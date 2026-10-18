from pathlib import Path

import soundfile as sf

from narrator.engine import FakeEngine
from narrator.render import Renderer
from narrator.script import load_script
from narrator.settings import Settings
from narrator.verify import Verifier, word_error_rate


def _render(tmp_path: Path, body: str, **over):
    script_path = tmp_path / "s.md"
    script_path.write_text(body, encoding="utf-8")
    script = load_script(script_path)
    s = Settings.build(script.meta, over, script.base_dir)
    engine = FakeEngine()
    report = Renderer(script, s, engine, Verifier("none")).render(tmp_path / "out", log=lambda *_: None)
    return report, engine


def test_timed_render_places_segments(tmp_path):
    report, _ = _render(tmp_path, "[00:00:01] a\nHola mundo, esto es una prueba de narración.\n"
                                  "[00:00:10] b\nSegundo segmento con algo más de texto.\n")
    assert report["ok"]
    starts = [s["start"] for s in report["segments"]]
    assert starts == [1.0, 10.0]
    info = sf.info(tmp_path / "out" / "narration.wav")
    assert info.samplerate == 48000 and info.duration > 10
    srt = (tmp_path / "out" / "narration.srt").read_text(encoding="utf-8")
    assert "00:00:01,000 -->" in srt and "00:00:10,000 -->" in srt


def test_overflow_is_reported(tmp_path):
    long = "Esta frase es deliberadamente larga para que no quepa en el hueco disponible. " * 3
    report, _ = _render(tmp_path, f"[00:00:00 -> 00:00:02] a\n{long}\n")
    assert not report["ok"]
    assert report["segments"][0]["status"] == "overflow"


def test_small_overflow_is_stretched(tmp_path):
    text = "Una frase corta que casi cabe."  # ~30 chars / 15 cps ≈ 2.0 s + pads
    report, _ = _render(tmp_path, f"[00:00:00 -> 00:00:02.1] a\n{text}\n", max_stretch=1.2)
    seg = report["segments"][0]
    assert seg["status"] in ("ok", "stretched") and seg["duration"] <= 2.11


def test_cache_skips_resynthesis(tmp_path):
    body = "[00:00:00] a\nUna frase que se cachea entre renders sucesivos.\n"
    _, e1 = _render(tmp_path, body)
    _, e2 = _render(tmp_path, body)
    assert e1.calls and not e2.calls


def test_untimed_segments_follow_each_other(tmp_path):
    report, _ = _render(tmp_path, "Primera parte del texto sin tiempo, bastante larga.\n"
                                  "[+2] b\nSegunda parte también sin tiempo y algo larga.\n")
    a, b = report["segments"]
    assert abs(b["start"] - (a["start"] + a["duration"] + 2.0)) < 1e-6


def test_wer():
    assert word_error_rate(["a", "b", "c"], ["a", "b", "c"]) == 0
    assert word_error_rate(["a", "b", "c"], ["a", "x", "c", "d"]) == 2 / 3
