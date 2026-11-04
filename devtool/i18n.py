"""Internationalisation: Russian (source language), English and German.

Strings in the code are written in Russian and looked up in
``static/locales/<lang>.json`` (the same files the web UI uses), keyed by the
Russian original. A missing key falls back to the Russian text.

The language comes from (in order): the per-request context (set by the API
from the ``X-Lang`` header), ``DEVTOOL_LANG``, the system locale (``LANG`` /
``LC_ALL`` / ``LC_MESSAGES``), and finally English.
"""

from __future__ import annotations

import json
import os
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Any

LANGS = ("ru", "en", "de")
DEFAULT_LANG = "en"
LOCALE_DIR = Path(__file__).parent / "static" / "locales"

_request_lang: ContextVar[str | None] = ContextVar("devtool_lang", default=None)


def normalize(value: str | None) -> str | None:
    """'de_DE.UTF-8' -> 'de', 'en-US' -> 'en'; unknown -> None."""
    if not value:
        return None
    code = value.strip().lower().replace("-", "_").split(".")[0].split("_")[0]
    return code if code in LANGS else None


def env_lang() -> str:
    for var in ("DEVTOOL_LANG", "LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        val = os.environ.get(var, "")
        for part in val.split(":"):  # LANGUAGE may be a list like "de:en"
            lang = normalize(part)
            if lang:
                return lang
    return DEFAULT_LANG


def get_lang() -> str:
    return _request_lang.get() or env_lang()


def set_request_lang(value: str | None):
    """Set the language for the current request; returns a token for reset_request_lang."""
    return _request_lang.set(normalize(value))


def reset_request_lang(token) -> None:
    _request_lang.reset(token)


@lru_cache(maxsize=None)
def catalog(lang: str) -> dict[str, Any]:
    if lang == "ru":
        return {}
    path = LOCALE_DIR / f"{lang}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def tr(source: str, /, _lang: str | None = None, **kwargs: Any) -> str:
    """Translate a Russian source string; ``{name}`` placeholders are filled from kwargs."""
    lang = _lang or get_lang()
    out = catalog(lang).get(source, source) if lang != "ru" else source
    if not isinstance(out, str):
        out = source
    return out.format(**kwargs) if kwargs else out


def plural(n: int, one: str, few: str, many: str, lang: str | None = None) -> str:
    """Pick a plural form. Callers pass the three Russian forms; other languages
    look up ``@plural:<one>`` -> [singular, plural]."""
    lang = lang or get_lang()
    if lang == "ru":
        n = abs(n)
        if n % 10 == 1 and n % 100 != 11:
            return one
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return few
        return many
    forms = catalog(lang).get("@plural:" + one)
    if isinstance(forms, list) and len(forms) == 2:
        return forms[0] if abs(n) == 1 else forms[1]
    return one if abs(n) == 1 else many


# ----------------------------------------------------------------- dates

WEEKDAYS_SHORT = {
    "ru": ["пн", "вт", "ср", "чт", "пт", "сб", "вс"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "de": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"],
}
WEEKDAYS_FULL = {
    "ru": ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "de": ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"],
}
MONTHS_GEN = {
    "ru": ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
    "de": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"],
}
SINCE_WEEKDAY = {
    "ru": ["С понедельника", "Со вторника", "Со среды", "С четверга", "С пятницы", "С субботы", "С воскресенья"],
    "en": ["Since Monday", "Since Tuesday", "Since Wednesday", "Since Thursday", "Since Friday", "Since Saturday", "Since Sunday"],
    "de": ["Seit Montag", "Seit Dienstag", "Seit Mittwoch", "Seit Donnerstag", "Seit Freitag", "Seit Samstag", "Seit Sonntag"],
}


def day_label(weekday: int, day: int, month: int, year: int | None = None, lang: str | None = None) -> str:
    """'Пт, 30 октября' / 'Fri, October 30' / 'Fr., 30. Oktober' (+ year when given)."""
    lang = lang or get_lang()
    wd, mon = WEEKDAYS_SHORT[lang][weekday], MONTHS_GEN[lang][month - 1]
    if lang == "en":
        label = f"{wd}, {mon} {day}" + (f", {year}" if year else "")
    elif lang == "de":
        label = f"{wd}., {day}. {mon}" + (f" {year}" if year else "")
    else:
        label = f"{wd}, {day} {mon}" + (f" {year}" if year else "")
    return label[0].upper() + label[1:]


# unit forms: ru (one, few, many, accusative-one), en (one, other), de nominative (one, other), de dative (one, other)
_UNITS = {
    "year": {"ru": ("год", "года", "лет", "год"), "en": ("year", "years"), "de": ("Jahr", "Jahre"), "de_dat": ("Jahr", "Jahren")},
    "month": {"ru": ("месяц", "месяца", "месяцев", "месяц"), "en": ("month", "months"), "de": ("Monat", "Monate"), "de_dat": ("Monat", "Monaten")},
    "day": {"ru": ("день", "дня", "дней", "день"), "en": ("day", "days"), "de": ("Tag", "Tage"), "de_dat": ("Tag", "Tagen")},
    "hour": {"ru": ("час", "часа", "часов", "час"), "en": ("hour", "hours"), "de": ("Stunde", "Stunden"), "de_dat": ("Stunde", "Stunden")},
    "minute": {"ru": ("минута", "минуты", "минут", "минуту"), "en": ("minute", "minutes"), "de": ("Minute", "Minuten"), "de_dat": ("Minute", "Minuten")},
    "second": {"ru": ("секунда", "секунды", "секунд", "секунду"), "en": ("second", "seconds"), "de": ("Sekunde", "Sekunden"), "de_dat": ("Sekunde", "Sekunden")},
}
JUST_NOW = {"ru": "только что", "en": "just now", "de": "gerade eben"}


def relative(seconds: int, lang: str | None = None) -> str:
    """Human relative time; positive seconds are in the future."""
    lang = lang or get_lang()
    future = seconds > 0
    s = abs(int(seconds))
    if s < 10:
        return JUST_NOW[lang]
    for size, unit in ((31536000, "year"), (2592000, "month"), (86400, "day"), (3600, "hour"), (60, "minute"), (1, "second")):
        if s >= size:
            n = s // size
            forms = _UNITS[unit]
            if lang == "ru":
                one, few, many, acc = forms["ru"]
                word = plural(n, one, few, many, lang="ru")
                if word == one:
                    word = acc  # "1 минуту назад", "через 1 секунду"
                return f"через {n} {word}" if future else f"{n} {word} назад"
            if lang == "de":
                one, other = forms["de_dat"]
                return f"in {n} {one if n == 1 else other}" if future else f"vor {n} {one if n == 1 else other}"
            one, other = forms["en"]
            word = one if n == 1 else other
            return f"in {n} {word}" if future else f"{n} {word} ago"
    return JUST_NOW[lang]  # pragma: no cover
