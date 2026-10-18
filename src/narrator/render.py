"""Script -> per-sentence takes (best-of-N, ASR-checked) -> timed narration track."""
from __future__ import annotations

import hashlib
import json
import re
import textwrap
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

from . import __version__
from .audio import loudness_normalize, media_info, peak_guard, time_stretch, trim_silence, write_wav
from .engine import Engine
from .script import Script, Segment, format_timecode, split_sentences
from .settings import Settings
from .textnorm import RESPELL_RE, load_lexicon, normalize, risky_tokens
from .verify import Verifier

COMMA_PAUSE = 0.12
MIN_CHUNK_CHARS = 40
CPS_RANGE = (6.0, 25.0)  # plausible spoken chars/second; outside -> likely babble or truncation


@dataclass
class Chunk:
    display: str
    spoken: str
    pause_after: float
    warnings: list[str] = field(default_factory=list)
    wer: float | None = None
    heard: str = ""
    take: int = 0
    takes_tried: int = 0
    offset: float = 0.0  # seconds from segment start (after stretch)
    duration: float = 0.0


@dataclass
class SegmentResult:
    index: int
    label: str
    start: float
    slot_end: float | None
    duration: float = 0.0
    speed: float = 1.0
    status: str = "ok"  # ok | stretched | overflow | overlap
    chunks: list[Chunk] = field(default_factory=list)
    file: str = ""


def _split_long(sentence: str, lang: str, lexicon: dict, max_chars: int) -> list[str]:
    """Split an over-long sentence at , ; : — (outside [..|..] markup), then at words."""
    if len(normalize(sentence, lang, lexicon)[1]) <= max_chars:
        return [sentence]
    protected = RESPELL_RE.sub(lambda m: m.group(0).replace(",", "\0").replace(" ", "\1"), sentence)
    parts = [p.replace("\0", ",").replace("\1", " ") for p in re.split(r"(?<=[,;:—])\s+", protected)]
    out: list[str] = []
    for p in parts:
        if out and len(normalize(out[-1] + " " + p, lang, lexicon)[1]) <= max_chars:
            out[-1] = f"{out[-1]} {p}"
        else:
            out.append(p)
    final: list[str] = []
    for p in out:  # still too long: hard split on words
        words, cur = p.split(" "), ""
        for w in words:
            if cur and len(normalize(f"{cur} {w}", lang, lexicon)[1]) > max_chars:
                final.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            final.append(cur)
    return final


def _merge_short(sentences: list[tuple[str, float | None, bool]], lang: str, lexicon: dict,
                 min_chars: int) -> list[tuple[str, float | None, bool]]:
    """Join very short sentences with the next one: the model phrases better with context."""
    out: list[tuple[str, float | None, bool]] = []
    for sent in sentences:
        if out:
            prev, pause, para = out[-1]
            if pause is None and not para and len(normalize(prev, lang, lexicon)[1]) < min_chars:
                out[-1] = (f"{prev} {sent[0]}", sent[1], sent[2])
                continue
        out.append(sent)
    return out


def plan_segment(seg: Segment, s: Settings, lexicon: dict, lang: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    sentences = _merge_short(split_sentences(seg.text), lang, lexicon, MIN_CHUNK_CHARS)
    for sentence, pause, para_end in sentences:
        pieces = _split_long(sentence, lang, lexicon, s.max_chunk_chars)
        for i, piece in enumerate(pieces):
            display, spoken = normalize(piece, lang, lexicon)
            last = i == len(pieces) - 1
            if not last:
                gap = COMMA_PAUSE
            elif pause is not None:
                gap = pause
            else:
                gap = s.paragraph_pause if para_end else s.sentence_pause
            chunks.append(Chunk(display=display, spoken=spoken, pause_after=gap, warnings=risky_tokens(spoken)))
    return chunks


class Renderer:
    def __init__(self, script: Script, settings: Settings, engine: Engine, verifier: Verifier,
                 cache_dir: Path | None = None) -> None:
        self.script = script
        self.s = settings
        self.engine = engine
        self.verifier = verifier
        self.lexicon = load_lexicon(settings.lexicon)
        # Inline [term|respelling] pairs also normalize ASR output (it hears "ATP", not "a te pe").
        self.asr_lexicon = dict(self.lexicon)
        for seg in script.segments:
            for term, spoken in RESPELL_RE.findall(seg.text):
                self.asr_lexicon.setdefault(term, spoken)
        self.cache = cache_dir or script.base_dir / ".narrator-cache"
        self.cache.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ takes
    def _key(self, spoken: str, p: dict) -> str:
        blob = json.dumps([__version__, self.engine.fingerprint(), spoken, p, self.verifier.backend,
                           self.verifier.model, self.s.max_wer], sort_keys=True, ensure_ascii=False)
        return hashlib.sha1(blob.encode()).hexdigest()

    def synth_chunk(self, chunk: Chunk, p: dict) -> np.ndarray:
        sr = self.engine.sample_rate
        key = self._key(chunk.spoken, p)
        wav_path, meta_path = self.cache / f"{key}.wav", self.cache / f"{key}.json"
        if wav_path.is_file() and meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            chunk.wer, chunk.heard, chunk.take, chunk.takes_tried = (
                meta["wer"], meta["heard"], meta["take"], meta["takes_tried"])
            return sf.read(wav_path, dtype="float32")[0]

        n = p["takes"] if self.verifier.enabled else 1
        best: tuple[float, int, np.ndarray, float | None, str] | None = None
        tried = 0
        for k in range(max(n, 1)):
            tried += 1
            raw = self.engine.synth(chunk.spoken, language=p["language"], exaggeration=p["exaggeration"],
                                    cfg_weight=p["cfg_weight"], temperature=p["temperature"],
                                    seed=p["seed"] + 7919 * k)
            wav = trim_silence(raw, sr)
            dur = wav.size / sr
            cps = len(chunk.spoken) / dur if dur else 0.0
            penalty = 0.0 if CPS_RANGE[0] <= cps <= CPS_RANGE[1] else 0.5
            wer, heard = (self.verifier.score(wav, sr, chunk.spoken, p["language"], self.asr_lexicon)
                          if self.verifier.enabled else (None, ""))
            score = (wer or 0.0) + penalty
            if best is None or score < best[0]:
                best = (score, k, wav, wer, heard)
            if self.verifier.enabled and wer is not None and wer <= self.s.max_wer and penalty == 0:
                break
        assert best is not None
        _, chunk.take, wav, chunk.wer, chunk.heard = best
        chunk.takes_tried = tried
        sf.write(wav_path, wav, sr, subtype="FLOAT")
        meta_path.write_text(json.dumps({"wer": chunk.wer, "heard": chunk.heard, "take": chunk.take,
                                         "takes_tried": tried, "spoken": chunk.spoken},
                                        ensure_ascii=False), encoding="utf-8")
        return wav

    def render_segment(self, seg: Segment) -> tuple[list[Chunk], np.ndarray]:
        p = self.s.segment_params(seg.options)
        chunks = plan_segment(seg, self.s, self.lexicon, p["language"])
        sr = self.engine.sample_rate
        parts: list[np.ndarray] = []
        t = 0.0
        for i, ch in enumerate(chunks):
            wav = self.synth_chunk(ch, p)
            ch.offset, ch.duration = t, wav.size / sr
            parts.append(wav)
            t += ch.duration
            if i < len(chunks) - 1:
                parts.append(np.zeros(int(ch.pause_after * sr), dtype=np.float32))
                t += ch.pause_after
        audio = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
        return chunks, loudness_normalize(audio, sr, self.s.target_lufs)

    # ------------------------------------------------------------ timeline
    def render(self, out_dir: Path, video: Path | None = None, log=print) -> dict:
        sr = self.engine.sample_rate
        segs = self.script.segments
        rendered: list[tuple[SegmentResult, np.ndarray]] = []
        errors: list[str] = []
        cursor = self.s.lead_in
        for i, seg in enumerate(segs):
            log(f"[{i + 1}/{len(segs)}] {seg.label or seg.text[:50]!r}")
            chunks, audio = self.render_segment(seg)
            if seg.start is not None:
                start = seg.start
            else:
                start = cursor + (seg.gap if seg.gap is not None else (self.s.segment_gap if i else 0.0))
            nxt = next((x.start for x in segs[i + 1:] if x.start is not None), None)
            slot_end = seg.end if seg.end is not None else (nxt - self.s.min_gap if nxt is not None else None)
            res = SegmentResult(index=i + 1, label=seg.label, start=start, slot_end=slot_end, chunks=chunks)
            dur = audio.size / sr
            if start < cursor - 1e-3:
                res.status = "overlap"
                errors.append(f"segment {i + 1} starts at {format_timecode(start)} but previous narration "
                              f"runs until {format_timecode(cursor)}")
            if slot_end is not None and dur > slot_end - start + 1e-3:
                need = dur / max(slot_end - start, 1e-3)
                if need <= self.s.max_stretch:
                    audio = time_stretch(audio, sr, need)
                    res.speed, res.status = need, "stretched"
                else:
                    res.status = "overflow"
                    errors.append(f"segment {i + 1} needs {dur:.2f}s but slot is {slot_end - start:.2f}s "
                                  f"(x{need:.2f} > max_stretch {self.s.max_stretch}); shorten the text "
                                  f"or move the next cue")
            res.duration = audio.size / sr
            for ch in chunks:
                ch.offset /= res.speed
                ch.duration /= res.speed
            cursor = start + res.duration
            rendered.append((res, audio))

        total = cursor
        if video:
            total = max(total, media_info(video)["duration"])
        track = np.zeros(int(total * sr) + 1, dtype=np.float32)
        out_dir.mkdir(parents=True, exist_ok=True)
        seg_dir = out_dir / "segments"
        for res, audio in rendered:
            a = int(res.start * sr)
            track[a:a + audio.size] += audio[: max(track.size - a, 0)]
            slug = re.sub(r"[^\w-]+", "_", res.label).strip("_")[:30]
            f = write_wav(seg_dir / f"{res.index:03d}{'_' + slug if slug else ''}.wav",
                          peak_guard(audio, self.s.peak_dbfs), sr, self.s.out_sample_rate)
            res.file = str(f.relative_to(out_dir))
        write_wav(out_dir / "narration.wav", peak_guard(track, self.s.peak_dbfs), sr, self.s.out_sample_rate)
        (out_dir / "narration.srt").write_text(to_srt([r for r, _ in rendered]), encoding="utf-8")

        report = build_report(self.script, self.s, [r for r, _ in rendered], errors, total,
                              self.engine, self.verifier)
        (out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        (out_dir / "report.md").write_text(report_markdown(report), encoding="utf-8")
        return report


def to_srt(results: list[SegmentResult]) -> str:
    lines: list[str] = []
    n = 0
    for res in results:
        for ch in res.chunks:
            n += 1
            a = res.start + ch.offset
            text = "\n".join(textwrap.wrap(ch.display, 42)) or ch.display
            lines += [str(n), f"{format_timecode(a, ',')} --> {format_timecode(a + ch.duration, ',')}", text, ""]
    return "\n".join(lines)


def build_report(script: Script, s: Settings, results: list[SegmentResult], errors: list[str],
                 total: float, engine: Engine, verifier: Verifier) -> dict:
    flagged = []
    for r in results:
        for ch in r.chunks:
            if ch.warnings or (ch.wer is not None and ch.wer > s.max_wer):
                flagged.append({"segment": r.index, "text": ch.display, "spoken": ch.spoken,
                                "heard": ch.heard, "wer": ch.wer, "warnings": ch.warnings})
    return {
        "version": __version__,
        "script": str(script.path),
        "engine": engine.fingerprint(),
        "asr": f"{verifier.backend}:{verifier.model}" if verifier.enabled else "off",
        "duration": round(total, 3),
        "ok": not errors,
        "errors": errors,
        "flagged": flagged,
        "settings": asdict(s),
        "segments": [asdict(r) for r in results],
    }


def report_markdown(rep: dict) -> str:
    out = ["# Narration report\n", f"- script: `{rep['script']}`", f"- duration: {rep['duration']:.2f}s",
           f"- engine: `{rep['engine']}`  asr: `{rep['asr']}`", f"- status: {'OK' if rep['ok'] else 'ERRORS'}\n"]
    if rep["errors"]:
        out += ["## Errors", *[f"- {e}" for e in rep["errors"]], ""]
    if rep["flagged"]:
        out += ["## Check pronunciation", "| seg | text | heard | WER | warnings |", "|---|---|---|---|---|"]
        for f in rep["flagged"]:
            wer = "" if f["wer"] is None else f"{f['wer']:.2f}"
            out.append(f"| {f['segment']} | {f['text']} | {f['heard']} | {wer} | {'; '.join(f['warnings'])} |")
        out.append("")
    out += ["## Segments", "| # | start | slot end | dur | speed | status | label |", "|---|---|---|---|---|---|---|"]
    for sgm in rep["segments"]:
        end = "" if sgm["slot_end"] is None else format_timecode(sgm["slot_end"])
        out.append(f"| {sgm['index']} | {format_timecode(sgm['start'])} | {end} | {sgm['duration']:.2f} | "
                   f"{sgm['speed']:.3f} | {sgm['status']} | {sgm['label']} |")
    return "\n".join(out) + "\n"
