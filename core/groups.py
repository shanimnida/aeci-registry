ICT = "ICT"
SECRETARIAT = "Secretariat"
TREASURER = "Treasurer"
BOARD = "Board"
CHAIRPERSON = "Chairperson"

ALL_GROUPS = (ICT, SECRETARIAT, TREASURER, BOARD, CHAIRPERSON)

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
