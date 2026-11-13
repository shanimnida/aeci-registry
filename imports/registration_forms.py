"""Member-facing forms; membership decisions stay in the staff review queue."""
from django import forms
from django.core import signing
from django.utils import timezone

from committees.models import Committee
from people.models import CivilStatus, Gender


CONSENT_VERSION = "v3-web-2026-11"
NOTICE = (
    ("Who is asking", "Avdei Elohim Church Inc. (AECI), a registered non-stock, non-profit religious corporation. For questions about your information, speak to the Secretariat in person."),
    ("What we collect", "Your name and nickname, date and place of birth, sex, civil status, nationality, home address, mobile number, email address, the name of your spouse and your date of marriage, the names and birth dates of your children, your emergency contact, and the committees you wish to serve in."),
    ("Why we collect it", "To keep the church's official register of members; to reach you about services, activities and pastoral care; to organise the committees; to greet members on birthdays and wedding anniversaries; and to contact the person you name if there is an emergency at a church activity."),
    ("Some of this is sensitive", "Under the Data Privacy Act of 2012 (RA 10173), your civil status, your age and your religious affiliation are sensitive personal information, and your children's details are a minor's personal data. That is why we ask for your consent instead of assuming it."),
    ("Who can see it", "Only the Secretariat, the ICT Committee and the Board of Directors can see a complete record. A committee chairperson sees only the name, mobile number and email address of the members of their own committee. Authorised birthday and anniversary reports show names and month/day dates without birth years. We do not sell, rent or trade your information, and we do not give it to anyone outside the church except where the law requires it."),
    ("How long we keep it", "Your name, membership dates and status are part of the church register and are kept permanently. Your contact details — mobile number, email, home address and emergency contact — are erased two years after your record is marked transferred or deceased."),
    ("Your rights", "You may ask to see your record, have it corrected, object to how it is used, or ask that it be erased. You may withdraw this consent at any time; withdrawing it does not undo what was already done lawfully before you withdrew. To do any of these, speak to the Secretariat. You may also complain to the National Privacy Commission (privacy.gov.ph)."),
)
GREETING_NOTICE = (
    "The church Facebook page is public: anyone on the internet can see it. "
    "With your permission, the church may post only your name and the occasion for "
    "your birthday or wedding anniversary, never your birth year, age, address, "
    "phone number or member number. Saying no does not affect your membership "
    "or greetings in person. You may change your choice by telling the Secretariat."
)
TOKEN_SALT = "aegis.member-registration"
TOKEN_MAX_AGE = 8 * 60 * 60


class PastDateField(forms.DateField):
    widget = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")

    def clean(self, value):
        date = super().clean(value)
        if date and date > timezone.localdate():
            raise forms.ValidationError("Please enter a date that is today or earlier.")
        return date


class MemberRegistrationForm(forms.Form):
    submission_token = forms.CharField(widget=forms.HiddenInput, max_length=500)
    contact_website = forms.CharField(required=False, max_length=200,
                                    widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))
    last_name = forms.CharField(max_length=100, label="Last name",
                               widget=forms.TextInput(attrs={"autocomplete": "family-name"}))
    first_name = forms.CharField(max_length=100, label="First name",
                                widget=forms.TextInput(attrs={"autocomplete": "given-name"}))
    middle_name = forms.CharField(max_length=100, required=False, label="Middle name",
                                 widget=forms.TextInput(attrs={"autocomplete": "additional-name"}))
    suffix = forms.CharField(max_length=20, required=False, help_text="For example Jr., Sr. or III.")
    nickname = forms.CharField(max_length=60, required=False, help_text="The name you like to be called.")
    date_of_birth = PastDateField(required=False, label="Date of birth")
    place_of_birth = forms.CharField(max_length=200, required=False, label="Place of birth")
    gender = forms.ChoiceField(required=False, label="Sex", choices=[("", "Prefer not to say"), *Gender.choices])
    civil_status = forms.ChoiceField(required=False, label="Civil status",
                                    choices=[("", "Prefer not to say"), *CivilStatus.choices])
    nationality = forms.CharField(max_length=60, required=False, initial="Filipino")
    home_address = forms.CharField(max_length=2000, required=False, label="Home address",
                                  widget=forms.Textarea(attrs={"rows": 3, "autocomplete": "street-address"}))
    mobile_number = forms.CharField(max_length=20, required=False, label="Mobile number",
                                   widget=forms.TextInput(attrs={"type": "tel", "autocomplete": "tel"}))
    email = forms.EmailField(max_length=254, required=False, widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    spouse_name = forms.CharField(max_length=200, required=False, label="Spouse's full name")
    date_of_marriage = PastDateField(required=False, label="Date of marriage")
    emergency_contact_name = forms.CharField(max_length=200, required=False, label="Emergency contact's name")
    emergency_relationship = forms.CharField(max_length=60, required=False, label="Relationship to you")
    emergency_number = forms.CharField(max_length=20, required=False, label="Emergency contact's phone number",
                                      widget=forms.TextInput(attrs={"type": "tel"}))
    committees = forms.ModelMultipleChoiceField(
        required=False, queryset=Committee.objects.none(), widget=forms.CheckboxSelectMultiple,
        label="Where would you like to serve?",
    )
    notes = forms.CharField(max_length=2000, required=False, label="Anything else for the Secretariat?",
                           widget=forms.Textarea(attrs={"rows": 3}))
    consent_given = forms.BooleanField(
        label="I have read the privacy notice and consent to the church collecting and using my information as described. If I list children, I give consent as their parent or guardian.",
        error_messages={"required": "Please give your consent before submitting your information."},
    )
    public_greeting_consent = forms.BooleanField(
        required=False, label="Yes, the church may greet me by name on its public Facebook page.",
    )

    def __init__(self, *args, session_key, **kwargs):
        super().__init__(*args, **kwargs)
        self.registration_session_key = session_key
        self.fields["committees"].queryset = Committee.objects.filter(
            is_active=True, is_self_selectable=True
        ).order_by("name")
        for field in self.fields.values():
            if isinstance(field, PastDateField):
                field.widget.attrs["max"] = timezone.localdate().isoformat()

    def clean_submission_token(self):
        token = self.cleaned_data["submission_token"]
        try:
            payload = signing.loads(token, salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE)
            from uuid import UUID
            submission_id = UUID(payload["id"])
            if payload["session"] != self.registration_session_key:
                raise ValueError
        except (signing.BadSignature, ValueError, KeyError, TypeError):
            raise forms.ValidationError("This form has expired. Please review your details and submit again.")
        return submission_id

    def clean_committees(self):
        committees = self.cleaned_data["committees"]
        if len(committees) > 2:
            raise forms.ValidationError("Please choose no more than two committees.")
        return committees

    def clean_contact_website(self):
        if self.cleaned_data["contact_website"]:
            raise forms.ValidationError("Please leave this field blank.")
        return ""

    def clean(self):
        data = super().clean()
        birth, marriage = data.get("date_of_birth"), data.get("date_of_marriage")
        if birth and marriage and marriage < birth:
            self.add_error("date_of_marriage", "Please check the marriage date; it is before your birth date.")
        return data


class RegistrationChildForm(forms.Form):
    full_name = forms.CharField(max_length=200, required=False, label="Child's full name")
    date_of_birth = PastDateField(required=False, label="Date of birth")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date_of_birth"].widget.attrs["max"] = timezone.localdate().isoformat()

    def clean(self):
        data = super().clean()
        if data.get("date_of_birth") and not data.get("full_name"):
            self.add_error("full_name", "Please enter the child's name, or leave both fields blank.")
        return data


RegistrationChildFormSet = forms.formset_factory(
    RegistrationChildForm, extra=1, max_num=10, absolute_max=10, validate_max=True,
)
