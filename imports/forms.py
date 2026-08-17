from django import forms
from unfold.widgets import (
    UnfoldAdminCheckboxSelectMultipleWidget,
    UnfoldAdminFileFieldWidget,
    UnfoldAdminSelectWidget,
    UnfoldAdminTextareaWidget,
    UnfoldAdminTextInputWidget,
)

from people.models import CivilStatus, Gender, MembershipStatus

from .parsing import ALL_COMMITTEE_NAMES, FORM_VERSIONS


# IMPORTANT 5 (2026-08-16 import fixes): imports/admin.py's upload_view reads
# the whole file into memory in one call before decoding it, and nothing
# capped how large a file it would accept -- a mistaken or hostile
# multi-hundred-megabyte upload would be read whole regardless. A realistic
# batch is tens of forms, not tens of thousands; each transcribed form is on
# the order of a kilobyte or two of JSON, so 5 MB comfortably covers a batch
# in the thousands while still refusing anything that size implies is wrong.
MAX_IMPORT_FILE_SIZE = 5 * 1024 * 1024


class UploadForm(forms.Form):
    file = forms.FileField(
        label="Import file (.xlsx, .csv, or .json)",
        widget=UnfoldAdminFileFieldWidget(
            attrs={
                "accept": (
                    ".xlsx,.csv,.json,"
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
                    "text/csv,application/json"
                )
            }
        ),
    )

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if upload.size > MAX_IMPORT_FILE_SIZE:
            raise forms.ValidationError(
                f"This file is {upload.size / 1_048_576:.1f} MB, larger than AEGIS accepts for "
                f"one profiling import ({MAX_IMPORT_FILE_SIZE / 1_048_576:.0f} MB). A realistic "
                "batch is tens of forms -- split this into smaller files, or check it is the "
                "right file."
            )
        return upload


# Date-shaped fields are plain text, not forms.DateField. Calendar validity
# is deliberately checked in exactly one place: Person.full_clean() when the
# reviewer approves (see imports/services.py). A form-level DateField would
# reject an "impossible" date the AI faithfully transcribed before the
# reviewer even gets to see and judge it, and would duplicate the model's
# own validation with a second, possibly different, error message.
class StagedPersonForm(forms.Form):
    member_no = forms.CharField(required=False, widget=UnfoldAdminTextInputWidget)
    last_name = forms.CharField(widget=UnfoldAdminTextInputWidget)
    first_name = forms.CharField(widget=UnfoldAdminTextInputWidget)
    middle_name = forms.CharField(required=False, widget=UnfoldAdminTextInputWidget)
    suffix = forms.CharField(required=False, widget=UnfoldAdminTextInputWidget)

    date_of_birth = forms.CharField(
        required=False, widget=UnfoldAdminTextInputWidget, help_text="YYYY-MM-DD"
    )
    place_of_birth = forms.CharField(required=False, widget=UnfoldAdminTextInputWidget)
    gender = forms.ChoiceField(
        required=False, choices=(("", "—"), *Gender.choices), widget=UnfoldAdminSelectWidget
    )
    civil_status = forms.ChoiceField(
        required=False,
        choices=(("", "—"), *CivilStatus.choices),
        widget=UnfoldAdminSelectWidget,
    )
    nationality = forms.CharField(required=False, widget=UnfoldAdminTextInputWidget)

    home_address = forms.CharField(
        required=False, widget=UnfoldAdminTextareaWidget(attrs={"rows": 2})
    )
    mobile_number = forms.CharField(required=False, widget=UnfoldAdminTextInputWidget)
    email = forms.CharField(required=False, widget=UnfoldAdminTextInputWidget)

    # CRITICAL 1 (2026-08-16 import fixes): this used to be display-only --
    # shown in the "what the AI read" panel but never part of `cleaned`, so
    # imports/services.py had no way to look for and link an existing Person
    # by this name even after that logic was added. Editable like every
    # other field, for the same reason date_of_birth is: the AI's reading
    # can be wrong, and a wrong spouse match is exactly what the reviewer
    # must be able to correct before approving.
    spouse_name = forms.CharField(required=False, widget=UnfoldAdminTextInputWidget)
    date_of_marriage = forms.CharField(
        required=False, widget=UnfoldAdminTextInputWidget, help_text="YYYY-MM-DD"
    )

    emergency_contact_name = forms.CharField(required=False, widget=UnfoldAdminTextInputWidget)
    emergency_relationship = forms.CharField(required=False, widget=UnfoldAdminTextInputWidget)
    emergency_number = forms.CharField(required=False, widget=UnfoldAdminTextInputWidget)

    form_version = forms.ChoiceField(choices=[(v, v) for v in FORM_VERSIONS], widget=UnfoldAdminSelectWidget)
    date_filed = forms.CharField(
        required=False, widget=UnfoldAdminTextInputWidget, help_text="YYYY-MM-DD"
    )
    certification_date = forms.CharField(
        required=False, widget=UnfoldAdminTextInputWidget, help_text="YYYY-MM-DD"
    )

    committees = forms.MultipleChoiceField(
        required=False,
        choices=[(name, name) for name in ALL_COMMITTEE_NAMES],
        widget=UnfoldAdminCheckboxSelectMultipleWidget,
    )

    # Not part of the AI's JSON at all -- see import-feature-report.md. The
    # AI never decides membership; a human does, here, explicitly. MEMBER is
    # the sensible default because this whole workflow exists for the Member
    # Profiling Form, not because the software is making the call.
    membership_status = forms.ChoiceField(
        choices=MembershipStatus.choices, widget=UnfoldAdminSelectWidget
    )

    # Deliberately no `notes` field. The AI's free-text `notes` was its own
    # commentary about the form -- "the AI talking about the form rather
    # than showing it" -- and the reviewer has the actual paper in hand,
    # which is a better source than a machine's remarks about it. See
    # review.html and the field-level flags below for where that
    # information now lives instead.


class ChildForm(forms.Form):
    full_name = forms.CharField(required=False, widget=UnfoldAdminTextInputWidget)
    date_of_birth = forms.CharField(
        required=False, widget=UnfoldAdminTextInputWidget, help_text="YYYY-MM-DD"
    )


ChildFormSet = forms.formset_factory(ChildForm, extra=0)


def initial_from_data(data: dict) -> dict:
    """Map a staged row's raw/edited JSON onto StagedPersonForm's fields."""
    initial = {field: data.get(field) for field in StagedPersonForm.base_fields if field != "membership_status"}
    initial["membership_status"] = data.get("membership_status") or MembershipStatus.MEMBER
    initial["committees"] = data.get("committees") or []
    for text_field in ("member_no", "middle_name", "suffix", "place_of_birth", "nationality",
                        "home_address", "mobile_number", "email", "spouse_name",
                        "emergency_contact_name",
                        "emergency_relationship", "emergency_number", "date_of_birth",
                        "date_of_marriage", "date_filed", "certification_date"):
        if initial.get(text_field) is None:
            initial[text_field] = ""
    return initial


def children_initial(data: dict) -> list[dict]:
    children = data.get("children") or []
    return [
        {"full_name": child.get("full_name") or "", "date_of_birth": child.get("date_of_birth") or ""}
        for child in children
    ]
