"""Parse narration scripts (.md/.txt with timecode cues, or .srt) into segments."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

TC_RE = r"[\d:.,]+"
CUE_RE = re.compile(rf"^\[\s*(?P<a>{TC_RE}|\+[\d.]*)\s*(?:(?:-{{1,2}}>|–)\s*(?P<b>{TC_RE})\s*)?\](?P<rest>.*)$")
OPT_RE = re.compile(r"(\w+)=(\S+)")
PAUSE_RE = re.compile(r"\{pause[ =](?P<s>[\d.]+)\}")
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


@dataclass
class Segment:
    index: int
    text: str
    start: float | None = None  # None = right after previous segment
    end: float | None = None  # hard end of slot (optional)
    gap: float | None = None  # for "[+0.8]" cues
    label: str = ""
    options: dict[str, str] = field(default_factory=dict)


@dataclass
class Script:
    path: Path
    meta: dict
    segments: list[Segment]

    @property
    def base_dir(self) -> Path:
        return self.path.parent


def parse_timecode(tc: str, fps: float = 25.0) -> float:
    """HH:MM:SS.mmm | HH:MM:SS,mmm | MM:SS.s | SS.s | HH:MM:SS:FF (frames)."""
    tc = tc.strip().replace(",", ".")
    parts = tc.split(":")
    if len(parts) == 4:
        h, m, s, f = (float(p) for p in parts)
        return h * 3600 + m * 60 + s + f / fps
    total = 0.0
    for p in parts:
        total = total * 60 + float(p)
    return total


def format_timecode(t: float, sep: str = ".") -> str:
    ms = round(t * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _split_front_matter(raw: str) -> tuple[dict, str]:
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            meta = yaml.safe_load(raw[3:end]) or {}
            return meta, raw[end + 4:].lstrip("\n")
    return {}, raw


def parse_markdown(raw: str, fps: float | None = None) -> tuple[dict, list[Segment]]:
    meta, body = _split_front_matter(raw)
    fps = float(fps or meta.get("fps", 25))
    body = COMMENT_RE.sub("", body)
    segments: list[Segment] = []
    cur: Segment | None = None
    lines: list[str] = []

    def flush() -> None:
        nonlocal cur, lines
        text = "\n".join(lines).strip()
        if cur is None and text:
            cur = Segment(index=0, text="")
        if cur is not None and text:
            cur.text = text
            cur.index = len(segments)
            segments.append(cur)
        cur, lines = None, []

    for line in body.splitlines():
        m = CUE_RE.match(line.strip())
        if m:
            flush()
            a, b, rest = m.group("a"), m.group("b"), m.group("rest")
            seg = Segment(index=0, text="")
            if a.startswith("+"):
                seg.gap = float(a[1:]) if len(a) > 1 else None
            else:
                seg.start = parse_timecode(a, fps)
            if b:
                seg.end = parse_timecode(b, fps)
            seg.options = dict(OPT_RE.findall(rest))
            seg.label = OPT_RE.sub("", rest).strip(" |-")
            cur = seg
            continue
        if line.lstrip().startswith("#") and cur is None and not lines:
            continue  # markdown headings outside segments are titles
        lines.append(line)
    flush()
    return meta, segments


def parse_srt(raw: str) -> list[Segment]:
    segments: list[Segment] = []
    for block in re.split(r"\n\s*\n", raw.strip().replace("\r\n", "\n")):
        rows = [r for r in block.splitlines() if r.strip()]
        ti = next((i for i, r in enumerate(rows) if "-->" in r), None)
        if ti is None:
            continue
        a, b = (p.strip().split(" ")[0] for p in rows[ti].split("-->"))
        text = " ".join(rows[ti + 1:]).strip()
        if text:
            segments.append(Segment(index=len(segments), text=text,
                                    start=parse_timecode(a), end=parse_timecode(b)))
    return segments


def load_script(path: str | Path) -> Script:
    path = Path(path).resolve()
    raw = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".srt":
        meta: dict = {}
        sidecar = path.with_suffix(".yaml")
        if sidecar.is_file():
            meta = yaml.safe_load(sidecar.read_text(encoding="utf-8")) or {}
        segments = parse_srt(raw)
    else:
        meta, segments = parse_markdown(raw)
    if not segments:
        raise ValueError(f"{path}: no narration text found")
    return Script(path=path, meta=meta, segments=segments)


def split_sentences(text: str) -> list[tuple[str, float | None, bool]]:
    """Split segment text into (sentence, explicit_pause_after, paragraph_end).

    Handles `{pause 0.8}` markers and blank-line paragraph breaks. Keeps
    `[term|respelling]` markup intact (no splitting inside brackets).
    """
    out: list[tuple[str, float | None, bool]] = []
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    for pi, para in enumerate(paragraphs):
        para = " ".join(para.split())
        pieces = PAUSE_RE.split(para)
        # PAUSE_RE.split -> [text, pause, text, pause, ...]
        for i in range(0, len(pieces), 2):
            chunk = pieces[i].strip()
            pause = float(pieces[i + 1]) if i + 1 < len(pieces) else None
            sents = [s for s in _SENT_RE.split(chunk) if s.strip()] if chunk else []
            for si, s in enumerate(sents):
                last = si == len(sents) - 1
                out.append((s.strip(), pause if last else None, False))
            if not sents and pause and out:
                prev = out[-1]
                out[-1] = (prev[0], (prev[1] or 0) + pause, prev[2])
        if out and pi < len(paragraphs):
            s, p, _ = out[-1]
            out[-1] = (s, p, True)
    return out


_ABBREVS = ("Sr.", "Sra.", "Dr.", "Dra.", "ej.", "e.g.", "i.e.", "vs.", "p.", "fig.", "Fig.", "approx.")
_ABBREV = "".join(rf"(?<!\b{re.escape(a)})" for a in _ABBREVS)
_SENT_RE = re.compile(rf"(?<=[.!?…]){_ABBREV}\s+(?=[\"'«“(¿¡\[A-ZÁÉÍÓÚÑ])")
