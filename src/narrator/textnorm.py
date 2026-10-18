"""Script text -> TTS-safe spoken text (es / en).

Ported from flat-hunter-bcn voice/tts_prep.py and generalized for science
narration: lexicon respellings, decimals, scientific notation, units, ranges,
fractions, greek letters and math symbols. Anything still risky (digits,
unknown ALLCAPS acronyms, stray symbols) is reported as a warning so the
author can add a lexicon entry instead of letting the model guess.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

import yaml

RESPELL_RE = re.compile(r"\[([^\[\]|]+)\|([^\[\]]+)\]")

_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")

LANG = {
    "es": {
        "dec": "coma",
        "minus": "menos",
        "times10": "por diez elevado a",
        "pow10": "diez elevado a",
        "to": "a",
        "over": "sobre",
        "fractions": {"1/2": "un medio", "1/3": "un tercio", "2/3": "dos tercios",
                      "1/4": "un cuarto", "3/4": "tres cuartos"},
        "symbols": {"±": "más o menos", "≈": "aproximadamente", "≥": "mayor o igual que",
                    "≤": "menor o igual que", "≠": "distinto de", "∞": "infinito",
                    " = ": " es igual a ", " + ": " más ", " → ": " da lugar a ", " × ": " por "},
        "greek": {"α": "alfa", "β": "beta", "γ": "gamma", "δ": "delta", "Δ": "delta",
                  "ε": "épsilon", "θ": "theta", "λ": "lambda", "µ": "mi", "π": "pi",
                  "ρ": "ro", "σ": "sigma", "τ": "tau", "φ": "fi", "ψ": "psi", "ω": "omega",
                  "Ω": "omega"},
    },
    "en": {
        "dec": "point",
        "minus": "minus",
        "times10": "times ten to the power of",
        "pow10": "ten to the power of",
        "to": "to",
        "over": "over",
        "fractions": {"1/2": "one half", "1/3": "one third", "2/3": "two thirds",
                      "1/4": "one quarter", "3/4": "three quarters"},
        "symbols": {"±": "plus or minus", "≈": "approximately", "≥": "greater than or equal to",
                    "≤": "less than or equal to", "≠": "not equal to", "∞": "infinity",
                    " = ": " equals ", " + ": " plus ", " → ": " yields ", " × ": " times "},
        "greek": {"α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "Δ": "delta",
                  "ε": "epsilon", "θ": "theta", "λ": "lambda", "µ": "mu", "π": "pi",
                  "ρ": "rho", "σ": "sigma", "τ": "tau", "φ": "phi", "ψ": "psi", "ω": "omega",
                  "Ω": "omega"},
    },
}

# symbol: (es singular, es plural, en singular, en plural)
UNITS: dict[str, tuple[str, str, str, str]] = {
    "%": ("por ciento", "por ciento", "percent", "percent"),
    "°C": ("grado Celsius", "grados Celsius", "degree Celsius", "degrees Celsius"),
    "°F": ("grado Fahrenheit", "grados Fahrenheit", "degree Fahrenheit", "degrees Fahrenheit"),
    "°": ("grado", "grados", "degree", "degrees"),
    "K": ("kelvin", "kelvin", "kelvin", "kelvin"),
    "Å": ("angstrom", "angstroms", "angstrom", "angstroms"),
    "pm": ("picómetro", "picómetros", "picometer", "picometers"),
    "nm": ("nanómetro", "nanómetros", "nanometer", "nanometers"),
    "µm": ("micrómetro", "micrómetros", "micrometer", "micrometers"),
    "mm": ("milímetro", "milímetros", "millimeter", "millimeters"),
    "cm": ("centímetro", "centímetros", "centimeter", "centimeters"),
    "m": ("metro", "metros", "meter", "meters"),
    "km": ("kilómetro", "kilómetros", "kilometer", "kilometers"),
    "m²": ("metro cuadrado", "metros cuadrados", "square meter", "square meters"),
    "km²": ("kilómetro cuadrado", "kilómetros cuadrados", "square kilometer", "square kilometers"),
    "m³": ("metro cúbico", "metros cúbicos", "cubic meter", "cubic meters"),
    "cm³": ("centímetro cúbico", "centímetros cúbicos", "cubic centimeter", "cubic centimeters"),
    "m/s": ("metro por segundo", "metros por segundo", "meter per second", "meters per second"),
    "m/s²": ("metro por segundo al cuadrado", "metros por segundo al cuadrado",
             "meter per second squared", "meters per second squared"),
    "km/s": ("kilómetro por segundo", "kilómetros por segundo", "kilometer per second", "kilometers per second"),
    "km/h": ("kilómetro por hora", "kilómetros por hora", "kilometer per hour", "kilometers per hour"),
    "µg": ("microgramo", "microgramos", "microgram", "micrograms"),
    "mg": ("miligramo", "miligramos", "milligram", "milligrams"),
    "g": ("gramo", "gramos", "gram", "grams"),
    "kg": ("kilogramo", "kilogramos", "kilogram", "kilograms"),
    "ns": ("nanosegundo", "nanosegundos", "nanosecond", "nanoseconds"),
    "µs": ("microsegundo", "microsegundos", "microsecond", "microseconds"),
    "ms": ("milisegundo", "milisegundos", "millisecond", "milliseconds"),
    "s": ("segundo", "segundos", "second", "seconds"),
    "min": ("minuto", "minutos", "minute", "minutes"),
    "h": ("hora", "horas", "hour", "hours"),
    "Hz": ("hercio", "hercios", "hertz", "hertz"),
    "kHz": ("kilohercio", "kilohercios", "kilohertz", "kilohertz"),
    "MHz": ("megahercio", "megahercios", "megahertz", "megahertz"),
    "GHz": ("gigahercio", "gigahercios", "gigahertz", "gigahertz"),
    "J": ("julio", "julios", "joule", "joules"),
    "kJ": ("kilojulio", "kilojulios", "kilojoule", "kilojoules"),
    "kcal": ("kilocaloría", "kilocalorías", "kilocalorie", "kilocalories"),
    "eV": ("electronvoltio", "electronvoltios", "electronvolt", "electronvolts"),
    "keV": ("kiloelectronvoltio", "kiloelectronvoltios", "kiloelectronvolt", "kiloelectronvolts"),
    "MeV": ("megaelectronvoltio", "megaelectronvoltios", "megaelectronvolt", "megaelectronvolts"),
    "GeV": ("gigaelectronvoltio", "gigaelectronvoltios", "gigaelectronvolt", "gigaelectronvolts"),
    "W": ("vatio", "vatios", "watt", "watts"),
    "kW": ("kilovatio", "kilovatios", "kilowatt", "kilowatts"),
    "V": ("voltio", "voltios", "volt", "volts"),
    "mV": ("milivoltio", "milivoltios", "millivolt", "millivolts"),
    "A": ("amperio", "amperios", "ampere", "amperes"),
    "mA": ("miliamperio", "miliamperios", "milliampere", "milliamperes"),
    "N": ("newton", "newtons", "newton", "newtons"),
    "Pa": ("pascal", "pascales", "pascal", "pascals"),
    "kPa": ("kilopascal", "kilopascales", "kilopascal", "kilopascals"),
    "atm": ("atmósfera", "atmósferas", "atmosphere", "atmospheres"),
    "mol": ("mol", "moles", "mole", "moles"),
    "mL": ("mililitro", "mililitros", "milliliter", "milliliters"),
    "ml": ("mililitro", "mililitros", "milliliter", "milliliters"),
    "L": ("litro", "litros", "liter", "liters"),
    "€": ("euro", "euros", "euro", "euros"),
    "J/mol": ("julio por mol", "julios por mol", "joule per mole", "joules per mole"),
    "kJ/mol": ("kilojulio por mol", "kilojulios por mol", "kilojoule per mole", "kilojoules per mole"),
    "kcal/mol": ("kilocaloría por mol", "kilocalorías por mol", "kilocalorie per mole", "kilocalories per mole"),
    "g/mol": ("gramo por mol", "gramos por mol", "gram per mole", "grams per mole"),
    "mol/L": ("mol por litro", "moles por litro", "mole per liter", "moles per liter"),
    "g/cm³": ("gramo por centímetro cúbico", "gramos por centímetro cúbico",
              "gram per cubic centimeter", "grams per cubic centimeter"),
    "kg/m³": ("kilogramo por metro cúbico", "kilogramos por metro cúbico",
              "kilogram per cubic meter", "kilograms per cubic meter"),
    "W/m²": ("vatio por metro cuadrado", "vatios por metro cuadrado", "watt per square meter", "watts per square meter"),
}

_UNIT_ALT = "|".join(re.escape(u) for u in sorted(UNITS, key=len, reverse=True))
# Single-letter units (m, s, K, A…) need a space so "1990s" / "4K" stay untouched.
_MULTI_ALT = "|".join(re.escape(u) for u in sorted(UNITS, key=len, reverse=True)
                      if not re.fullmatch(r"[A-Za-z]", u))
_UNIT = rf"(?:(?:\s|(?=(?:{_MULTI_ALT})(?![\w/])))(?P<unit>{_UNIT_ALT})(?![\w/]))?"
_NUM = {
    # es: 1.400 / 1.400,5 are thousands; 3,14 and 3.14 are decimals.
    "es": r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?",
    "en": r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?",
}
_PRE = r"(?<![\w.,/])"
_EXP = r"[-−⁻+]?[\d⁰¹²³⁴⁵⁶⁷⁸⁹]+"


def _num2words(n: int, lang: str, year: bool = False) -> str:
    from num2words import num2words

    out = num2words(n, lang=lang, to="year") if year else num2words(n, lang=lang)
    return out.replace(",", "").replace("-", " ")


def _parse_number(raw: str, lang: str) -> tuple[str, str | None]:
    """Return (integer part, fractional digits or None)."""
    if lang == "es":
        raw = raw.replace(".", "") if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", raw) else raw
        raw = raw.replace(",", ".")
    else:
        raw = raw.replace(",", "")
    if "." in raw:
        i, f = raw.split(".", 1)
        return i, f
    return raw, None


def say_number(raw: str, lang: str, *, allow_year: bool = False) -> tuple[str, bool]:
    """Spoken form + whether the value is exactly one (for unit plurals)."""
    neg = raw[:1] in "-−"
    i, f = _parse_number(raw.lstrip("-−"), lang)
    L = LANG[lang]
    year = allow_year and lang == "en" and f is None and len(i) == 4 and 1100 <= int(i) <= 2099
    words = _num2words(int(i), lang, year=year)
    if f:
        if lang == "es" and len(f) <= 2 and not f.startswith("0"):
            frac = _num2words(int(f), lang)
        else:
            frac = " ".join(_num2words(int(d), lang) for d in f)
        words = f"{words} {L['dec']} {frac}"
    if neg:
        words = f"{L['minus']} {words}"
    return words, (f is None and int(i) == 1 and not neg)


def _unit_words(unit: str | None, one: bool, lang: str) -> str:
    if not unit:
        return ""
    es_s, es_p, en_s, en_p = UNITS[unit]
    word = (es_s if one else es_p) if lang == "es" else (en_s if one else en_p)
    return " " + word


def _agree_es(words: str, unit: str | None) -> str:
    """Spanish number/noun agreement before a unit: uno->un/una, millones -> millones de."""
    if not unit or unit == "%":
        return words
    feminine = UNITS[unit][0].split()[0].endswith("a")
    if re.search(r"(?:^|\s)(?:veinti)?uno$", words):
        words = re.sub(r"uno$", "una" if feminine else "un", words)
        words = re.sub(r"veintiun$", "veintiún", words)
    if re.search(r"(?:millón|millones|billón|billones)$", words):
        words += " de"
    return words


def _exp_words(raw: str, lang: str) -> str:
    raw = raw.translate(_SUPERSCRIPT).replace("−", "-").lstrip("+")
    return say_number(raw, lang)[0]


# ---------------------------------------------------------------- es clocks
# Ported from voice/tts_prep.py (clock verbalization).
def _hour_noun(h24: int, lang: str) -> str:
    h = h24 % 12 or 12
    if lang == "es" and h == 1:
        return "una"
    return _num2words(h, lang)


def verbalize_clock(hh: int, mm: int, lang: str) -> str:
    if lang != "es":
        return f"{_num2words(hh, lang)} {_num2words(mm, lang) if mm else 'hundred'}"
    article = "la" if hh % 12 == 1 else "las"
    noun = _hour_noun(hh, lang)
    if mm == 0:
        return f"{article} {noun}"
    if mm == 15:
        return f"{article} {noun} y cuarto"
    if mm == 30:
        return f"{article} {noun} y media"
    if mm == 45:
        nh = (hh + 1) % 24
        return f"{'la' if nh % 12 == 1 else 'las'} {_hour_noun(nh, lang)} menos cuarto"
    return f"{article} {noun} y {_num2words(mm, lang)}"


_CLOCK_RE = re.compile(r"(?:(?P<pre>\b(?:a\s+)?las?\s+))?\b(?P<h>[01]?\d|2[0-3]):(?P<m>[0-5]\d)\b", re.IGNORECASE)


# ---------------------------------------------------------------- lexicon
@lru_cache(maxsize=32)
def _load_lexicon_file(path: str) -> tuple[tuple[str, str], ...]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise TypeError(f"lexicon {path}: expected a mapping term -> respelling")
    return tuple((str(k), str(v)) for k, v in data.items())


def load_lexicon(paths: Iterable[str | Path]) -> dict[str, str]:
    """Later files override earlier ones."""
    lex: dict[str, str] = {}
    for p in paths:
        lex.update(_load_lexicon_file(str(Path(p).resolve())))
    return lex


def apply_lexicon(text: str, lexicon: dict[str, str]) -> str:
    """Whole-token, case-sensitive replacement, longest term first."""
    if not lexicon:
        return text
    terms = sorted(lexicon, key=len, reverse=True)
    pattern = re.compile(r"(?<![\w])(?:" + "|".join(re.escape(t) for t in terms) + r")(?![\w])")
    return pattern.sub(lambda m: lexicon[m.group(0)], text)


# ---------------------------------------------------------------- main API
def split_markup(text: str) -> tuple[str, str]:
    """`[ATP|a te pe]` -> display 'ATP', spoken 'a te pe'."""
    return RESPELL_RE.sub(lambda m: m.group(1), text), RESPELL_RE.sub(lambda m: m.group(2), text)


def verbalize(text: str, lang: str) -> str:
    if lang not in LANG:
        raise ValueError(f"unsupported normalization language {lang!r} (have: {', '.join(LANG)})")
    L = LANG[lang]
    num = _NUM[lang]
    text = unicodedata.normalize("NFC", text).replace("−", "-").replace("\u00a0", " ").replace("μ", "µ")

    def clock(m: re.Match) -> str:
        spoken = verbalize_clock(int(m.group("h")), int(m.group("m")), lang)
        pre = m.group("pre")
        if pre and lang == "es":
            lead = "a " if re.match(r"(?i)^a\s", pre) else ""
            return lead + spoken
        return (pre or "") + spoken

    text = _CLOCK_RE.sub(clock, text)

    # 6.022×10^23 mol / 3e8 m/s / 10⁻⁹ m
    sci = re.compile(rf"{_PRE}(?P<m>-?(?:{num}))\s?(?:[×x·*]|\\times)\s?10\s?\^?\s?(?P<e>{_EXP}){_UNIT}")
    text = sci.sub(lambda m: f"{say_number(m.group('m'), lang)[0]} {L['times10']} "
                             f"{_exp_words(m.group('e'), lang)}{_unit_words(m.group('unit'), False, lang)}", text)
    enot = re.compile(rf"{_PRE}(?P<m>\d+(?:\.\d+)?)[eE](?P<e>[-+]?\d+){_UNIT}(?![\w])")
    text = enot.sub(lambda m: f"{say_number(m.group('m'), lang)[0]} "
                              f"{L['times10']} {_exp_words(m.group('e'), lang)}"
                              f"{_unit_words(m.group('unit'), False, lang)}", text)
    pow10 = re.compile(rf"{_PRE}10(?:\^(?P<e1>-?\d+)|(?P<e2>[⁻⁰¹²³⁴⁵⁶⁷⁸⁹]+)){_UNIT}")
    text = pow10.sub(lambda m: f"{L['pow10']} {_exp_words(m.group('e1') or m.group('e2'), lang)}"
                               f"{_unit_words(m.group('unit'), False, lang)}", text)

    # Ranges: 3–5 nm ("entre 3–5" -> "entre tres y cinco")
    rng = re.compile(rf"(?P<pre>\bentre\s+)?{_PRE}(?P<a>{num})\s?[–—-]\s?(?P<b>{num}){_UNIT}", re.IGNORECASE)
    text = rng.sub(lambda m: f"{m.group('pre') or ''}{say_number(m.group('a'), lang)[0]} "
                             f"{'y' if m.group('pre') else L['to']} {say_number(m.group('b'), lang)[0]}"
                             f"{_unit_words(m.group('unit'), False, lang)}", text)

    # Fractions: 1/2, 7/8
    def frac(m: re.Match) -> str:
        key = f"{m.group('a')}/{m.group('b')}"
        if key in L["fractions"]:
            return L["fractions"][key]
        return f"{say_number(m.group('a'), lang)[0]} {L['over']} {say_number(m.group('b'), lang)[0]}"

    text = re.sub(r"(?<![\w./])(?P<a>\d+)/(?P<b>\d+)(?![\w/])", frac, text)

    # Number + unit: 12 nm, 37 °C, 1 mol, 45 %
    nu = re.compile(rf"{_PRE}(?P<n>-?(?:{num})){_UNIT}(?![\w])")

    def number_unit(m: re.Match) -> str:
        unit = m.group("unit")
        words, one = say_number(m.group("n"), lang, allow_year=not unit)
        if lang == "es" and "coma" not in words:
            words = _agree_es(words, unit)
        return words + _unit_words(unit, one, lang)

    text = nu.sub(number_unit, text)

    for sym, word in {**L["symbols"], **L["greek"]}.items():
        text = text.replace(sym, word if sym.startswith(" ") else f" {word} ")
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def normalize(text: str, lang: str, lexicon: dict[str, str] | None = None) -> tuple[str, str]:
    """Return (display_text, spoken_text)."""
    display, spoken = split_markup(text)
    spoken = apply_lexicon(spoken, lexicon or {})
    return display.strip(), verbalize(spoken, lang)


def risky_tokens(spoken: str) -> list[str]:
    """Tokens likely to be mispronounced: leftover digits, ALLCAPS, odd symbols."""
    warn: list[str] = []
    for tok in re.findall(r"\S+", spoken):
        core = tok.strip(".,;:!?¿¡()\"'«»“”")
        if not core:
            continue
        if re.search(r"\d", core):
            warn.append(f"digits left in {core!r}")
        elif re.fullmatch(r"[A-ZÁÉÍÓÚÑ]{2,}s?", core):
            warn.append(f"acronym {core!r} not in lexicon")
        elif re.search(r"[^\w\s'’\-]", core):
            warn.append(f"symbol in {core!r}")
    return warn


def canon_words(text: str) -> list[str]:
    """Lowercase, strip accents/punctuation — for ASR comparison."""
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9ñ]+", t)
