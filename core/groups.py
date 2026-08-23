ICT = "ICT"
SECRETARIAT = "Secretariat"
BOARD = "Board"
CHAIRPERSON = "Chairperson"

# Four roles. A Treasurer group existed until 2026-08-24, holding no
# permissions, reserved for the finance subsystem -- removed because the
# Treasurer has not asked for anything, so that subsystem is not merely
# unbuilt but unconfirmed, and a role that grants nothing is a checkbox
# on the account form that quietly does nothing. See
# core/migrations/0005_remove_treasurer_group.py. The Treasurer POSITION
# -- the church office itself -- is unaffected and still seeded.
ALL_GROUPS = (ICT, SECRETARIAT, BOARD, CHAIRPERSON)

# A user in more than just Chairperson already has a wider lens on the data;
# the narrow five-field, own-committee view is only for Chairperson-only users.
WIDER_ACCESS_GROUPS = (ICT, SECRETARIAT, BOARD)


def is_chairperson_only(user) -> bool:
    """True for a user who is a Chairperson and nothing more privileged.

    A group-role predicate, not tied to any one model admin, so it lives here
    alongside the group-name constants rather than in a specific app's admin.
    """
    if user.is_superuser:
        return False
    names = set(user.groups.values_list("name", flat=True))
    return CHAIRPERSON in names and not names & set(WIDER_ACCESS_GROUPS)


def is_ict(user) -> bool:
    """True for ICT — the only role permitted to attach a login to a Person.

    Linking `Person.user` is what gives `is_chairperson_only` scoping any
    effect at all, so who may set it has to follow the same separation of
    duties the group permissions already encode: the Secretariat manages
    membership data but must never be able to grant someone access by
    linking a login itself. Superusers are treated as ICT for this purpose,
    same as elsewhere in the admin.
    """
    if user.is_superuser:
        return True
    return ICT in set(user.groups.values_list("name", flat=True))
