#!/usr/bin/env bash
# One-shot installer for macOS (Apple Silicon). Re-runnable.
set -euo pipefail
cd "$(dirname "$0")"

[[ "$(uname -s)" == "Darwin" ]] || { echo "This installer targets macOS. See README > Development for other OSes."; exit 1; }
[[ "$(uname -m)" == "arm64" ]] || echo "WARNING: not Apple Silicon — synthesis will run on CPU (slow)."
command -v brew >/dev/null || { echo "Homebrew required: https://brew.sh"; exit 1; }

echo "==> system tools (ffmpeg, rubberband, uv)"
brew install ffmpeg rubberband uv

echo "==> python env (.venv, Python 3.11)"
uv venv --python 3.11 --allow-existing .venv
uv pip install --python .venv/bin/python -e ".[tts,asr,dev]"

mkdir -p "$HOME/.local/bin" voices
ln -sf "$PWD/.venv/bin/narrator" "$HOME/.local/bin/narrator"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "NOTE: add to ~/.zshrc ->  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

if [[ "${NARRATOR_PREFETCH:-1}" == "1" ]]; then
  echo "==> downloading models (~5 GB, once)"
  .venv/bin/python - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download("ResembleAI/chatterbox", allow_patterns=[
    "ve.pt", "t3_mtl23ls_v2.safetensors", "s3gen.pt",
    "grapheme_mtl_merged_expanded_v1.json", "conds.pt", "Cangjie5_TC.json"])
snapshot_download("mlx-community/whisper-large-v3-turbo")
PY
fi

echo "==> doctor"
.venv/bin/narrator doctor
echo
echo "Done. Next: record voices/voice.wav (README §1), then:"
echo "  narrator check examples/demo.es.md"
echo "  narrator render examples/demo.es.md --fake"
