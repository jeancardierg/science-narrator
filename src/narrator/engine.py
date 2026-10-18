"""TTS engines. Chatterbox Multilingual (zero-shot clone) + a fake for tests.

Ported from flat-hunter-bcn voice/tts_chatterbox.py: lazy model load, device
pick with loud fallback, mp3 reference conversion. Adds Apple Silicon (MPS),
cached speaker conditionals and seeded takes.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Protocol

import numpy as np

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")


class Engine(Protocol):
    name: str
    sample_rate: int

    def synth(self, text: str, *, language: str, exaggeration: float, cfg_weight: float,
              temperature: float, seed: int) -> np.ndarray: ...

    def fingerprint(self) -> str: ...


def file_sha1(path: str | Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def pick_device(requested: str = "auto") -> str:
    import torch

    req = (requested or "auto").lower()
    if req in ("auto", "mps") and torch.backends.mps.is_available():
        return "mps"
    if req in ("auto", "cuda") and torch.cuda.is_available():
        return "cuda"
    if req not in ("auto", "cpu"):
        print(f"[tts] WARNING: device {req!r} unavailable (torch={torch.__version__}) -> cpu (slow)",
              file=sys.stderr, flush=True)
    return "cpu"


def ensure_wav_reference(path: Path) -> Path:
    """Convert non-wav references (mp3/m4a/…) to 24 kHz mono wav next to the source."""
    if path.suffix.lower() == ".wav":
        return path
    import subprocess

    from .audio import ffmpeg_exe

    wav = path.with_suffix(".ref24k.wav")
    if not wav.is_file():
        subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(path), "-ac", "1",
                        "-ar", "24000", str(wav)], check=True)
        print(f"[tts] converted {path.name} -> {wav.name}", flush=True)
    return wav


class ChatterboxEngine:
    name = "chatterbox-mtl"

    def __init__(self, reference: str | Path, device: str = "auto") -> None:
        ref = Path(reference)
        if not ref.is_file():
            raise FileNotFoundError(
                f"voice reference not found: {ref}\n"
                "Record 10–20 s of clean speech (see README > Voice sample).")
        self.reference = ensure_wav_reference(ref)
        self.requested_device = device
        self.device: str | None = None
        self.sample_rate = 24000
        self._model = None
        self._ref_sha = file_sha1(self.reference)

    def fingerprint(self) -> str:
        return f"{self.name}:{self._ref_sha}"

    def _ensure(self) -> None:
        if self._model is not None:
            return
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        self.device = pick_device(self.requested_device)
        try:
            self._model = ChatterboxMultilingualTTS.from_pretrained(device=self.device)
        except Exception as exc:
            if self.device == "cpu":
                raise
            print(f"[tts] WARNING: load on {self.device} failed ({exc}); retrying on cpu",
                  file=sys.stderr, flush=True)
            self.device = "cpu"
            self._model = ChatterboxMultilingualTTS.from_pretrained(device="cpu")
        self.sample_rate = int(getattr(self._model, "sr", 24000))
        self._model.prepare_conditionals(str(self.reference))
        print(f"[tts] chatterbox ready on {self.device}; voice={self.reference}", flush=True)

    def synth(self, text: str, *, language: str, exaggeration: float, cfg_weight: float,
              temperature: float, seed: int) -> np.ndarray:
        import torch

        self._ensure()
        torch.manual_seed(seed)
        np.random.seed(seed % (2**32))
        wav = self._model.generate(text, language_id=language, exaggeration=exaggeration,
                                   cfg_weight=cfg_weight, temperature=temperature)
        if hasattr(wav, "cpu"):
            wav = wav.cpu().numpy()
        return np.asarray(wav, dtype=np.float32).reshape(-1)


class FakeEngine:
    """Deterministic tone per character — for tests and dry runs (no model download)."""

    name = "fake"
    sample_rate = 24000

    def __init__(self, cps: float = 15.0) -> None:
        self.cps = cps
        self.calls: list[str] = []

    def fingerprint(self) -> str:
        return f"fake:{self.cps}"

    def synth(self, text: str, *, language: str, exaggeration: float, cfg_weight: float,
              temperature: float, seed: int) -> np.ndarray:
        self.calls.append(text)
        n = max(int(len(text) / self.cps * self.sample_rate), self.sample_rate // 10)
        t = np.arange(n) / self.sample_rate
        tone = 0.2 * np.sin(2 * np.pi * (180 + seed % 40) * t)
        pad = np.zeros(self.sample_rate // 10, dtype=np.float32)
        return np.concatenate([pad, tone.astype(np.float32), pad])
