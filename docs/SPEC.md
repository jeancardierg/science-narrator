# SPEC — script format and outputs (contract)

## Inputs

### Script `.md` / `.txt`
Optional YAML front matter. Any key of `Settings` can go there (`src/narrator/settings.py`):
`language, voice, lexicon, device, exaggeration, cfg_weight, temperature, seed, takes, max_wer, asr, asr_model, max_chunk_chars, sentence_pause, paragraph_pause, segment_gap, lead_in, fps, min_gap, max_stretch, target_lufs, peak_dbfs, out_sample_rate`.
Relative paths (`voice`, `lexicon`) are resolved from the script's directory.

The body is a sequence of segments. A cue line opens each segment:

| Cue | start | slot end |
|---|---|---|
| `[T]` | T | next timed cue − `min_gap` |
| `[T -> E]` / `[T --> E]` / `[T – E]` | T | E |
| `[+]` | previous end + `segment_gap` | next timed cue − `min_gap` |
| `[+G]` | previous end + G | next timed cue − `min_gap` |
| text before the first cue | `lead_in` | next timed cue − `min_gap` |

Timecodes `T`/`E` can be `HH:MM:SS.mmm`, `HH:MM:SS,mmm`, `MM:SS(.s)`, `SS(.s)` or `HH:MM:SS:FF` (frames, using `fps`).

After the closing `]` on the cue line:
- `key=value` tokens set per-segment options: `exaggeration|exag`, `cfg_weight|cfg`, `temperature|temp`, `seed`, `takes`, `language`.
- The remaining words are the **label**, used for file names and the report.

Inside the text:
- `[display|spoken]`: subtitles show `display`, the TTS says `spoken`, and the ASR check treats `display` as equal to `spoken`.
- `{pause S}` or `{pause=S}`: explicit pause of S seconds.
- Blank line: paragraph end (`paragraph_pause`).
- `<!-- … -->`: removed.
- A `#` heading line before the first segment text is ignored (treated as the title).

### Script `.srt`
Each subtitle becomes one segment, with start and end taken from its timing. Settings come from an optional sidecar `<name>.yaml`.

### Lexicon `.yaml`
A flat mapping of `term: respelling`. Matches are whole-token and case-sensitive, and the longest term wins. Later files override earlier ones. Lexicons run **before** number and unit verbalization, so `H2O: hache dos o` works.

## Processing
1. Split the text into sentences (it knows common abbreviations). Sentences shorter than 40 spoken characters are merged with the next one. Sentences longer than `max_chunk_chars` are split at `, ; : —` and then at word boundaries.
2. Normalize: inline respellings → lexicon → clocks → scientific notation → ranges → fractions → number + unit → symbols and Greek letters. Leftover digits, ALLCAPS and symbols become warnings.
3. For each chunk, make up to `takes` takes with seed `seed + 7919·k`. Each take is trimmed, then scored as `WER(ASR(take), spoken) + 0.5` if its characters per second fall outside [6, 25]. The first take with WER ≤ `max_wer` and no penalty is accepted; otherwise the lowest score wins. Without an ASR backend, there is 1 take.
4. Build each segment as chunks joined by pauses (comma 0.12 s, sentence 0.30 s, paragraph 0.65 s, or an explicit `{pause}`). Loudness is normalized to `target_lufs`.
5. Place segments on the timeline:
   - If the segment is longer than its slot and `ratio ≤ max_stretch`, time-stretch it and set status `stretched`.
   - If the ratio is larger, set status `overflow` and record an error.
   - If the start falls before the previous segment's end, set status `overlap` and record an error.
6. Mix the track. Its length is max(last end, video duration if `--video` is given). Apply the peak guard (`peak_dbfs`).

## Outputs (`<out>/`)
| File | Format |
|---|---|
| `narration.wav` | PCM 24-bit, `out_sample_rate` (48 kHz), mono, starts at t=0 |
| `segments/NNN_label.wav` | same format, one per segment |
| `narration.srt` | one cue per chunk, display text wrapped at 42 chars |
| `report.json` | `{version, script, engine, asr, duration, ok, errors[], flagged[], settings, segments[]}` |
| `report.md` | human summary of the same data |

Exit codes for `render`: `0` ok, `2` errors (overflow or overlap) unless `--allow-overflow` is passed.

## Cache
`<script dir>/.narrator-cache/<sha1>.wav|.json`. The key covers: version, engine fingerprint (engine name + reference sha1), spoken text, per-segment params, ASR backend and model, and `max_wer`.
