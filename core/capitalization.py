"""Turns paper-form ALL CAPS into ordinary title case, in one place, so every
write path -- the admin where the Secretariat types, the importer, and any
future one -- treats a name or address the same way.

The paper forms are filled in block capitals; the volunteers who transcribe
and review them mostly are not, and Django admin users typing a correction
by hand are not either. Two decisions follow from that:

1. A field is only touched when it is currently *shouting* -- every cased
   character in it is uppercase (``str.isupper()``). Anyone who already typed
   "McDonald" or "dela Cruz" is left alone. This is deliberately a per-field,
   not a per-word, decision: reshaping only the words within a partly-typed
   field would silently overrule a user who is mid-correction, which is a
   worse failure than leaving an inconsistently-cased field untouched.
2. Even inside a shouting field, a token that is plainly not an ordinary
   word -- it carries a digit (``KC-109``, ``OB-4-77``), or its letters have
   no vowel at all (``B.G.H``, ``L.T.B.``, ``BGHMC``) -- is left exactly as
   written rather than title-cased into ``Kc-109`` or ``B.g.h``. No purely
   consonant string is an ordinary English or Filipino word; every real
   initialism found in the batch happens to be one.

Filipino name particles (``DELA CRUZ``, ``DEL ROSARIO``, ``DE GUZMAN``) are
deliberately *not* special-cased to a lowercase mid-name form. There is no
single convention the paper forms agree on -- the same family spells its own
surname ``Til-Adan`` on one form and ``Til-adan`` on another -- so this
module does not try to arbitrate spelling at all, only casing: every word
capitalized, no exceptions, is the one rule simple enough to apply the same
way everywhere.
"""

import re

_VOWELS = frozenset("AEIOUaeiou")
_ROMAN_NUMERAL_RE = re.compile(r"^[IVXLCDM]+$", re.IGNORECASE)


def _is_code_like(token: str) -> bool:
    """True for a token that is plainly not an ordinary word.

    Covers purok/zone codes that carry a digit (``KC-109``, ``FA-011-D``)
    and initialisms whose letters have no vowel at all (``BGH``, ``LTB``).
    An empty or punctuation-only token (stray comma, blank from a double
    space) also counts -- there is nothing to capitalize, so it is passed
    through unchanged rather than crashing on an empty ``.title()``.
    """
    if any(ch.isdigit() for ch in token):
        return True
    letters = [ch for ch in token if ch.isalpha()]
    if not letters:
        return True
    return not any(ch in _VOWELS for ch in letters)


def capitalize_words(value: str) -> str:
    """Title-case a name or address field, but only if it is currently
    shouting (see module docstring for the two rules this follows).

    Splits on the literal space so repeated or trailing whitespace survives
    unchanged -- this function only ever changes letter case, never
    spacing. Every other separator Python's own ``str.title()`` already
    treats as a word boundary (hyphen, apostrophe, comma, period) is left to
    it: ``MARY-JANE`` -> ``Mary-Jane``, ``O'BRIEN`` -> ``O'Brien``.
    """
    if not value or not value.isupper():
        return value
    tokens = value.split(" ")
    capitalized = [
        token if not token or _is_code_like(token) else token.lower().title()
        for token in tokens
    ]
    return " ".join(capitalized)


def capitalize_suffix(value: str) -> str:
    """Normalize a name suffix -- Jr., Sr., or a Roman-numeral generation
    marker (II, III, IV, V, ...).

    Not routed through capitalize_words() above: its "no vowel means it is
    a code, leave it alone" rule exists to protect initialisms like B.G.H,
    but I, V, X, L, C and D are themselves vowel-containing letters, so that
    rule would wave III straight through the ordinary title-casing and
    produce "Iii". Suffixes are a small, effectively closed vocabulary, so
    they get their own rule instead: a token made up purely of Roman-numeral
    letters is upper-cased outright; anything else (JR, JR., SR) is
    title-cased normally. Only fires when the field is currently shouting,
    same as every other field in this module -- "Jr." typed by hand is left
    alone.
    """
    if not value or not value.isupper():
        return value
    tokens = value.split(" ")
    normalized = []
    for token in tokens:
        letters_only = "".join(ch for ch in token if ch.isalpha())
        if letters_only and _ROMAN_NUMERAL_RE.match(letters_only):
            normalized.append(token.upper())
        else:
            normalized.append(token.lower().title())
    return " ".join(normalized)
