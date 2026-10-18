"""Audio helpers: trimming, loudness, time-stretch, ffmpeg I/O."""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf


@lru_cache(maxsize=1)
def ffmpeg_exe() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as exc:
        raise RuntimeError("ffmpeg not found (macOS: brew install ffmpeg)") from exc


def rubberband_exe() -> str | None:
    return shutil.which("rubberband")


def trim_silence(wav: np.ndarray, sr: int, threshold_db: float = -45.0, pad: float = 0.04) -> np.ndarray:
    """Trim leading/trailing silence (frame RMS below threshold relative to peak)."""
    if wav.size == 0:
        return wav
    frame = max(int(sr * 0.01), 1)
    n = wav.size // frame
    if n == 0:
        return wav
    rms = np.sqrt(np.mean(wav[: n * frame].reshape(n, frame) ** 2, axis=1) + 1e-12)
    ref = float(np.max(np.abs(wav))) + 1e-12
    loud = np.where(20 * np.log10(rms / ref) > threshold_db)[0]
    if loud.size == 0:
        return wav[:0]
    a = max(loud[0] * frame - int(pad * sr), 0)
    b = min((loud[-1] + 1) * frame + int(pad * sr), wav.size)
    out = wav[a:b].copy()
    fade = min(int(0.005 * sr), out.size // 2)
    if fade:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        out[:fade] *= ramp
        out[-fade:] *= ramp[::-1]
    return out


def loudness_normalize(wav: np.ndarray, sr: int, target_lufs: float) -> np.ndarray:
    if wav.size < int(0.5 * sr):
        return wav
    import pyloudnorm as pyln

    meter = pyln.Meter(sr)
    lufs = meter.integrated_loudness(wav.astype(np.float64))
    if not np.isfinite(lufs):
        return wav
    return (wav * (10 ** ((target_lufs - lufs) / 20))).astype(np.float32)


def peak_guard(wav: np.ndarray, peak_dbfs: float) -> np.ndarray:
    peak = float(np.max(np.abs(wav))) if wav.size else 0.0
    limit = 10 ** (peak_dbfs / 20)
    if peak > limit:
        wav = wav * (limit / peak)
    return wav.astype(np.float32)


def time_stretch(wav: np.ndarray, sr: int, speed: float) -> np.ndarray:
    """Speed up (>1) or slow down (<1) without pitch change. rubberband if installed, else ffmpeg atempo."""
    if abs(speed - 1.0) < 1e-3:
        return wav
    with tempfile.TemporaryDirectory() as td:
        src, dst = Path(td) / "in.wav", Path(td) / "out.wav"
        sf.write(src, wav, sr, subtype="FLOAT")
        rb = rubberband_exe()
        if rb:
            cmd = [rb, "-q", "-3", "--time", f"{1 / speed:.6f}", str(src), str(dst)]
        else:
            cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(src),
                   "-filter:a", f"atempo={speed:.6f}", str(dst)]
        subprocess.run(cmd, check=True, capture_output=True)
        out, _ = sf.read(dst, dtype="float32")
    return out.reshape(-1) if out.ndim == 1 else out.mean(axis=1)


def write_wav(path: str | Path, wav: np.ndarray, sr: int, out_sr: int) -> Path:
    """Write 24-bit PCM at out_sr (resampled with ffmpeg/soxr-quality swr)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if sr == out_sr:
        sf.write(path, wav, sr, subtype="PCM_24")
        return path
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "src.wav"
        sf.write(tmp, wav, sr, subtype="FLOAT")
        base = [ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(tmp)]
        tail = ["-ar", str(out_sr), "-c:a", "pcm_s24le", str(path)]
        try:  # soxr = best quality; Homebrew ffmpeg has it, some static builds don't
            subprocess.run([*base, "-af", "aresample=resampler=soxr:precision=28", *tail],
                           check=True, capture_output=True)
        except subprocess.CalledProcessError:
            subprocess.run([*base, *tail], check=True, capture_output=True)
    return path


def media_info(path: str | Path) -> dict:
    """Duration (s) and whether an audio stream exists, parsed from `ffmpeg -i`."""
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True, check=False)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    if not m:
        raise RuntimeError(f"cannot read media info for {path}")
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return {"duration": dur, "has_audio": bool(re.search(r"Stream #\S+.*Audio:", r.stderr))}


def resample(wav: np.ndarray, sr: int, target: int) -> np.ndarray:
    if sr == target:
        return wav
    from math import gcd

    from scipy.signal import resample_poly

    g = gcd(sr, target)
    return resample_poly(wav, target // g, sr // g).astype(np.float32)
