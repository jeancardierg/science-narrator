import pytest

from narrator.textnorm import apply_lexicon, canon_words, normalize, risky_tokens


@pytest.mark.parametrize("src,expected", [
    ("mide 0,5–1 µm", "mide cero coma cinco a uno micrómetros"),
    ("entre 3–5 nm", "entre tres y cinco nanómetros"),
    ("a 37 °C", "a treinta y siete grados Celsius"),
    ("1 mol", "un mol"),
    ("21 m", "veintiún metros"),
    ("1 h", "una hora"),
    ("el 45%", "el cuarenta y cinco por ciento"),
    ("6,022×10^23", "seis coma cero dos dos por diez elevado a veintitrés"),
    ("10⁻⁹ m", "diez elevado a menos nueve metros"),
    ("3e8 m/s", "tres por diez elevado a ocho metros por segundo"),
    ("1.080.000.000 km/h", "mil ochenta millones de kilómetros por hora"),
    ("3.14", "tres coma catorce"),
    ("a las 11:30", "a las once y media"),
    ("ΔG ≈ -30 kJ/mol", "delta G aproximadamente menos treinta kilojulios por mol"),
    ("1/2", "un medio"),
])
def test_es(src, expected):
    assert normalize(src, "es")[1] == expected


@pytest.mark.parametrize("src,expected", [
    ("10 µm wide", "ten micrometers wide"),
    ("37.5 °C", "thirty seven point five degrees Celsius"),
    ("in 1998", "in nineteen ninety eight"),
    ("3×10^8 m/s", "three times ten to the power of eight meters per second"),
    ("±5%", "plus or minus five percent"),
    ("3,200 bases", "three thousand two hundred bases"),
])
def test_en(src, expected):
    assert normalize(src, "en")[1] == expected


def test_single_letter_units_need_space():
    assert "segundos" not in normalize("los 1990s", "es")[1]
    assert "4K" in normalize("4K", "en")[1]


def test_inline_respelling_and_lexicon():
    display, spoken = normalize("La [ATP sintasa|a te pe sintasa] y el ADN", "es", {"ADN": "a de ene"})
    assert display == "La ATP sintasa y el ADN"
    assert spoken == "La a te pe sintasa y el a de ene"


def test_lexicon_whole_word_longest_first():
    lex = {"ARN": "a erre ene", "ARNm": "a erre ene mensajero"}
    assert apply_lexicon("ARNm y ARN, no ARNasa", lex) == "a erre ene mensajero y a erre ene, no ARNasa"


def test_risky_tokens():
    w = risky_tokens("el CRISPR corta 4K kJ/mol")
    assert any("CRISPR" in x for x in w) and any("4K" in x for x in w) and any("kJ/mol" in x for x in w)
    assert risky_tokens("todo en orden, sin problemas.") == []


def test_canon_words():
    assert canon_words("¡Mitocondría, ATP!") == ["mitocondria", "atp"]
