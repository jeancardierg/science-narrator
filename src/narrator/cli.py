"""narrator CLI: check | render | mux | doctor."""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from .audio import ffmpeg_exe, media_info, rubberband_exe
from .script import format_timecode, load_script
from .settings import Settings


def _settings(args: argparse.Namespace, script) -> Settings:
    overrides = {"voice": args.voice, "language": args.lang, "takes": args.takes, "asr": args.asr,
                 "device": args.device, "seed": args.seed}
    if args.lexicon:
        overrides["lexicon"] = args.lexicon
    return Settings.build(script.meta, overrides, script.base_dir)


def cmd_check(args: argparse.Namespace) -> int:
    """Print what the TTS will actually be asked to say, plus risky tokens. No audio."""
    from .render import plan_segment
    from .textnorm import load_lexicon

    script = load_script(args.script)
    s = _settings(args, script)
    lex = load_lexicon(s.lexicon)
    warnings = 0
    for seg in script.segments:
        p = s.segment_params(seg.options)
        when = format_timecode(seg.start) if seg.start is not None else "+"
        print(f"\n[{seg.index + 1}] {when} {seg.label}")
        for ch in plan_segment(seg, s, lex, p["language"]):
            print(f"   say: {ch.spoken}")
            for w in ch.warnings:
                warnings += 1
                print(f"   !!  {w}")
    print(f"\n{warnings} warning(s). Fix with lexicon entries or inline [term|respelling].")
    return 1 if warnings and args.strict else 0


def cmd_render(args: argparse.Namespace) -> int:
    from .engine import ChatterboxEngine, FakeEngine
    from .render import Renderer
    from .verify import Verifier

    script = load_script(args.script)
    s = _settings(args, script)
    engine = FakeEngine() if args.fake else ChatterboxEngine(s.voice, device=s.device)
    verifier = Verifier("none" if args.fake else s.asr, s.asr_model, s.language)
    out = Path(args.out or script.path.with_suffix("").as_posix() + "_out")
    video = Path(args.video) if args.video else None
    report = Renderer(script, s, engine, verifier).render(out, video=video)
    print(f"\nwrote {out / 'narration.wav'}  ({report['duration']:.1f}s)")
    print(f"      {out / 'narration.srt'}\n      {out / 'report.md'}")
    if report["flagged"]:
        print(f"{len(report['flagged'])} sentence(s) flagged for pronunciation review (see report.md)")
    for e in report["errors"]:
        print(f"ERROR: {e}", file=sys.stderr)
    if video and args.mux:
        mux(video, out / "narration.wav", out / f"{video.stem}_narrated{video.suffix}", args.duck)
    return 0 if report["ok"] or args.allow_overflow else 2


def mux(video: Path, narration: Path, dst: Path, duck_db: float | None) -> Path:
    """Copy video stream; replace audio (duck_db=None) or mix narration over original lowered by duck_db."""
    info = media_info(video)
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(video), "-i", str(narration)]
    if duck_db is None or not info["has_audio"]:
        cmd += ["-map", "0:v", "-map", "1:a"]
    else:
        cmd += ["-filter_complex",
                f"[0:a]volume={duck_db}dB[bg];[bg][1:a]amix=inputs=2:duration=first:normalize=0[a]",
                "-map", "0:v", "-map", "[a]"]
    cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-t", f"{info['duration']:.3f}", str(dst)]
    subprocess.run(cmd, check=True)
    print(f"wrote {dst}")
    return dst


def cmd_mux(args: argparse.Namespace) -> int:
    video = Path(args.video)
    dst = Path(args.out) if args.out else video.with_name(f"{video.stem}_narrated{video.suffix}")
    mux(video, Path(args.narration), dst, None if args.replace else args.duck)
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    ok = True
    print(f"python   {sys.version.split()[0]}  {platform.system()} {platform.machine()}")
    try:
        print(f"ffmpeg   {ffmpeg_exe()}")
    except RuntimeError as e:
        ok = False
        print(f"ffmpeg   MISSING ({e})")
    print(f"rubberband {rubberband_exe() or 'missing (brew install rubberband) -> ffmpeg atempo fallback'}")
    try:
        import torch

        from .engine import pick_device

        print(f"torch    {torch.__version__}  device={pick_device('auto')}")
    except ImportError:
        ok = False
        print("torch    MISSING (pip install -e '.[tts]')")
    for mod, hint in (("chatterbox", "pip install -e '.[tts]'"), ("mlx_whisper", "pip install -e '.[asr]' (Apple Silicon)"),
                      ("faster_whisper", "optional ASR fallback (non-Mac)")):
        try:
            __import__(mod)
            print(f"{mod:<14} ok")
        except ImportError:
            print(f"{mod:<14} missing — {hint}")
    hf = Path.home() / ".cache" / "huggingface" / "hub"
    cached = sorted(p.name for p in hf.glob("models--*")) if hf.is_dir() else []
    print(f"hf cache {hf} ({len(cached)} models)")
    print(f"disk free {shutil.disk_usage(Path.home()).free / 1e9:.1f} GB")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="narrator", description="Voice-cloned, video-synced science narration")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("script", help="script .md/.txt (timecode cues) or .srt")
        p.add_argument("--voice", help="reference sample (overrides front matter)")
        p.add_argument("--lang", help="language code (es, en, …)")
        p.add_argument("--lexicon", action="append", help="pronunciation lexicon YAML (repeatable)")
        p.add_argument("--takes", type=int, help="max takes per sentence")
        p.add_argument("--asr", choices=["auto", "mlx", "faster-whisper", "none"])
        p.add_argument("--device", choices=["auto", "mps", "cuda", "cpu"])
        p.add_argument("--seed", type=int)

    p = sub.add_parser("check", help="show normalized spoken text + pronunciation warnings")
    common(p)
    p.add_argument("--strict", action="store_true", help="exit 1 on warnings")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("render", help="synthesize narration.wav + .srt + report")
    common(p)
    p.add_argument("--out", help="output dir (default: <script>_out)")
    p.add_argument("--video", help="video to match length (and mux with --mux)")
    p.add_argument("--mux", action="store_true", help="also write <video>_narrated.mp4")
    p.add_argument("--duck", type=float, default=-14.0, help="original audio gain in dB when muxing")
    p.add_argument("--allow-overflow", action="store_true", help="exit 0 even if segments overflow")
    p.add_argument("--fake", action="store_true", help="tone placeholder engine (timing dry-run, no model)")
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("mux", help="put narration onto a video")
    p.add_argument("--video", required=True)
    p.add_argument("--narration", required=True)
    p.add_argument("--out")
    p.add_argument("--duck", type=float, default=-14.0)
    p.add_argument("--replace", action="store_true", help="drop original audio")
    p.set_defaults(fn=cmd_mux)

    p = sub.add_parser("doctor", help="check installation")
    p.set_defaults(fn=cmd_doctor)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
