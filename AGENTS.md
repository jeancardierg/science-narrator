# AGENTS.md — rules for Codex (and any coding agent)

## What this is
A CLI (`narrator`) that turns a timed script and a voice sample into a cloned-voice narration track. The track is synced to an existing video and checked for pronunciation. It runs locally on an Apple Silicon Mac.

The pipeline is: script parse → text normalization and lexicon → Chatterbox takes → Whisper round-trip score → best take → timeline placement and time-stretch → WAV, SRT and report.

## Layout
```
src/narrator/
  cli.py        argparse entry: check | render | mux | doctor
  script.py     .md/.srt parsing, timecodes, sentence splitting   (format contract: docs/SPEC.md)
  textnorm.py   verbalization (es/en), units, sci notation, lexicon, risky-token warnings
  engine.py     Engine protocol, ChatterboxEngine (mps/cuda/cpu), FakeEngine
  verify.py     ASR backends (mlx-whisper, faster-whisper), WER
  render.py     chunk planning, best-of-N takes, cache, timeline, SRT, report
  audio.py      trim, LUFS, time-stretch (rubberband/ffmpeg), ffmpeg I/O
  settings.py   Settings dataclass (defaults <- front matter <- CLI)
tests/          pytest, no network, no GPU
docs/SPEC.md    script format + outputs contract
docs/CODEX_TASKS.md  backlog, in order
```

## Commands
```bash
uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -e ".[dev]"   # light: no torch
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests
.venv/bin/narrator render examples/demo.es.md --fake      # end-to-end without models
```
On the Mac with models installed (`bash install.sh`): `narrator render examples/demo.es.md --video <file>`.

## Hard rules
- **Tests must not download models or need a GPU.** Use `FakeEngine` and `Verifier("none")`. Put real-model tests behind `@pytest.mark.slow` and skip them unless `NARRATOR_SLOW=1`.
- **The script format is a contract.** If you change the syntax, update `docs/SPEC.md`, `examples/` and the README table in the same change.
- **Cache keys** (`Renderer._key`) must include every input that affects the audio. If you add a synthesis knob, add it to the key.
- **Determinism:** the same script, settings and seed must give the same take choice. Never seed from the clock.
- **Never commit voice samples or generated media.** `voices/` and `*.wav` are gitignored, so keep it that way.
- **Python 3.11 only** (chatterbox-tts pins torch 2.6 and numpy < 1.26). Do not bump past `chatterbox-tts==0.1.7` without testing on MPS.
- Apple Silicon (MPS) is the primary target. Keep CUDA and CPU paths working, and never hard-code a device.
- No network calls except Hugging Face model downloads made by the libraries.
- Use the `ffmpeg_exe()` / `rubberband_exe()` helpers. Never shell out to a bare `ffmpeg`.
- Stay within the dependencies already in `pyproject.toml`. A new dependency needs a one-line justification in the PR description, and heavy ones go in an optional extra.

## Style
- Type hints, small functions, dataclasses for data, argparse for the CLI (no click or typer).
- Comments only for non-obvious "why" (model quirks, ffmpeg flags, language rules).
- Each `textnorm` rule needs a parametrized test with input and expected spoken output, for both `es` and `en` where it applies.

## Definition of done
`pytest -q` passes, `ruff check` is clean, the SPEC and README are updated if behaviour changed, and `narrator render examples/demo.es.md --fake` still exits 0.
