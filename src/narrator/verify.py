"""ASR round-trip check: transcribe each take, score it against the script text."""
from __future__ import annotations

import sys

import numpy as np

from .audio import resample
from .textnorm import canon_words, normalize

DEFAULT_MODELS = {"mlx": "mlx-community/whisper-large-v3-turbo", "faster-whisper": "large-v3-turbo"}


def word_error_rate(ref: list[str], hyp: list[str]) -> float:
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / len(ref)


class Verifier:
    def __init__(self, backend: str = "auto", model: str = "", language: str = "es") -> None:
        self.language = language
        self.backend = self._pick(backend)
        self.model = model or DEFAULT_MODELS.get(self.backend, "")
        self._fw = None

    @staticmethod
    def _pick(backend: str) -> str:
        if backend == "none":
            return "none"
        if backend in ("auto", "mlx"):
            try:
                import mlx_whisper  # noqa: F401

                return "mlx"
            except ImportError:
                if backend == "mlx":
                    raise
        try:
            import faster_whisper  # noqa: F401

            return "faster-whisper"
        except ImportError:
            if backend == "faster-whisper":
                raise
        print("[asr] WARNING: no ASR backend installed -> pronunciation check OFF", file=sys.stderr)
        return "none"

    @property
    def enabled(self) -> bool:
        return self.backend != "none"

    def transcribe(self, wav: np.ndarray, sr: int, language: str | None = None) -> str:
        lang = language or self.language
        audio = resample(wav, sr, 16000)
        if self.backend == "mlx":
            import mlx_whisper

            out = mlx_whisper.transcribe(audio, path_or_hf_repo=self.model, language=lang,
                                         condition_on_previous_text=False, temperature=0.0)
            return out.get("text", "").strip()
        if self.backend == "faster-whisper":
            if self._fw is None:
                from faster_whisper import WhisperModel

                self._fw = WhisperModel(self.model, device="auto", compute_type="default")
            segs, _ = self._fw.transcribe(audio, language=lang, beam_size=5,
                                          condition_on_previous_text=False, vad_filter=False)
            return " ".join(s.text for s in segs).strip()
        return ""

    def score(self, wav: np.ndarray, sr: int, spoken: str, language: str,
              lexicon: dict[str, str]) -> tuple[float, str]:
        """(WER vs expected spoken text, raw transcript). ASR output is normalized with the same lexicon."""
        heard = self.transcribe(wav, sr, language)
        hyp = canon_words(normalize(heard, language, lexicon)[1]) if heard else []
        return word_error_rate(canon_words(spoken), hyp), heard
