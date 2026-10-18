from narrator.script import parse_markdown, parse_srt, parse_timecode, split_sentences

MD = """---
language: es
fps: 25
---
# Title is ignored
[00:00:02.5] intro exaggeration=0.45
Hola. La [ATP|a te pe], e.g. de la célula. {pause 0.8} Fin del párrafo.

Segundo párrafo, Dr. Pérez lo dijo.
[+1.0] suelto
Texto suelto.
[00:01:00:12 -> 00:01:10] frames
Otro.
<!-- comentario -->
"""


def test_timecodes():
    assert parse_timecode("00:01:02.500") == 62.5
    assert parse_timecode("01:02,25") == 62.25
    assert parse_timecode("3.5") == 3.5
    assert parse_timecode("00:00:01:12", fps=24) == 1.5


def test_parse_markdown():
    meta, segs = parse_markdown(MD)
    assert meta["language"] == "es"
    assert [s.label for s in segs] == ["intro", "suelto", "frames"]
    assert segs[0].start == 2.5 and segs[0].options == {"exaggeration": "0.45"}
    assert segs[1].start is None and segs[1].gap == 1.0
    assert segs[2].start == 60.48 and segs[2].end == 70.0
    assert "comentario" not in segs[2].text


def test_split_sentences():
    _, segs = parse_markdown(MD)
    out = split_sentences(segs[0].text)
    assert out == [
        ("Hola.", None, False),
        ("La [ATP|a te pe], e.g. de la célula.", 0.8, False),
        ("Fin del párrafo.", None, True),
        ("Segundo párrafo, Dr. Pérez lo dijo.", None, True),
    ]


def test_parse_srt():
    srt = "1\n00:00:01,000 --> 00:00:04,000\nPrimera línea\ncontinúa\n\n2\n00:00:05,000 --> 00:00:07,500\nSegunda\n"
    segs = parse_srt(srt)
    assert [(s.start, s.end, s.text) for s in segs] == [(1.0, 4.0, "Primera línea continúa"), (5.0, 7.5, "Segunda")]


def test_cli_none_overrides_keep_front_matter(tmp_path):
    from narrator.settings import Settings

    s = Settings.build({"voice": "v.wav", "takes": 5}, {"voice": None, "takes": None, "seed": 7}, tmp_path)
    assert s.voice.endswith("v.wav") and s.takes == 5 and s.seed == 7
