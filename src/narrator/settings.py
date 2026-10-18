"""Render settings: defaults <- script front matter <- CLI overrides."""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class Settings:
    language: str = "es"
    voice: str = "voices/voice.wav"  # reference sample (10–20 s, clean, mono)
    lexicon: list[str] = field(default_factory=list)
    device: str = "auto"  # auto -> mps (Apple Silicon) | cuda | cpu
    # Chatterbox knobs (tuned for clone fidelity; raise exaggeration for livelier delivery)
    exaggeration: float = 0.35
    cfg_weight: float = 0.55
    temperature: float = 0.5
    seed: int = 1234
    # Quality loop
    takes: int = 3  # max candidates per sentence when ASR verification is on
    max_wer: float = 0.0  # accept first take at/below this word error rate
    asr: str = "auto"  # auto | mlx | faster-whisper | none
    asr_model: str = ""  # empty = backend default
    max_chunk_chars: int = 220
    # Pacing
    sentence_pause: float = 0.30
    paragraph_pause: float = 0.65
    segment_gap: float = 0.50  # between untimed segments
    lead_in: float = 0.0
    # Sync
    fps: float = 25.0
    min_gap: float = 0.15  # silence kept before the next timed cue
    max_stretch: float = 1.08  # max speed-up to fit a slot (1.08 = 8 % faster)
    # Output
    target_lufs: float = -16.0
    peak_dbfs: float = -1.0
    out_sample_rate: int = 48000

    @classmethod
    def build(cls, meta: dict, overrides: dict, base_dir: Path) -> Settings:
        names = {f.name for f in fields(cls)}
        given = {k: v for k, v in overrides.items() if v is not None}  # unset CLI flags keep front matter
        merged = {k: v for k, v in {**meta, **given}.items() if k in names}
        s = cls(**merged)
        if isinstance(s.lexicon, str):
            s.lexicon = [s.lexicon]
        s.voice = str(_resolve(s.voice, base_dir))
        s.lexicon = [str(_resolve(p, base_dir)) for p in s.lexicon]
        return s

    def segment_params(self, options: dict[str, str]) -> dict:
        """Per-segment overrides from cue options (exaggeration=, cfg=, temperature=, seed=, takes=)."""
        alias = {"cfg": "cfg_weight", "temp": "temperature", "exag": "exaggeration"}
        p = {"exaggeration": self.exaggeration, "cfg_weight": self.cfg_weight,
             "temperature": self.temperature, "seed": self.seed, "takes": self.takes,
             "language": self.language}
        for k, v in options.items():
            k = alias.get(k, k)
            if k in ("seed", "takes"):
                p[k] = int(v)
            elif k == "language":
                p[k] = v
            elif k in p:
                p[k] = float(v)
        return p


def _resolve(p: str, base: Path) -> Path:
    path = Path(p).expanduser()
    return path if path.is_absolute() else (base / path).resolve()
