# science-narrator

Narrate a science video in **your own voice**, locally, on an Apple Silicon Mac.

You give it a short voice sample and a script with timecodes. It creates one narration track that lines up with your existing video, plus subtitles and a report:

- **Voice clone:** [Chatterbox Multilingual](https://github.com/resemble-ai/chatterbox) (MIT) runs on the Mac's GPU through MPS. It supports 23 languages.
- **Pronunciation:** the text is cleaned up before speech. Numbers, decimals, scientific notation (`6,022×10^23`), units (`µm`, `°C`, `kJ/mol`), ranges, Greek letters and symbols become words. You fix terms with a lexicon file. Acronyms it doesn't know get flagged.
- **Checked takes:** Whisper (`mlx-whisper`) transcribes every sentence. If a take doesn't match the script, the tool makes a new one, up to N takes, and keeps the best. Anything still wrong goes into `report.md`.
- **Sync with the video:** each segment starts at its cue. If a segment runs a little long, it's sped up slightly (up to 8 % by default, with rubberband so the pitch stays the same). If it's much too long, the report says so. It never overlaps the next segment without telling you.
- **Outputs:** `narration.wav` (48 kHz/24-bit, -16 LUFS), one WAV per segment, `narration.srt` and `report.md`. Optionally it can also write the final video with the narration mixed in.

Everything runs offline after the first model download (about 5 GB).

---

## Install (macOS, Apple Silicon)

Requirements: macOS 14+, M1–M4, 16 GB RAM is enough, about 8 GB free disk and [Homebrew](https://brew.sh).

```bash
git clone <this repo> science-narrator && cd science-narrator
bash install.sh
```

`install.sh` does the following:
- installs `ffmpeg`, `rubberband` and `uv` with brew
- creates `.venv` with Python 3.11 and installs the package with `[tts,asr]`
- links `narrator` into `~/.local/bin`
- downloads the models in advance
- runs `narrator doctor`

To skip the model download, run `NARRATOR_PREFETCH=0 bash install.sh`.

---

## 1. Voice sample (this decides the quality)

Clone quality depends far more on the reference sample than on any setting.

| Do | Avoid |
|---|---|
| 15–25 s of continuous speech | under 8 s or over 30 s |
| **Same language and register as the video**: read a science paragraph the way you'll narrate it | casual phone voice when you want a narrator voice |
| Quiet, soft-furnished room, 15–20 cm from the mic | echoey rooms, fans, music, other voices |
| Steady volume, no clipping (peaks around -6 dBFS) | whispering, shouting, mouth noise |
| WAV (mp3/m4a are converted automatically) | heavy noise reduction or compression on the sample |

To record on the Mac (built-in or USB mic):

```bash
ffmpeg -f avfoundation -list_devices true -i ""          # find your mic index
ffmpeg -f avfoundation -i ":0" -t 25 -ac 1 -ar 48000 voices/voice.wav
```

Leave a short silence at the start and end. `voices/` is in `.gitignore`, so your sample is never committed.

> Only clone voices you have explicit permission to use. Chatterbox adds an inaudible watermark (Perth) to everything it generates.

---

## 2. Write the script

Copy [`examples/demo.es.md`](examples/demo.es.md). Each cue is a timecode from your video:

```markdown
---
language: es
voice: ../voices/voice.wav
lexicon: [lexicon.es.yaml]
---
[00:00:01.000] intro
¿De dónde sale la energía de tus células? {pause 0.4} De la mitocondria.

[00:00:08.500 -> 00:00:20.000] tamaño
Mide entre 0,5–1 µm…

[00:00:21.000] atp exaggeration=0.45
La [ATP sintasa|a te pe sintasa] fabrica ATP.

[+0.8] cierre seed=99
…
```

| Syntax | Meaning |
|---|---|
| `[HH:MM:SS.mmm]` (also `MM:SS`, `HH:MM:SS:FF`) | the segment starts exactly here |
| `[start -> end]` | the segment must fit inside this slot |
| `[+]` / `[+0.8]` | the segment follows the previous one, with an optional gap in seconds |
| `key=value` on the cue line | settings for this segment: `exaggeration= cfg= temperature= seed= takes= language=` |
| `[term\|respelling]` | fixes how one occurrence is pronounced; the subtitle keeps `term` |
| `{pause 0.6}` | explicit pause |
| blank line | paragraph pause (0.65 s) |
| `<!-- … -->` | comment |

**An `.srt` file works as a script too.** This is usually the easiest way to sync with a video you already have:

1. In your editor, add a subtitle track and type each narration line at the moment it should start (and end).
2. Export it as SRT.
3. Run `narrator render cues.srt`. Settings go in a sidecar file `cues.yaml` with the same keys as the front matter.

---

## 3. Check pronunciation (no audio, instant)

```bash
narrator check examples/demo.es.md
```

This prints exactly what the model will be asked to say, for example `seis coma cero dos dos por diez elevado a veintitrés`. It flags unknown acronyms (`CRISPR`), leftover digits (`4K`) and symbols (`kJ/s`).

Fix flagged items in a lexicon file:

```yaml
# examples/lexicon.es.yaml   term: how it should sound (whole word, case-sensitive)
ATP: a te pe
CRISPR: críspar
Jean: Yán
```

Write the respelling the way that language spells sounds. Use an accent mark to place stress, for example `críspar`.

---

## 4. Render

```bash
narrator render examples/demo.es.md --video my_video.mp4          # narration only, padded to video length
narrator render examples/demo.es.md --video my_video.mp4 --mux    # + my_video_narrated.mp4 (original audio at -14 dB)
narrator render examples/demo.es.md --fake                        # timing dry-run with tones, no model
```

Output goes to `examples/demo.es_out/`:

```
narration.wav       full track, starts at 00:00:00, same length as the video → drop it at the start of your timeline
segments/NNN_*.wav  one file per cue, if you'd rather place or edit them yourself
narration.srt       subtitles timed to the generated speech
report.md / .json   flagged sentences (what Whisper heard vs. what you wrote), overflows, stretch ratios
```

How the iteration loop works:
- Rendered sentences are cached in `.narrator-cache/`, so a re-render only regenerates the sentences you changed.
- If you don't like how one segment sounds, change its `seed=` (or `exaggeration=`) and render again.
- If the report shows a segment overflowing its slot, shorten the text or move the next cue.

Exit codes: `0` = everything fits, `2` = at least one segment overflows or overlaps the next one. Pass `--allow-overflow` to ignore that.

### Settings worth knowing

| Setting | Default | Effect |
|---|---|---|
| `exaggeration` | 0.35 | Higher is more expressive; it also drifts further from your voice. Try 0.3–0.5 for narration. |
| `cfg_weight` | 0.55 | Higher sticks closer to the reference voice and gives slightly slower, more careful delivery. |
| `temperature` | 0.5 | Lower is more stable; higher varies more between takes. |
| `takes` / `max_wer` | 3 / 0.0 | Takes per sentence, and the error rate a take must reach to be accepted straight away. |
| `max_stretch` | 1.08 | Maximum speed-up allowed to fit a slot. |
| `target_lufs` | -16 | Loudness target. Use -16 for web; use -23 or -24 if you're mixing under music in an editor. |

---

## Syncing with the video: open-source tools only (macOS)

The whole chain is free and open source:
- Chatterbox (MIT) for the voice
- Whisper / mlx-whisper (MIT) for the transcription check
- ffmpeg (LGPL/GPL) and Rubber Band (GPL) for audio processing
- the editors below

| Tool | License | Use it for |
|---|---|---|
| **Kdenlive** | GPL | **Recommended.** Native Apple Silicon build. Add a subtitle track, type each narration line at the right moment, and export it as SRT. That SRT is your script, so run `narrator render cues.srt`. Then drop `narration.wav` at 00:00, or the per-segment WAVs. Use keyframed volume to duck the original audio. |
| **[FilmCraft](https://github.com/storytold/filmcraft)** | MIT / Apache-2.0 | **Experimental (alpha).** A Premiere-style editor written in Rust. Every action can be scripted through its command line, JSON control server or MCP, so narration placement can be automated (see Codex task 3b). Work on copies of your files, and use Kdenlive for final delivery until it matures. |
| **Shotcut** | GPL | A simpler alternative. The Subtitles panel creates and exports SRT; place `narration.wav` at 00:00. |
| **Aegisub** | BSD | Frame-accurate subtitle timing against the video, if the editor's subtitle tools feel too coarse. Exports SRT. |
| **Audacity** | GPL | Listen through or touch up individual segments. |
| **ffmpeg** | LGPL/GPL | Used under the hood. `narrator render … --mux` writes the final video with no editor at all. |

Any editor that can import a WAV, and ideally SRT, works the same way: put `narration.wav` at 00:00 and it's in sync.

---

## Troubleshooting

- `narrator doctor` checks ffmpeg, rubberband, torch with MPS, the ASR backend and the model cache.
- **MPS error at load:** the tool retries on CPU automatically. Force it with `--device cpu`, which is slower but works. Updating torch inside the 2.6 line may help.
- **Accent or voice drift:** re-record the sample in the target language, lower `exaggeration` and raise `cfg_weight`.
- **A word is always wrong:** add it to the lexicon and respell it phonetically. The ASR check then confirms the fix.
- **First render is slow:** the models are loading. After that, expect roughly real-time or faster on an M4 when ASR checking is on.

## Development

The code is ported from the voice-agent TTS in `flat-hunter-bcn/voice` (Chatterbox wrapper and Spanish verbalization), now generalized.

The roadmap and Codex tasks are in [`docs/CODEX_TASKS.md`](docs/CODEX_TASKS.md), the format contract is in [`docs/SPEC.md`](docs/SPEC.md), and agent rules are in [`AGENTS.md`](AGENTS.md).

```bash
uv pip install -e ".[dev]" && .venv/bin/python -m pytest -q
```
