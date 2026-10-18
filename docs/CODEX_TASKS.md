# Codex backlog

Do these in order. Each task fits one Codex session on the Plus plan.

## How to run it with a Plus subscription
- Use the **Codex CLI on the Mac** (`npm i -g @openai/codex`, then `codex` from the repo root) or the Codex IDE extension. Working locally means Codex can run the real model on MPS with your voice file. Codex cloud tasks can't see `voices/` or download the 5 GB of models in a useful way.
- Start every session with: *"Read AGENTS.md and docs/SPEC.md, then do task N from docs/CODEX_TASKS.md. Run the tests before finishing."*
- One task per session, and commit after each one, so a bad task is easy to revert.
- For the Plus usage limits: keep tasks small (they already are), use a lighter reasoning setting for the mechanical tasks (3, 5, 8), and the higher one for 2, 4 and 6.

---

### 0. Smoke test on the Mac *(you, about 10 min)*
`bash install.sh`, then record `voices/voice.wav`, then run `narrator check examples/demo.es.md` and `narrator render examples/demo.es.md`. Listen to the result. If the MPS load fails, paste the traceback into Codex as task 0b: *"Make ChatterboxEngine work on MPS on this machine; keep the CPU fallback."*

### 1. Real-model regression test (slow)
> Add `tests/test_slow_chatterbox.py`, marked `@pytest.mark.slow` and skipped unless `NARRATOR_SLOW=1` and `voices/voice.wav` exists. It renders `examples/demo.es.md` with `--asr auto` and asserts the following: `report.ok`, every chunk's WER ≤ 0.15, the length of `narration.wav` matches the report, and nothing is clipped (peak ≤ -1 dBFS). Register the `slow` marker in pyproject.

### 2. Timeline export for editors (FCPXML + OTIO)
> Add `--timeline fcpxml|otio` to `render`. It writes `timeline.fcpxml` (FCPXML 1.10, importable in DaVinci Resolve and Final Cut Pro) and/or `timeline.otio`. Each `segments/NNN.wav` is placed as a clip at its `start`, on an audio track named "Narration", with a marker per segment carrying the label. Put `opentimelineio` in a new optional extra `timeline`. Write the FCPXML by hand with `xml.etree`, so it needs no extra dependency. Test with FakeEngine by parsing the XML and checking clip offsets in frames at 25 fps.

### 3. Cues from the editor
> Add `narrator cues <file>`, which converts editor exports into a script skeleton `.md` with one `[HH:MM:SS.mmm] label` line per marker, followed by an empty line for the text:
> (a) DaVinci Resolve marker EDL (`Timeline → Export → Timeline Markers to EDL`); (b) an SRT (keeps the text); (c) Final Cut / Resolve FCPXML markers.
> Test against small fixture files in `tests/fixtures/`.

### 4. Cues from a scratch voice-over
> Add `narrator cues --from-audio <video>`. If the existing video has a rough or temporary narration, transcribe it with the ASR backend using word timestamps (mlx-whisper `word_timestamps=True`, faster-whisper `word_timestamps=True`). Write a `.md` script with one cue per sentence, holding the transcribed text and `[start -> end]` slots, so you can rewrite the text and re-render it in your cloned voice at the same timing. Keep the ASR model in memory once. Add a unit test with a fake transcriber.

### 5. Better subtitles
> Make `narration.srt` follow broadcast rules. The limits are: at most 2 lines of 42 characters, cue length between 1.0 and 7.0 s, and at most 17 characters per second. Long chunks are split at word level, using word timestamps from the ASR verification pass when they're available and proportional-by-characters timing when they aren't. Store word timestamps in the chunk cache JSON. Add tests.

### 6. Sidechain ducking and music bed
> In `mux`, add `--duck-mode constant|sidechain` (default sidechain) using ffmpeg `sidechaincompress`, so the original audio drops only while narration is playing. Add `--music <file> --music-db -22`, which loops or trims the music to the video length. Loudness-normalize the final mix to -14 LUFS integrated with `loudnorm` two-pass. Test by building the ffmpeg command, without running it.

### 7. Voice sample prep
> Add `narrator prep-voice <in> [-o voices/voice.wav]`. It converts to mono 24 kHz, applies a high-pass at 80 Hz, trims silence and normalizes to -20 LUFS. It warns when the sample is under 10 s or over 30 s, when it clips, when estimated SNR is below 25 dB (noise floor taken from the quietest 10 % of frames), or when DC offset is present. Add an optional `--denoise` using ffmpeg `afftdn` (no new dependencies). Add tests with synthetic signals.

### 8. Pronunciation helpers
> Add `narrator lexicon suggest <script> [-o lexicon.yaml]`. It collects every risky-token warning across the script and appends stub entries (`TERM: TODO`) to the lexicon without touching existing ones. Two default rules come with it: unknown ALLCAPS acronyms of 2–5 letters are **spelled letter by letter** in the target language (es: a, be, ce, de, …; en: A, B, C …), with a warning that this is a fallback; and chemical formulas like `H2O` and `CO2` are verbalized as letters and digits. Use parametrized tests in both languages.

### 9. Review report with audio
> Generate `report.html`: one row per chunk with an `<audio>` element for the chosen take and links to the alternative takes, the spoken text, what Whisper heard, the WER and warnings. Keep all takes in the cache (`<key>.take<k>.wav`). Add `narrator pick <segment>.<chunk> <take>` to pin a chosen take (stored in `<script>.picks.yaml` and respected by render), and `narrator retake <segment>[.<chunk>]` to bump that chunk's seed offset (stored in the same picks file).

### 10. textnorm coverage
> Extend `textnorm` with the following, each with tests:
> - ordinals (`1.º`, `2ª`, `1st`, `3rd`)
> - Roman numerals in centuries (`siglo XX` → `siglo veinte`)
> - percent ranges (`5–10 %`)
> - temperatures in kelvin with negatives
> - `x²`/`x³` in variables (`v²` → `uve al cuadrado`, `v squared`)
> - `≥`/`≤` next to numbers
> - currencies `$`/`US$`
> - the abbreviations `aprox.`, `ca.`, `vs.`
>
> Keep the existing cases passing.

### 11. Distribution
> Make the tool installable without cloning: `uv tool install --python 3.11 "science-narrator[tts,asr] @ git+https://github.com/<you>/science-narrator"`. Ensure `examples/` ship as package data and `narrator init` copies them into the current folder. Add a GitHub Actions workflow that runs ruff and pytest (light extras only) on `macos-14`.

### 12. (Optional) Second engine for A/B
> Add an `Engine` implementation for F5-TTS on MLX (`f5-tts-mlx`) in an optional extra `f5`, selectable with `engine: f5` in front matter. It needs the reference transcript, so add a `voice_text:` setting. Check the model license before you enable it by default; leave the default as Chatterbox.
