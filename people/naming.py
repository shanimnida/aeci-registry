"""How a person's name is written in a list.

Requested 2026-08-24: "in every viewing of people's list make Surname
first as the standard and first name first as an option".

Surname first is the standard because a register is looked up by surname.
It is what the church's own book of members is ordered by (spec 7.6), it
is how the changelist has always been sorted, and a column of given names
is one you have to read every row of to find anybody.

**This applies to LISTS, not to prose.** A notice saying "Linked to
existing child Rhyzel Bayatin Abaigar" is a sentence, and a sentence reads
in the spoken order -- so `Person.full_name` stays exactly as it was and
this module is only reached where names are stacked in a column.

The choice lives in the session rather than in a new model field: it is a
display preference, it costs no migration, and every screen that shows a
list is an admin screen with a request in hand.
"""

SURNAME_FIRST = "surname"
GIVEN_FIRST = "given"
SESSION_KEY = "aegis_name_order"
DEFAULT = SURNAME_FIRST

LABELS = {
    SURNAME_FIRST: "Surname first",
    GIVEN_FIRST: "First name first",
}


def name_order(request) -> str:
    """The order this user is reading lists in."""
    if request is None:
        return DEFAULT
    chosen = request.session.get(SESSION_KEY)
    return chosen if chosen in LABELS else DEFAULT


def other_order(order: str) -> str:
    return GIVEN_FIRST if order == SURNAME_FIRST else SURNAME_FIRST


def display_name(person, order=DEFAULT) -> str:
    if person is None:
        return ""
    return person.sorted_name if order == SURNAME_FIRST else person.full_name


def short_display_name(person, order=DEFAULT) -> str:
    """First and last name only, plus a nickname -- the roster form.

    Mirrors committees.admin.overview_display_name's reasoning: the
    committee screens exist to answer "who is on this", not to be a second
    full directory, so they deliberately drop middle names and suffixes.
    """
    if person is None:
        return ""
    if order == SURNAME_FIRST and person.last_name:
        name = f"{person.last_name}, {person.first_name}".strip().rstrip(",")
    else:
        name = f"{person.first_name} {person.last_name}".strip()
    if person.nickname:
        name = f'{name} "{person.nickname}"'
    return name
