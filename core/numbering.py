"""Control numbers.

Member numbers changed shape on 2026-08-24. They used to be sequential --
`MEM-0001`, `MEM-0002` -- which meant the number told anyone holding it two
things the church had not chosen to publish: roughly how many members there
are, and who joined before whom. That was acceptable while the number lived
on an internal form. It stops being acceptable once the number is printed on
an ID card a member carries (spec 7.5), which is the direction the church is
taking it.

They are now random: `MEM-` followed by six random digits and a seventh
check digit. Still permanent, still unique, still carrying no year (D10) --
register order now comes from `date_became_member`, which is the date the
church actually cares about, rather than being smuggled into the identifier.

**The check digit is load-bearing, not decoration.** A number read off a card
or dictated over the phone gets one digit wrong sooner or later, and without
a check digit that silently becomes a different member. It also gives
`member_no_is_valid` a single, honest definition of "a real member number",
which is what `renumber_members` uses to tell a number it should replace from
one it must leave alone.

Document numbers (`EARF-2026-001` and the rest, Phase B) are unchanged: they
are filed and reported per year, so they stay sequential and keep using
`ControlNumberSequence`.
"""

import re
import secrets

from django.db import transaction

from core.models import ControlNumberSequence

MEMBER_NO_PREFIX = "MEM"

# Six random digits plus one check digit. Six gives a million possibilities
# against a congregation of a few hundred, so a collision is rare enough to
# handle by retrying and common enough that pretending it cannot happen
# would be wrong.
MEMBER_NO_BODY_DIGITS = 6
MEMBER_NO_TOTAL_DIGITS = MEMBER_NO_BODY_DIGITS + 1

MEMBER_NO_RE = re.compile(rf"^{MEMBER_NO_PREFIX}-(\d{{{MEMBER_NO_TOTAL_DIGITS}}})$")

# Damm's totally anti-symmetric quasigroup of order 10. Chosen over Luhn
# because it catches ALL adjacent transpositions -- Luhn misses 09 <-> 90 --
# and a transposition is the error a human makes copying a number off a card.
# One table lookup per digit, no position weighting, and the check digit is
# an ordinary digit appended to the end.
_DAMM_TABLE = (
    (0, 3, 1, 7, 5, 9, 8, 6, 4, 2),
    (7, 0, 9, 2, 1, 5, 4, 8, 6, 3),
    (4, 2, 0, 6, 8, 7, 1, 3, 5, 9),
    (1, 7, 5, 0, 9, 8, 3, 4, 2, 6),
    (6, 1, 2, 3, 0, 4, 5, 9, 7, 8),
    (3, 6, 7, 4, 2, 0, 9, 5, 8, 1),
    (5, 8, 6, 9, 7, 2, 0, 1, 3, 4),
    (8, 9, 4, 5, 3, 6, 2, 0, 1, 7),
    (9, 4, 3, 8, 6, 1, 7, 2, 0, 5),
    (2, 5, 8, 1, 4, 3, 6, 7, 9, 0),
)


def damm_check_digit(digits: str) -> str:
    """The digit that makes `digits` a self-checking number."""
    interim = 0
    for character in digits:
        interim = _DAMM_TABLE[interim][int(character)]
    return str(interim)


def damm_is_valid(digits: str) -> bool:
    """True when the final digit checks out against the ones before it."""
    interim = 0
    for character in digits:
        interim = _DAMM_TABLE[interim][int(character)]
    return interim == 0


def member_no_is_valid(value) -> bool:
    """True for a well-formed member number: the prefix, seven digits, and a
    check digit that agrees with the other six.

    This is the definition `renumber_members` works from, so a number typed
    by hand survives a re-run only if its check digit is right. That is
    deliberate: it is the difference between "somebody chose this number" and
    "somebody mistyped one".
    """
    match = MEMBER_NO_RE.match((value or "").strip())
    if not match:
        return False
    return damm_is_valid(match.group(1))


def _candidate_member_no() -> str:
    body = "".join(str(secrets.randbelow(10)) for _ in range(MEMBER_NO_BODY_DIGITS))
    return f"{MEMBER_NO_PREFIX}-{body}{damm_check_digit(body)}"


def new_member_no(max_attempts: int = 100) -> str:
    """A fresh, unique, random member number.

    Uniqueness is checked against what is already on file rather than
    reserved in a sequence, because there is no longer a sequence to reserve
    from. `Person.member_no` carries a unique constraint, so a genuine race
    between two encoders loses at the database rather than silently issuing a
    duplicate -- this loop is what keeps that from being the common case.

    Imported locally for the same reason the old allocator did: `core` is a
    foundational app and must not depend on `people` at import time.
    """
    from people.models import Person

    for _ in range(max_attempts):
        candidate = _candidate_member_no()
        if not Person.objects.filter(member_no=candidate).exists():
            return candidate
    raise RuntimeError(
        f"Could not find an unused member number in {max_attempts} attempts. "
        "That should be impossible with six digits and a congregation this "
        "size — check whether Person.member_no has been filled with test data."
    )


def _allocate(prefix: str, year: int | None) -> int:
    """Reserve and return the next integer for this sequence.

    Runs inside a transaction with a row lock so two people encoding at the
    same time cannot be handed the same number. Used only by document
    numbers now; member numbers stopped being sequential on 2026-08-24.
    """
    with transaction.atomic():
        ControlNumberSequence.objects.get_or_create(prefix=prefix, year=year)
        sequence = ControlNumberSequence.objects.select_for_update().get(
            prefix=prefix, year=year
        )
        sequence.last_value += 1
        sequence.save(update_fields=["last_value"])
        return sequence.last_value


def next_document_no(prefix: str, year: int) -> str:
    """Document numbers are filed per year and reset annually (spec D10)."""
    return f"{prefix}-{year}-{_allocate(prefix, year):03d}"
