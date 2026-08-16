# AECI Core Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the member and committee registry for Avdei Elohim Church Inc., so the Secretariat can encode paper profiling forms through the Django admin with role-based access, validation, audit trails, and a privacy retention job.

**Architecture:** Four small Django apps (`core`, `people`, `committees`, `records`) over PostgreSQL. Phase A ships admin-only — no custom templates, no front-end framework. Access control uses Django's built-in groups for model-level permissions, `ModelAdmin.get_queryset()` overrides for row-level scoping, and `get_fields()` overrides for field-level scoping. Change history comes from `django-simple-history`; view auditing is a purpose-built `AccessLog`.

**Tech Stack:** Python 3.12+, Django 5.x, PostgreSQL 16, `django-simple-history`, `django-storages` + `boto3`, `django-environ`, `Pillow`, `pytest` + `pytest-django`, `gunicorn`, `whitenoise`.

**Spec:** `docs/superpowers/specs/2026-08-16-aeci-people-committees-design.md`

**Plan 1 of 2.** This plan covers spec sections §3 (data model), §4 (roles and permissions), §5 (privacy and compliance), §6 (encoding workflow) and §8 (architecture). Spec §7 (reporting and dashboards) is Plan 2 and is deliberately out of scope here — it is built after real records exist to test it against.

## Global Constraints

Copied verbatim from the spec. Every task's requirements implicitly include this section.

- **Python 3.12+, Django 5.x, PostgreSQL.** No SQLite anywhere, including tests — local development must match production (§8.3).
- **Member numbers carry no year:** `MEM-0001`, four digits, zero-padded, never resets (D10).
- **Document numbers carry a year and reset annually:** `EARF-2026-001`, `FR-2026-001`, `RB-2026-001`, `CDV-2026-001`, three digits (D10). Phase A implements the allocator; only `MEM` is used.
- **Only `last_name` and `first_name` are required on `Person`.** Every other field is optional (§3.2).
- **A `Person` is never hard-deleted by any role except ICT.** Deletion is a status change (§4).
- **Twelve committees exist; eleven are self-selectable.** Grievance and Reconciliation has `is_self_selectable=False` (D7).
- **A person may hold at most two active `MEMBER`-role memberships on self-selectable committees.** `CHAIRPERSON`, `CO_CHAIR` and `OVERSIGHT` are exempt from the cap (§3.3).
- **`approved_by` is required when *changing* status to `MEMBER`, and not required when *creating* a record already at `MEMBER`** (§3.2.2). Violating this makes the paper backlog un-encodable.
- **Default `membership_status` is `RELATED`, not `VISITOR`** (D14).
- **A Chairperson sees only `first_name`, `last_name`, `nickname`, `mobile_number` and `email`, for members of their own committee only** (D12).
- **Group names are exactly:** `ICT`, `Secretariat`, `Treasurer`, `Board`, `Chairperson`.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `manage.py`, `aeci/settings.py`, `aeci/urls.py`, `aeci/wsgi.py` | Project configuration, environment-driven settings |
| `docker-compose.yml`, `.env.example` | Local PostgreSQL matching production |
| `pytest.ini`, `conftest.py` | Test configuration and shared fixtures |
| `core/models.py` | `TimeStampedModel` (abstract), `ControlNumberSequence` |
| `core/numbering.py` | Control-number allocation and formatting |
| `core/groups.py` | Group name constants |
| `people/models.py` | `Person`, `Household`, `HouseholdMember` |
| `people/admin.py` | Person encoding screen, inlines, scoping, access logging |
| `committees/models.py` | `Committee`, `CommitteeFunction`, `CommitteeMembership`, `Position`, `Appointment` |
| `committees/admin.py` | Committee and appointment admin |
| `committees/migrations/0002_seed_committees.py` | The 12 committees, their functions, and the church positions |
| `records/models.py` | `FormScan`, `AccessLog` |
| `records/admin.py` | Scan upload screen |
| `core/migrations/0002_create_groups.py` | The five groups and their permissions |
| `people/management/commands/purge_stale_contacts.py` | Retention job (§5.1) |
| `core/management/commands/backup_database.py` | `pg_dump` to object storage (§8.4) |

---

## Task 1: Project scaffold, PostgreSQL, and the test harness

**Files:**
- Create: `manage.py`, `aeci/__init__.py`, `aeci/settings.py`, `aeci/urls.py`, `aeci/wsgi.py`
- Create: `docker-compose.yml`, `.env.example`, `requirements.txt`, `pytest.ini`, `conftest.py`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Consumes: nothing
- Produces: a Django project named `aeci` with `DATABASES["default"]` pointing at PostgreSQL via `DATABASE_URL`; `pytest` runs against a real PostgreSQL test database.

- [ ] **Step 1: Write the failing test**

`tests/test_smoke.py`:

```python
import pytest
from django.db import connection


@pytest.mark.django_db
def test_database_is_postgresql():
    assert connection.vendor == "postgresql"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_smoke.py -v`
Expected: FAIL — pytest cannot find Django settings, or `django.core.exceptions.ImproperlyConfigured`.

- [ ] **Step 3: Write the project configuration**

`requirements.txt`:

```
Django>=5.0,<6.0
psycopg[binary]>=3.1
django-environ>=0.11
django-simple-history>=3.5
django-storages>=1.14
boto3>=1.34
Pillow>=10.2
gunicorn>=21.2
whitenoise>=6.6
pytest>=8.0
pytest-django>=4.8
```

`docker-compose.yml`:

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: aeci
      POSTGRES_USER: aeci
      POSTGRES_PASSWORD: aeci
    ports:
      - "5432:5432"
    volumes:
      - aeci_pgdata:/var/lib/postgresql/data

volumes:
  aeci_pgdata:
```

`.env.example`:

```
DEBUG=True
SECRET_KEY=dev-only-not-for-production
DATABASE_URL=postgres://aeci:aeci@localhost:5432/aeci
ALLOWED_HOSTS=localhost,127.0.0.1
```

`aeci/settings.py`:

```python
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "simple_history",
    "core",
    "people",
    "committees",
    "records",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
]

ROOT_URLCONF = "aeci.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "aeci.wsgi.application"

DATABASES = {"default": env.db("DATABASE_URL")}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-ph"
TIME_ZONE = "Asia/Manila"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Contact data is purged this many days after a person becomes
# TRANSFERRED or DECEASED. Spec section 5.1: two years.
CONTACT_RETENTION_DAYS = 730

# Version string stamped on the current paper profiling form footer.
CONSENT_FORM_VERSION = "v2 (August 2026)"
```

`aeci/urls.py`:

```python
from django.contrib import admin
from django.urls import path

urlpatterns = [path("admin/", admin.site.urls)]
```

`aeci/wsgi.py`:

```python
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "aeci.settings")
application = get_wsgi_application()
```

`manage.py`:

```python
#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "aeci.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
```

`pytest.ini`:

```ini
[pytest]
DJANGO_SETTINGS_MODULE = aeci.settings
python_files = test_*.py
```

`conftest.py`:

```python
import pytest
from django.contrib.auth.models import User


@pytest.fixture
def ict_user(db):
    return User.objects.create_user("ict", password="x", is_staff=True)
```

Create empty app packages so `INSTALLED_APPS` resolves: `core/`, `people/`, `committees/`, `records/`, each with `__init__.py`, `apps.py`, `models.py`, `admin.py`, and a `migrations/__init__.py`.

`core/apps.py` (repeat the pattern for each app, changing the name):

```python
from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
```

- [ ] **Step 4: Start PostgreSQL and run the test**

Run:
```bash
docker compose up -d
cp .env.example .env
pytest tests/test_smoke.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add manage.py aeci core people committees records docker-compose.yml .env.example requirements.txt pytest.ini conftest.py tests
git commit -m "feat: scaffold Django project with PostgreSQL and pytest"
```

---

## Task 2: Control number allocation

**Files:**
- Modify: `core/models.py`
- Create: `core/numbering.py`
- Test: `tests/core/test_numbering.py`

**Interfaces:**
- Consumes: Task 1's project.
- Produces:
  - `core.models.TimeStampedModel` — abstract, fields `created_at`, `updated_at`, `created_by`, `updated_by`.
  - `core.models.ControlNumberSequence` — fields `prefix: str`, `year: int | None`, `last_value: int`.
  - `core.numbering.next_member_no() -> str` returning e.g. `"MEM-0001"`.
  - `core.numbering.next_document_no(prefix: str, year: int) -> str` returning e.g. `"FR-2026-001"`.

- [ ] **Step 1: Write the failing test**

`tests/core/test_numbering.py`:

```python
import pytest

from core.numbering import next_document_no, next_member_no


@pytest.mark.django_db
def test_member_numbers_are_sequential_and_carry_no_year():
    assert next_member_no() == "MEM-0001"
    assert next_member_no() == "MEM-0002"


@pytest.mark.django_db
def test_document_numbers_carry_a_year_and_reset_per_year():
    assert next_document_no("FR", 2026) == "FR-2026-001"
    assert next_document_no("FR", 2026) == "FR-2026-002"
    assert next_document_no("FR", 2027) == "FR-2027-001"


@pytest.mark.django_db
def test_prefixes_do_not_share_a_sequence():
    assert next_document_no("FR", 2026) == "FR-2026-001"
    assert next_document_no("RB", 2026) == "RB-2026-001"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_numbering.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.numbering'`.

- [ ] **Step 3: Write the implementation**

`core/models.py`:

```python
from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        abstract = True


class ControlNumberSequence(models.Model):
    """One row per (prefix, year). Year is NULL for sequences that never reset."""

    prefix = models.CharField(max_length=8)
    year = models.IntegerField(null=True, blank=True)
    last_value = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["prefix", "year"], name="unique_prefix_year"
            )
        ]

    def __str__(self):
        return f"{self.prefix}-{self.year or 'perpetual'}: {self.last_value}"
```

`core/numbering.py`:

```python
from django.db import transaction

from core.models import ControlNumberSequence


def _allocate(prefix: str, year: int | None) -> int:
    """Reserve and return the next integer for this sequence.

    Runs inside a transaction with a row lock so two people encoding at the
    same time cannot be handed the same number.
    """
    with transaction.atomic():
        ControlNumberSequence.objects.get_or_create(prefix=prefix, year=year)
        sequence = ControlNumberSequence.objects.select_for_update().get(
            prefix=prefix, year=year
        )
        sequence.last_value += 1
        sequence.save(update_fields=["last_value"])
        return sequence.last_value


def next_member_no() -> str:
    """Member numbers are permanent identity and carry no year (spec D10)."""
    return f"MEM-{_allocate('MEM', None):04d}"


def next_document_no(prefix: str, year: int) -> str:
    """Document numbers are filed per year and reset annually (spec D10)."""
    return f"{prefix}-{year}-{_allocate(prefix, year):03d}"
```

- [ ] **Step 4: Make and run migrations, then run the tests**

Run:
```bash
python manage.py makemigrations core
pytest tests/core/test_numbering.py -v
```
Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git add core tests/core
git commit -m "feat: add control number sequences with locked allocation"
```

---

## Task 3: The Person model

**Files:**
- Modify: `people/models.py`
- Test: `tests/people/test_person.py`

**Interfaces:**
- Consumes: `core.models.TimeStampedModel`.
- Produces: `people.models.Person` with:
  - `MembershipStatus` — a `TextChoices` class with members `MEMBER`, `CHILD`, `RELATED`, `VISITOR`, `INACTIVE`, `TRANSFERRED`, `DECEASED`.
  - `Person.full_name` property returning `"First Middle Last Suffix"` with blanks collapsed.
  - `Person.TRACKED_FIELDS` — the tuple of field names checked by `has_missing_data`.

- [ ] **Step 1: Write the failing test**

`tests/people/test_person.py`:

```python
import pytest
from django.core.exceptions import ValidationError

from people.models import MembershipStatus, Person


@pytest.mark.django_db
def test_only_names_are_required():
    person = Person(last_name="Malong", first_name="Shan")
    person.full_clean()
    person.save()
    assert person.pk is not None
    assert person.membership_status == MembershipStatus.RELATED


@pytest.mark.django_db
def test_creating_a_person_already_a_member_needs_no_approver():
    """The paper backlog is un-encodable if this fails. Spec section 3.2.2."""
    person = Person(
        last_name="Santos",
        first_name="Rhea",
        membership_status=MembershipStatus.MEMBER,
    )
    person.full_clean()
    person.save()
    assert person.approved_by is None


@pytest.mark.django_db
def test_changing_someone_to_member_requires_an_approver():
    person = Person.objects.create(last_name="Reyes", first_name="Manex")
    person.membership_status = MembershipStatus.MEMBER
    with pytest.raises(ValidationError) as exc:
        person.full_clean()
    assert "approved_by" in exc.value.message_dict


@pytest.mark.django_db
def test_changing_to_member_succeeds_with_an_approver():
    approver = Person.objects.create(last_name="Bilango", first_name="Alpha")
    person = Person.objects.create(last_name="Reyes", first_name="Manex")
    person.membership_status = MembershipStatus.MEMBER
    person.approved_by = approver
    person.full_clean()
    person.save()
    assert person.membership_status == MembershipStatus.MEMBER


@pytest.mark.django_db
def test_status_change_stamps_the_time():
    person = Person.objects.create(last_name="Daclitan", first_name="Kathleen")
    assert person.status_changed_at is None
    person.membership_status = MembershipStatus.TRANSFERRED
    person.save()
    assert person.status_changed_at is not None


@pytest.mark.django_db
def test_missing_data_flag_tracks_blank_fields():
    person = Person.objects.create(last_name="Abiagar", first_name="Sonia")
    assert person.has_missing_data is True

    person.date_of_birth = "1980-04-01"
    person.mobile_number = "09171234567"
    person.email = "sonia@example.com"
    person.home_address = "Km 5, La Trinidad, Benguet"
    person.civil_status = "MARRIED"
    person.save()
    assert person.has_missing_data is False


@pytest.mark.django_db
def test_full_name_collapses_blanks():
    person = Person(last_name="Malong", first_name="Shan", middle_name="Albert")
    assert person.full_name == "Shan Albert Malong"

    plain = Person(last_name="Yagui", first_name="Diana")
    assert plain.full_name == "Diana Yagui"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/people/test_person.py -v`
Expected: FAIL with `ImportError: cannot import name 'MembershipStatus' from 'people.models'`.

- [ ] **Step 3: Write the implementation**

`people/models.py`:

```python
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from core.models import TimeStampedModel


class MembershipStatus(models.TextChoices):
    MEMBER = "MEMBER", "Member"
    CHILD = "CHILD", "Child"
    RELATED = "RELATED", "Related (spouse or guardian, not a member)"
    VISITOR = "VISITOR", "Visitor"
    INACTIVE = "INACTIVE", "Inactive"
    TRANSFERRED = "TRANSFERRED", "Transferred"
    DECEASED = "DECEASED", "Deceased"


class Gender(models.TextChoices):
    MALE = "MALE", "Male"
    FEMALE = "FEMALE", "Female"


class CivilStatus(models.TextChoices):
    SINGLE = "SINGLE", "Single"
    MARRIED = "MARRIED", "Married"
    WIDOWED = "WIDOWED", "Widowed"
    SEPARATED = "SEPARATED", "Separated"
    ANNULLED = "ANNULLED", "Annulled"


class Person(TimeStampedModel):
    """A human known to the church. Membership is a status, not a separate model."""

    # Fields the follow-up queue chases when blank (spec section 6.3).
    TRACKED_FIELDS = (
        "date_of_birth",
        "mobile_number",
        "email",
        "home_address",
        "civil_status",
    )

    # Cleared by purge_stale_contacts two years after transfer or death.
    CONTACT_FIELDS = (
        "mobile_number",
        "email",
        "home_address",
        "emergency_contact_name",
        "emergency_contact_relationship",
        "emergency_contact_number",
    )

    member_no = models.CharField(max_length=12, unique=True, null=True, blank=True)

    last_name = models.CharField(max_length=100)
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    suffix = models.CharField(max_length=20, blank=True)
    nickname = models.CharField(
        max_length=60, blank=True, help_text="The name this person actually goes by."
    )

    date_of_birth = models.DateField(null=True, blank=True)
    place_of_birth = models.CharField(max_length=200, blank=True)
    gender = models.CharField(max_length=10, choices=Gender.choices, blank=True)
    civil_status = models.CharField(
        max_length=12, choices=CivilStatus.choices, blank=True
    )
    nationality = models.CharField(max_length=60, default="Filipino", blank=True)

    home_address = models.TextField(blank=True)
    mobile_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)

    membership_status = models.CharField(
        max_length=12,
        choices=MembershipStatus.choices,
        default=MembershipStatus.RELATED,
    )
    status_changed_at = models.DateTimeField(null=True, blank=True)
    date_filed = models.DateField(
        null=True, blank=True, help_text="The date written on the paper form."
    )
    date_became_member = models.DateField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="approved"
    )
    date_of_death = models.DateField(null=True, blank=True)

    guardian = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="wards"
    )
    guardian_relationship = models.CharField(max_length=60, blank=True)

    emergency_contact_name = models.CharField(max_length=200, blank=True)
    emergency_contact_relationship = models.CharField(max_length=60, blank=True)
    emergency_contact_number = models.CharField(max_length=20, blank=True)

    consent_given = models.BooleanField(default=False)
    consent_date = models.DateField(null=True, blank=True)
    consent_version = models.CharField(max_length=20, blank=True)
    greeting_opt_out = models.BooleanField(
        default=False, help_text="Suppress this person from birthday and anniversary lists."
    )

    has_missing_data = models.BooleanField(default=False, editable=False)
    follow_up_notes = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="person",
    )

    history = HistoricalRecords()

    class Meta:
        ordering = ("last_name", "first_name")
        verbose_name_plural = "people"

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded_status = instance.membership_status
        return instance

    def __str__(self):
        return f"{self.full_name} ({self.member_no})" if self.member_no else self.full_name

    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.middle_name, self.last_name, self.suffix]
        return " ".join(part for part in parts if part)

    @property
    def missing_fields(self) -> list[str]:
        return [name for name in self.TRACKED_FIELDS if not getattr(self, name)]

    def clean(self):
        super().clean()
        loaded = getattr(self, "_loaded_status", None)
        becoming_member = (
            loaded is not None
            and loaded != MembershipStatus.MEMBER
            and self.membership_status == MembershipStatus.MEMBER
        )
        if becoming_member and self.approved_by_id is None:
            raise ValidationError(
                {
                    "approved_by": (
                        "Record who accepted this person into membership. "
                        "The Board or Pastor decides; the system only records it."
                    )
                }
            )

    def save(self, *args, **kwargs):
        loaded = getattr(self, "_loaded_status", None)
        if loaded != self.membership_status:
            self.status_changed_at = timezone.now()
        self.has_missing_data = bool(self.missing_fields)
        super().save(*args, **kwargs)
        self._loaded_status = self.membership_status
```

- [ ] **Step 4: Make and run migrations, then run the tests**

Run:
```bash
python manage.py makemigrations people
pytest tests/people/test_person.py -v
```
Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add people tests/people
git commit -m "feat: add Person with status rules and follow-up tracking"
```

---

## Task 4: Households and family links

**Files:**
- Modify: `people/models.py`
- Test: `tests/people/test_household.py`

**Interfaces:**
- Consumes: `people.models.Person`.
- Produces:
  - `people.models.Household` — fields `name`, `address`, `date_of_marriage`.
  - `people.models.HouseholdMember` — fields `household`, `person`, `role`.
  - `people.models.HouseholdRole` — `TextChoices` with `HEAD`, `SPOUSE`, `CHILD`, `OTHER`.

- [ ] **Step 1: Write the failing test**

`tests/people/test_household.py`:

```python
import pytest
from django.db import IntegrityError

from people.models import Household, HouseholdMember, HouseholdRole, Person


@pytest.mark.django_db
def test_a_household_holds_a_spouse_and_children():
    household = Household.objects.create(
        name="Malong Family", date_of_marriage="2010-05-14"
    )
    head = Person.objects.create(last_name="Malong", first_name="Shan")
    spouse = Person.objects.create(last_name="Malong", first_name="Maria")
    child = Person.objects.create(last_name="Malong", first_name="Joy")

    HouseholdMember.objects.create(
        household=household, person=head, role=HouseholdRole.HEAD
    )
    HouseholdMember.objects.create(
        household=household, person=spouse, role=HouseholdRole.SPOUSE
    )
    HouseholdMember.objects.create(
        household=household, person=child, role=HouseholdRole.CHILD
    )

    assert household.members.count() == 3
    assert household.members.filter(role=HouseholdRole.CHILD).count() == 1


@pytest.mark.django_db
def test_a_person_appears_once_per_household():
    household = Household.objects.create(name="Reyes Family")
    person = Person.objects.create(last_name="Reyes", first_name="Manex")
    HouseholdMember.objects.create(
        household=household, person=person, role=HouseholdRole.HEAD
    )
    with pytest.raises(IntegrityError):
        HouseholdMember.objects.create(
            household=household, person=person, role=HouseholdRole.OTHER
        )


@pytest.mark.django_db
def test_a_guardian_can_live_outside_the_household():
    """Spec section 3.2: a grandmother brings a child whose parents do not attend."""
    grandmother = Person.objects.create(last_name="Lang-ayan", first_name="Diana")
    child = Person.objects.create(
        last_name="Bilango",
        first_name="Ken",
        guardian=grandmother,
        guardian_relationship="Grandmother",
    )
    assert child.guardian == grandmother
    assert grandmother.wards.count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/people/test_household.py -v`
Expected: FAIL with `ImportError: cannot import name 'Household' from 'people.models'`.

- [ ] **Step 3: Write the implementation**

Append to `people/models.py`:

```python
class HouseholdRole(models.TextChoices):
    HEAD = "HEAD", "Head"
    SPOUSE = "SPOUSE", "Spouse"
    CHILD = "CHILD", "Child"
    OTHER = "OTHER", "Other"


class Household(TimeStampedModel):
    name = models.CharField(max_length=200, help_text='For example, "Malong Family".')
    address = models.TextField(blank=True)
    date_of_marriage = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class HouseholdMember(models.Model):
    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="members"
    )
    person = models.ForeignKey(
        Person, on_delete=models.CASCADE, related_name="household_memberships"
    )
    role = models.CharField(max_length=10, choices=HouseholdRole.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["household", "person"], name="unique_person_per_household"
            )
        ]

    def __str__(self):
        return f"{self.person.full_name} — {self.get_role_display()}"
```

- [ ] **Step 4: Make and run migrations, then run the tests**

Run:
```bash
python manage.py makemigrations people
pytest tests/people -v
```
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add people tests/people
git commit -m "feat: add households, family roles, and outside guardians"
```

---

## Task 5: Committees, functions, and seed data

**Files:**
- Modify: `committees/models.py`
- Create: `committees/migrations/0002_seed_committees.py`
- Test: `tests/committees/test_committees.py`

**Interfaces:**
- Consumes: `core.models.TimeStampedModel`.
- Produces:
  - `committees.models.Committee` — fields `name`, `code`, `description`, `is_self_selectable`, `is_active`.
  - `committees.models.CommitteeFunction` — fields `committee`, `name`, `description`.

- [ ] **Step 1: Write the failing test**

`tests/committees/test_committees.py`:

```python
import pytest
from django.db import IntegrityError

from committees.models import Committee, CommitteeFunction


@pytest.mark.django_db
def test_twelve_committees_are_seeded():
    assert Committee.objects.count() == 12


@pytest.mark.django_db
def test_eleven_committees_appear_on_the_profiling_form():
    """Spec D7: Grievance and Reconciliation is appointed, not self-selected."""
    assert Committee.objects.filter(is_self_selectable=True).count() == 11
    grievance = Committee.objects.get(code="grievance-and-reconciliation")
    assert grievance.is_self_selectable is False


@pytest.mark.django_db
def test_sunshine_has_its_three_functions():
    sunshine = Committee.objects.get(code="sunshine")
    names = set(sunshine.functions.values_list("name", flat=True))
    assert names == {"Ushering and Marshall", "Transport", "Benevolence"}


@pytest.mark.django_db
def test_function_names_are_unique_within_a_committee():
    sunshine = Committee.objects.get(code="sunshine")
    with pytest.raises(IntegrityError):
        CommitteeFunction.objects.create(committee=sunshine, name="Transport")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/committees/test_committees.py -v`
Expected: FAIL with `ImportError: cannot import name 'Committee' from 'committees.models'`.

- [ ] **Step 3: Write the models**

`committees/models.py`:

```python
from django.db import models

from core.models import TimeStampedModel


class Committee(TimeStampedModel):
    name = models.CharField(max_length=120)
    code = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    is_self_selectable = models.BooleanField(
        default=True,
        help_text="Whether members may choose this committee on the profiling form.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class CommitteeFunction(models.Model):
    """A sub-team inside a committee, such as Transport within Sunshine."""

    committee = models.ForeignKey(
        Committee, on_delete=models.CASCADE, related_name="functions"
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ("committee__name", "name")
        constraints = [
            models.UniqueConstraint(
                fields=["committee", "name"], name="unique_function_per_committee"
            )
        ]

    def __str__(self):
        return f"{self.committee.name} — {self.name}"
```

- [ ] **Step 4: Write the seed migration**

Run `python manage.py makemigrations committees` first, then create `committees/migrations/0002_seed_committees.py`:

```python
from django.db import migrations

# Spec section 3.3. Twelve committees; Grievance and Reconciliation is
# appointed by the Board rather than chosen, so it is not self-selectable.
COMMITTEES = [
    ("Sunshine", "sunshine", True, ["Ushering and Marshall", "Transport", "Benevolence"]),
    ("General Services", "general-services", True,
     ["Construction and Repair", "Maintenance", "Building Tools"]),
    ("Property and Supplies", "property-and-supplies", True,
     ["Musical Instruments", "Supplies"]),
    ("Music and Arts", "music-and-arts", True, ["Sounds", "Song Leading", "Instrument"]),
    ("Children's Ministry", "childrens-ministry", True, []),
    ("Youth", "youth", True, []),
    ("Events", "events", True, []),
    ("Finance and Resource Accessing", "finance-and-resource-accessing", True, []),
    ("Grievance and Reconciliation", "grievance-and-reconciliation", False, []),
    ("ICT", "ict", True, []),
    ("Secretariat", "secretariat", True, []),
    ("Food", "food", True, []),
]


def seed(apps, schema_editor):
    Committee = apps.get_model("committees", "Committee")
    CommitteeFunction = apps.get_model("committees", "CommitteeFunction")
    for name, code, selectable, functions in COMMITTEES:
        committee, _ = Committee.objects.get_or_create(
            code=code, defaults={"name": name, "is_self_selectable": selectable}
        )
        for function_name in functions:
            CommitteeFunction.objects.get_or_create(
                committee=committee, name=function_name
            )


def unseed(apps, schema_editor):
    Committee = apps.get_model("committees", "Committee")
    Committee.objects.filter(code__in=[code for _, code, _, _ in COMMITTEES]).delete()


class Migration(migrations.Migration):
    dependencies = [("committees", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/committees/test_committees.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 6: Commit**

```bash
git add committees tests/committees
git commit -m "feat: add committees with sub-functions and seed the twelve"
```

---

## Task 6: Positions and officer appointments

**Files:**
- Modify: `committees/models.py`
- Create: `committees/migrations/0003_seed_positions.py`
- Test: `tests/committees/test_appointments.py`

**Interfaces:**
- Consumes: `people.models.Person`.
- Produces:
  - `committees.models.Position` — fields `name`, `code`, `is_unique_holder`.
  - `committees.models.Appointment` — fields `person`, `position`, `start_date`, `end_date`; manager method `Appointment.objects.active()` returning appointments with `end_date` null or in the future.
  - Seeded position codes: `pastor`, `board-chairperson`, `treasurer`, `secretary`, `board-member`.

- [ ] **Step 1: Write the failing test**

`tests/committees/test_appointments.py`:

```python
import datetime as dt

import pytest
from django.core.exceptions import ValidationError

from committees.models import Appointment, Position
from people.models import Person


@pytest.fixture
def treasurer_position(db):
    return Position.objects.get(code="treasurer")


@pytest.mark.django_db
def test_positions_are_seeded():
    assert Position.objects.count() == 5
    assert Position.objects.get(code="treasurer").is_unique_holder is True
    assert Position.objects.get(code="board-member").is_unique_holder is False


@pytest.mark.django_db
def test_two_people_cannot_hold_a_unique_position_at_once(treasurer_position):
    first = Person.objects.create(last_name="Fredalyn", first_name="A")
    second = Person.objects.create(last_name="Juliet", first_name="B")
    Appointment.objects.create(
        person=first, position=treasurer_position, start_date=dt.date(2026, 1, 1)
    )
    clash = Appointment(
        person=second, position=treasurer_position, start_date=dt.date(2026, 6, 1)
    )
    with pytest.raises(ValidationError):
        clash.full_clean()


@pytest.mark.django_db
def test_a_successor_may_start_after_the_previous_holder_ends(treasurer_position):
    first = Person.objects.create(last_name="Fredalyn", first_name="A")
    second = Person.objects.create(last_name="Juliet", first_name="B")
    Appointment.objects.create(
        person=first,
        position=treasurer_position,
        start_date=dt.date(2025, 1, 1),
        end_date=dt.date(2025, 12, 31),
    )
    successor = Appointment(
        person=second, position=treasurer_position, start_date=dt.date(2026, 1, 1)
    )
    successor.full_clean()
    successor.save()
    assert Appointment.objects.count() == 2


@pytest.mark.django_db
def test_several_people_may_be_board_members_at_once():
    board_member = Position.objects.get(code="board-member")
    for name in ("Diego", "Jemuel", "Sonia"):
        person = Person.objects.create(last_name=name, first_name="X")
        appointment = Appointment(
            person=person, position=board_member, start_date=dt.date(2026, 1, 1)
        )
        appointment.full_clean()
        appointment.save()
    assert Appointment.objects.count() == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/committees/test_appointments.py -v`
Expected: FAIL with `ImportError: cannot import name 'Appointment' from 'committees.models'`.

- [ ] **Step 3: Write the models**

Append to `committees/models.py`:

```python
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone


class Position(models.Model):
    """A church-level office, distinct from committee membership."""

    name = models.CharField(max_length=120)
    code = models.SlugField(unique=True)
    is_unique_holder = models.BooleanField(
        default=True, help_text="Whether only one person may hold this at a time."
    )

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class AppointmentQuerySet(models.QuerySet):
    def active(self, on=None):
        on = on or timezone.localdate()
        return self.filter(start_date__lte=on).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=on)
        )


class Appointment(TimeStampedModel):
    person = models.ForeignKey(
        "people.Person", on_delete=models.PROTECT, related_name="appointments"
    )
    position = models.ForeignKey(
        Position, on_delete=models.PROTECT, related_name="appointments"
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    history = HistoricalRecords()
    objects = AppointmentQuerySet.as_manager()

    class Meta:
        ordering = ("-start_date",)

    def __str__(self):
        return f"{self.person.full_name} — {self.position.name}"

    def clean(self):
        super().clean()
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "The end date cannot precede the start date."})
        if not self.position_id or not self.position.is_unique_holder:
            return

        others = Appointment.objects.filter(position=self.position).exclude(pk=self.pk)
        for other in others:
            starts_before_other_ends = (
                other.end_date is None or self.start_date <= other.end_date
            )
            other_starts_before_this_ends = (
                self.end_date is None or other.start_date <= self.end_date
            )
            if starts_before_other_ends and other_starts_before_this_ends:
                raise ValidationError(
                    f"{other.person.full_name} already holds {self.position.name} "
                    f"over these dates. End that appointment first."
                )
```

**Move the imports to the top of the file.** The block above opens with `from django.core.exceptions import ValidationError`, `from django.db.models import Q` and `from django.utils import timezone` for readability, but they belong in the import block at the top of `committees/models.py`. Add `from simple_history.models import HistoricalRecords` there as well.

- [ ] **Step 4: Write the seed migration**

Run `python manage.py makemigrations committees`, then create `committees/migrations/0003_seed_positions.py`:

```python
from django.db import migrations

POSITIONS = [
    ("Pastor", "pastor", True),
    ("Chairperson of the Board", "board-chairperson", True),
    ("Treasurer", "treasurer", True),
    ("Secretary", "secretary", True),
    ("Board Member", "board-member", False),
]


def seed(apps, schema_editor):
    Position = apps.get_model("committees", "Position")
    for name, code, unique in POSITIONS:
        Position.objects.get_or_create(
            code=code, defaults={"name": name, "is_unique_holder": unique}
        )


def unseed(apps, schema_editor):
    Position = apps.get_model("committees", "Position")
    Position.objects.filter(code__in=[code for _, code, _ in POSITIONS]).delete()


class Migration(migrations.Migration):
    dependencies = [("committees", "0002_seed_committees")]
    operations = [migrations.RunPython(seed, unseed)]
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/committees -v`
Expected: PASS, 8 tests.

- [ ] **Step 6: Commit**

```bash
git add committees tests/committees
git commit -m "feat: add positions and appointments with overlap protection"
```

---

## Task 7: Committee membership and its four rules

**Files:**
- Modify: `committees/models.py`
- Test: `tests/committees/test_membership.py`

**Interfaces:**
- Consumes: `Committee`, `CommitteeFunction`, `Position`, `Appointment`, `people.models.Person`.
- Produces:
  - `committees.models.CommitteeRole` — `TextChoices` with `CHAIRPERSON`, `CO_CHAIR`, `MEMBER`, `OVERSIGHT`.
  - `committees.models.CommitteeMembership` — fields `committee`, `person`, `function`, `role`, `date_joined`, `date_left`; manager method `.active()`.
  - `CommitteeMembership.SELF_SELECTED_LIMIT = 2`.

- [ ] **Step 1: Write the failing test**

`tests/committees/test_membership.py`:

```python
import datetime as dt

import pytest
from django.core.exceptions import ValidationError

from committees.models import (
    Appointment,
    Committee,
    CommitteeFunction,
    CommitteeMembership,
    CommitteeRole,
    Position,
)
from people.models import Person

TODAY = dt.date(2026, 8, 16)


@pytest.fixture
def person(db):
    return Person.objects.create(last_name="Malong", first_name="Shan")


def join(person, code, role=CommitteeRole.MEMBER):
    membership = CommitteeMembership(
        committee=Committee.objects.get(code=code),
        person=person,
        role=role,
        date_joined=TODAY,
    )
    membership.full_clean()
    membership.save()
    return membership


@pytest.mark.django_db
def test_a_person_may_join_two_committees(person):
    join(person, "ict")
    join(person, "events")
    assert CommitteeMembership.objects.active().filter(person=person).count() == 2


@pytest.mark.django_db
def test_a_third_committee_is_refused(person):
    join(person, "ict")
    join(person, "events")
    with pytest.raises(ValidationError) as exc:
        join(person, "food")
    assert "two" in str(exc.value).lower()


@pytest.mark.django_db
def test_leaving_a_committee_frees_a_slot(person):
    first = join(person, "ict")
    join(person, "events")
    first.date_left = TODAY
    first.save()
    join(person, "food")
    assert CommitteeMembership.objects.active().filter(person=person).count() == 2


@pytest.mark.django_db
def test_being_chairperson_does_not_use_up_a_slot(person):
    """Spec section 3.3: otherwise chairing Grievance would block Diego elsewhere."""
    join(person, "grievance-and-reconciliation", role=CommitteeRole.CHAIRPERSON)
    join(person, "ict")
    join(person, "events")
    assert CommitteeMembership.objects.active().filter(person=person).count() == 3


@pytest.mark.django_db
def test_only_one_chairperson_per_committee(person):
    other = Person.objects.create(last_name="Daclitan", first_name="Kathleen")
    join(person, "ict", role=CommitteeRole.CHAIRPERSON)
    with pytest.raises(ValidationError) as exc:
        join(other, "ict", role=CommitteeRole.CHAIRPERSON)
    assert "chairperson" in str(exc.value).lower()


@pytest.mark.django_db
def test_a_function_must_belong_to_its_own_committee(person):
    transport = CommitteeFunction.objects.get(name="Transport")
    membership = CommitteeMembership(
        committee=Committee.objects.get(code="ict"),
        person=person,
        function=transport,
        role=CommitteeRole.MEMBER,
        date_joined=TODAY,
    )
    with pytest.raises(ValidationError):
        membership.full_clean()


@pytest.mark.django_db
def test_oversight_requires_a_board_appointment(person):
    with pytest.raises(ValidationError) as exc:
        join(person, "ict", role=CommitteeRole.OVERSIGHT)
    assert "board" in str(exc.value).lower()

    Appointment.objects.create(
        person=person,
        position=Position.objects.get(code="board-member"),
        start_date=dt.date(2026, 1, 1),
    )
    join(person, "ict", role=CommitteeRole.OVERSIGHT)
    assert CommitteeMembership.objects.filter(role=CommitteeRole.OVERSIGHT).count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/committees/test_membership.py -v`
Expected: FAIL with `ImportError: cannot import name 'CommitteeMembership' from 'committees.models'`.

- [ ] **Step 3: Write the implementation**

Append to `committees/models.py`:

```python
BOARD_POSITION_CODES = ("board-member", "board-chairperson", "pastor")


class CommitteeRole(models.TextChoices):
    CHAIRPERSON = "CHAIRPERSON", "Chairperson"
    CO_CHAIR = "CO_CHAIR", "Co-Chair"
    MEMBER = "MEMBER", "Member"
    OVERSIGHT = "OVERSIGHT", "Board Oversight"


class CommitteeMembershipQuerySet(models.QuerySet):
    def active(self, on=None):
        on = on or timezone.localdate()
        return self.filter(date_joined__lte=on).filter(
            Q(date_left__isnull=True) | Q(date_left__gte=on)
        )


class CommitteeMembership(TimeStampedModel):
    # Spec section 3.3: the profiling form says "select up to TWO (2)".
    SELF_SELECTED_LIMIT = 2

    # Appointed roles do not consume a self-selected slot.
    APPOINTED_ROLES = (
        CommitteeRole.CHAIRPERSON,
        CommitteeRole.CO_CHAIR,
        CommitteeRole.OVERSIGHT,
    )

    committee = models.ForeignKey(
        Committee, on_delete=models.PROTECT, related_name="memberships"
    )
    person = models.ForeignKey(
        "people.Person", on_delete=models.CASCADE, related_name="committee_memberships"
    )
    function = models.ForeignKey(
        CommitteeFunction,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="memberships",
    )
    role = models.CharField(
        max_length=12, choices=CommitteeRole.choices, default=CommitteeRole.MEMBER
    )
    date_joined = models.DateField()
    date_left = models.DateField(null=True, blank=True)

    history = HistoricalRecords()
    objects = CommitteeMembershipQuerySet.as_manager()

    class Meta:
        ordering = ("committee__name", "person__last_name")

    def __str__(self):
        return f"{self.person.full_name} — {self.committee.name} ({self.get_role_display()})"

    @property
    def is_active(self) -> bool:
        today = timezone.localdate()
        return self.date_joined <= today and (
            self.date_left is None or self.date_left >= today
        )

    def clean(self):
        super().clean()
        self._check_function_belongs_to_committee()
        self._check_self_selected_limit()
        self._check_single_chairperson()
        self._check_oversight_is_on_the_board()

    def _check_function_belongs_to_committee(self):
        if self.function_id and self.function.committee_id != self.committee_id:
            raise ValidationError(
                {"function": f"{self.function.name} is not part of {self.committee.name}."}
            )

    def _check_self_selected_limit(self):
        if self.role in self.APPOINTED_ROLES or self.date_left:
            return
        if not self.committee.is_self_selectable:
            return
        existing = (
            CommitteeMembership.objects.active()
            .filter(person=self.person, role=CommitteeRole.MEMBER)
            .filter(committee__is_self_selectable=True)
            .exclude(pk=self.pk)
            .count()
        )
        if existing >= self.SELF_SELECTED_LIMIT:
            raise ValidationError(
                f"{self.person.full_name} already serves on "
                f"{self.SELF_SELECTED_LIMIT} committees. A member may choose up to two. "
                f"End an existing membership first."
            )

    def _check_single_chairperson(self):
        if self.role != CommitteeRole.CHAIRPERSON or self.date_left:
            return
        clash = (
            CommitteeMembership.objects.active()
            .filter(committee=self.committee, role=CommitteeRole.CHAIRPERSON)
            .exclude(pk=self.pk)
            .first()
        )
        if clash:
            raise ValidationError(
                f"{clash.person.full_name} is already Chairperson of "
                f"{self.committee.name}. End that role first."
            )

    def _check_oversight_is_on_the_board(self):
        if self.role != CommitteeRole.OVERSIGHT:
            return
        on_board = (
            Appointment.objects.active()
            .filter(person=self.person, position__code__in=BOARD_POSITION_CODES)
            .exists()
        )
        if not on_board:
            raise ValidationError(
                f"{self.person.full_name} holds no active Board appointment, so they "
                f"cannot be Board Oversight. Record the appointment first."
            )
```

- [ ] **Step 4: Make and run migrations, then run the tests**

Run:
```bash
python manage.py makemigrations committees
pytest tests/committees -v
```
Expected: PASS, 15 tests.

- [ ] **Step 5: Commit**

```bash
git add committees tests/committees
git commit -m "feat: add committee membership with the four validation rules"
```

---

## Task 8: Form scans and the access log

**Files:**
- Modify: `records/models.py`, `aeci/settings.py`
- Test: `tests/records/test_records.py`

**Interfaces:**
- Consumes: `people.models.Person`.
- Produces:
  - `records.models.FormScan` — fields `person` (nullable), `form_type`, `file`, `uploaded_by`, `uploaded_at`, `notes`.
  - `records.models.FormType` — `TextChoices` with `MEMBER_PROFILING`, `EARF`, `FR`, `RB`, `CDV`, `MOM`, `OTHER`.
  - `records.models.AccessLog` — fields `user`, `person` (nullable), `report` (blank), `timestamp`, `ip_address`; classmethod `AccessLog.record(user, person=None, report="", ip=None)`.

- [ ] **Step 1: Write the failing test**

`tests/records/test_records.py`:

```python
import pytest
from django.contrib.auth.models import User

from people.models import Person
from records.models import AccessLog, FormScan, FormType


@pytest.mark.django_db
def test_a_scan_can_exist_before_it_is_linked_to_anyone():
    """Photos get uploaded in a batch, then matched to people during encoding."""
    scan = FormScan.objects.create(form_type=FormType.MEMBER_PROFILING)
    assert scan.person is None


@pytest.mark.django_db
def test_a_scan_links_to_a_person():
    person = Person.objects.create(last_name="Malong", first_name="Shan")
    scan = FormScan.objects.create(person=person, form_type=FormType.MEMBER_PROFILING)
    assert person.scans.count() == 1
    assert scan.get_form_type_display() == "Member Profiling Form"


@pytest.mark.django_db
def test_viewing_a_person_is_recorded():
    user = User.objects.create_user("secretariat", password="x")
    person = Person.objects.create(last_name="Santos", first_name="Rhea")
    AccessLog.record(user=user, person=person, ip="10.0.0.1")
    entry = AccessLog.objects.get()
    assert entry.user == user
    assert entry.person == person
    assert entry.ip_address == "10.0.0.1"


@pytest.mark.django_db
def test_a_report_writes_one_entry_not_one_per_row():
    """Spec section 7.6: per-row logging buries the signal the log exists for."""
    user = User.objects.create_user("sunshine", password="x")
    for name in ("A", "B", "C"):
        Person.objects.create(last_name=name, first_name="X")
    AccessLog.record(user=user, report="birthdays:next-30-days")
    assert AccessLog.objects.count() == 1
    assert AccessLog.objects.get().person is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/records/test_records.py -v`
Expected: FAIL with `ImportError: cannot import name 'FormScan' from 'records.models'`.

- [ ] **Step 3: Write the implementation**

`records/models.py`:

```python
from django.conf import settings
from django.db import models


class FormType(models.TextChoices):
    MEMBER_PROFILING = "MEMBER_PROFILING", "Member Profiling Form"
    EARF = "EARF", "Event and Activity Request Form"
    FR = "FR", "Fund Request Form"
    RB = "RB", "Fund Reimbursement Form"
    CDV = "CDV", "Cash Disbursement Voucher"
    MOM = "MOM", "Minutes of Meeting"
    OTHER = "OTHER", "Other"


class FormScan(models.Model):
    """A photograph of a paper form, kept as evidence and for reference."""

    person = models.ForeignKey(
        "people.Person",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="scans",
    )
    form_type = models.CharField(max_length=20, choices=FormType.choices)
    file = models.FileField(upload_to="scans/%Y/%m/", blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("-uploaded_at",)

    def __str__(self):
        who = self.person.full_name if self.person else "unlinked"
        return f"{self.get_form_type_display()} — {who}"


class AccessLog(models.Model):
    """Who looked at whom.

    django-simple-history records changes; it does not record reads. Under
    RA 10173 this is the log that answers a member asking how their address
    circulated. Spec section 5.2.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    person = models.ForeignKey(
        "people.Person", null=True, blank=True, on_delete=models.CASCADE
    )
    report = models.CharField(
        max_length=120,
        blank=True,
        help_text="Set instead of person when a whole list was viewed.",
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ("-timestamp",)

    def __str__(self):
        target = self.person.full_name if self.person else self.report
        return f"{self.user} viewed {target}"

    @classmethod
    def record(cls, user, person=None, report="", ip=None):
        return cls.objects.create(
            user=user, person=person, report=report, ip_address=ip
        )
```

Append to `aeci/settings.py` — object storage, because free-tier hosting has an ephemeral disk and local uploads vanish on redeploy (spec D11):

```python
# Scans MUST live in object storage. A free-tier host resets its filesystem
# on every redeploy and on idle spin-down, which silently destroys uploads.
if env.bool("USE_S3_STORAGE", default=False):
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "bucket_name": env("AWS_STORAGE_BUCKET_NAME"),
                "endpoint_url": env("AWS_S3_ENDPOINT_URL"),
                "access_key": env("AWS_ACCESS_KEY_ID"),
                "secret_key": env("AWS_SECRET_ACCESS_KEY"),
                "default_acl": "private",
                "querystring_auth": True,
            },
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        },
    }
else:
    MEDIA_ROOT = BASE_DIR / "media"
    MEDIA_URL = "media/"
```

- [ ] **Step 4: Make and run migrations, then run the tests**

Run:
```bash
python manage.py makemigrations records
pytest tests/records -v
```
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add records aeci/settings.py tests/records
git commit -m "feat: add form scans in object storage and the view access log"
```

---

## Task 9: The five groups and their permissions

**Files:**
- Create: `core/groups.py`, `core/migrations/0002_create_groups.py`
- Test: `tests/core/test_groups.py`

**Interfaces:**
- Consumes: all models from Tasks 3–8.
- Produces:
  - `core.groups.ICT`, `SECRETARIAT`, `TREASURER`, `BOARD`, `CHAIRPERSON` — string constants.
  - `core.groups.ALL_GROUPS` — tuple of all five.
  - Five `auth.Group` rows with model-level permissions assigned.

- [ ] **Step 1: Write the failing test**

`tests/core/test_groups.py`:

```python
import pytest
from django.contrib.auth.models import Group

from core import groups


@pytest.mark.django_db
def test_all_five_groups_exist():
    assert set(Group.objects.values_list("name", flat=True)) == set(groups.ALL_GROUPS)


@pytest.mark.django_db
def test_secretariat_can_edit_people_but_not_create_logins():
    codenames = set(
        Group.objects.get(name=groups.SECRETARIAT)
        .permissions.values_list("codename", flat=True)
    )
    assert "change_person" in codenames
    assert "add_person" in codenames
    assert "delete_person" not in codenames
    assert "add_user" not in codenames


@pytest.mark.django_db
def test_ict_can_create_logins_but_the_board_cannot():
    ict = set(
        Group.objects.get(name=groups.ICT).permissions.values_list("codename", flat=True)
    )
    board = set(
        Group.objects.get(name=groups.BOARD).permissions.values_list("codename", flat=True)
    )
    assert "add_user" in ict
    assert "add_user" not in board


@pytest.mark.django_db
def test_nobody_but_ict_may_delete_a_person():
    """Spec section 4: deletion is a status change, not a row removal."""
    for name in (groups.SECRETARIAT, groups.BOARD, groups.CHAIRPERSON, groups.TREASURER):
        codenames = set(
            Group.objects.get(name=name).permissions.values_list("codename", flat=True)
        )
        assert "delete_person" not in codenames
    ict = set(
        Group.objects.get(name=groups.ICT).permissions.values_list("codename", flat=True)
    )
    assert "delete_person" in ict


@pytest.mark.django_db
def test_chairpersons_may_only_view_people():
    codenames = set(
        Group.objects.get(name=groups.CHAIRPERSON)
        .permissions.values_list("codename", flat=True)
    )
    assert codenames == {"view_person", "view_committee", "view_committeemembership"}


@pytest.mark.django_db
def test_the_treasurer_group_is_empty_in_phase_a():
    """Spec section 4: the Treasurer's work lives in Phases B and C."""
    assert Group.objects.get(name=groups.TREASURER).permissions.count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_groups.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.groups'`.

- [ ] **Step 3: Write the constants and the migration**

`core/groups.py`:

```python
ICT = "ICT"
SECRETARIAT = "Secretariat"
TREASURER = "Treasurer"
BOARD = "Board"
CHAIRPERSON = "Chairperson"

ALL_GROUPS = (ICT, SECRETARIAT, TREASURER, BOARD, CHAIRPERSON)
```

`core/migrations/0002_create_groups.py`:

```python
from django.db import migrations

# Spec section 4. Treasurer is intentionally empty in Phase A: fund release,
# OR numbers and the ledger are Phases B and C. The group is created now so
# accounts and memberships are in place before those subsystems land.
GROUP_PERMISSIONS = {
    "ICT": "__all__",
    "Secretariat": [
        "add_person", "change_person", "view_person",
        "add_household", "change_household", "view_household", "delete_household",
        "add_householdmember", "change_householdmember", "view_householdmember",
        "delete_householdmember",
        "add_committeemembership", "change_committeemembership",
        "view_committeemembership", "delete_committeemembership",
        "view_committee", "view_committeefunction",
        "view_position", "view_appointment",
        "add_formscan", "change_formscan", "view_formscan",
    ],
    "Treasurer": [],
    "Board": [
        "view_person",
        "view_household", "view_householdmember",
        "add_committeemembership", "change_committeemembership",
        "view_committeemembership", "delete_committeemembership",
        "view_committee", "view_committeefunction",
        "add_appointment", "change_appointment", "view_appointment",
        "view_position",
        "view_accesslog",
    ],
    "Chairperson": ["view_person", "view_committee", "view_committeemembership"],
}

APP_LABELS = ("people", "committees", "records", "core")


def create_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    for name, codenames in GROUP_PERMISSIONS.items():
        group, _ = Group.objects.get_or_create(name=name)
        if codenames == "__all__":
            permissions = Permission.objects.filter(
                content_type__app_label__in=APP_LABELS + ("auth",)
            )
        else:
            permissions = Permission.objects.filter(
                codename__in=codenames, content_type__app_label__in=APP_LABELS
            )
        group.permissions.set(permissions)


def delete_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=GROUP_PERMISSIONS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
        ("people", "0002_household_householdmember"),
        ("committees", "0004_committeemembership"),
        ("records", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [migrations.RunPython(create_groups, delete_groups)]
```

> Adjust the dependency migration names to match what `makemigrations` actually produced in Tasks 4, 7 and 8. Run `python manage.py showmigrations` to read the real names. The migration must depend on every app whose permissions it assigns, or those permissions will not exist yet when it runs.

- [ ] **Step 4: Run the migration and the tests**

Run:
```bash
python manage.py migrate
pytest tests/core/test_groups.py -v
```
Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add core tests/core
git commit -m "feat: create the five role groups with model permissions"
```

---

## Task 10: The encoding screen

**Files:**
- Modify: `people/admin.py`, `committees/admin.py`, `records/admin.py`
- Test: `tests/people/test_admin_encoding.py`

**Interfaces:**
- Consumes: every model, plus `core.numbering.next_member_no`.
- Produces:
  - `people.admin.PersonAdmin` with inlines `HouseholdMemberInline` and `CommitteeMembershipInline`.
  - `people.admin.PersonAdmin.assign_member_no` — admin action setting `member_no` on people who lack one.
  - `people.admin.find_possible_duplicates(person) -> QuerySet[Person]`.

- [ ] **Step 1: Write the failing test**

`tests/people/test_admin_encoding.py`:

```python
import datetime as dt

import pytest

from people.admin import find_possible_duplicates
from people.models import MembershipStatus, Person


@pytest.mark.django_db
def test_duplicates_are_found_by_name_and_birthdate():
    Person.objects.create(
        last_name="Malong", first_name="Shan", date_of_birth=dt.date(1995, 3, 2)
    )
    candidate = Person(
        last_name="malong", first_name="SHAN", date_of_birth=dt.date(1995, 3, 2)
    )
    assert find_possible_duplicates(candidate).count() == 1


@pytest.mark.django_db
def test_a_shared_name_with_a_different_birthdate_is_not_a_duplicate():
    Person.objects.create(
        last_name="Santos", first_name="Maria", date_of_birth=dt.date(1970, 1, 1)
    )
    candidate = Person(
        last_name="Santos", first_name="Maria", date_of_birth=dt.date(1994, 9, 9)
    )
    assert find_possible_duplicates(candidate).count() == 0


@pytest.mark.django_db
def test_a_person_does_not_match_themselves():
    person = Person.objects.create(
        last_name="Reyes", first_name="Manex", date_of_birth=dt.date(1988, 7, 7)
    )
    assert find_possible_duplicates(person).count() == 0


@pytest.mark.django_db
def test_member_numbers_are_assigned_in_sequence_and_never_overwritten():
    from people.admin import assign_member_numbers

    existing = Person.objects.create(
        last_name="Daclitan",
        first_name="Kathleen",
        membership_status=MembershipStatus.MEMBER,
        member_no="MEM-0099",
    )
    fresh = Person.objects.create(
        last_name="Bilango", first_name="Alpha",
        membership_status=MembershipStatus.MEMBER,
    )

    assign_member_numbers(Person.objects.all())

    existing.refresh_from_db()
    fresh.refresh_from_db()
    assert existing.member_no == "MEM-0099"
    assert fresh.member_no == "MEM-0001"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/people/test_admin_encoding.py -v`
Expected: FAIL with `ImportError: cannot import name 'find_possible_duplicates' from 'people.admin'`.

- [ ] **Step 3: Write the implementation**

`people/admin.py`:

```python
from django.contrib import admin, messages
from simple_history.admin import SimpleHistoryAdmin

from committees.models import CommitteeMembership
from core.numbering import next_member_no
from people.models import Household, HouseholdMember, MembershipStatus, Person
from records.models import AccessLog, FormScan


def find_possible_duplicates(person):
    """A soft warning, never a block. Two people genuinely can share a name."""
    matches = Person.objects.filter(
        last_name__iexact=person.last_name, first_name__iexact=person.first_name
    )
    if person.date_of_birth:
        matches = matches.filter(date_of_birth=person.date_of_birth)
    if person.pk:
        matches = matches.exclude(pk=person.pk)
    return matches


def assign_member_numbers(queryset):
    """Give a MEM- number to members who lack one. Never overwrites."""
    assigned = 0
    for person in queryset.filter(
        member_no__isnull=True, membership_status=MembershipStatus.MEMBER
    ):
        person.member_no = next_member_no()
        person.save(update_fields=["member_no"])
        assigned += 1
    return assigned


class HouseholdMemberInline(admin.TabularInline):
    model = HouseholdMember
    extra = 1
    autocomplete_fields = ("household",)


class CommitteeMembershipInline(admin.TabularInline):
    model = CommitteeMembership
    extra = 1
    fields = ("committee", "function", "role", "date_joined", "date_left")
    autocomplete_fields = ("committee", "function")


class FormScanInline(admin.TabularInline):
    model = FormScan
    extra = 0
    fields = ("form_type", "file", "notes")


@admin.register(Person)
class PersonAdmin(SimpleHistoryAdmin):
    list_display = (
        "full_name", "member_no", "membership_status", "mobile_number",
        "has_missing_data",
    )
    list_filter = ("membership_status", "has_missing_data", "consent_given")
    search_fields = ("last_name", "first_name", "nickname", "member_no", "mobile_number")
    readonly_fields = ("status_changed_at", "has_missing_data")
    autocomplete_fields = ("approved_by", "guardian")
    inlines = (HouseholdMemberInline, CommitteeMembershipInline, FormScanInline)
    actions = ("assign_member_no",)

    fieldsets = (
        ("Identity", {
            "fields": (
                "member_no", ("last_name", "first_name"), ("middle_name", "suffix"),
                "nickname",
            )
        }),
        ("Personal", {
            "fields": (
                ("date_of_birth", "place_of_birth"), ("gender", "civil_status"),
                "nationality",
            )
        }),
        ("Contact", {"fields": ("home_address", ("mobile_number", "email"))}),
        ("Emergency contact", {
            "fields": (
                "emergency_contact_name", "emergency_contact_relationship",
                "emergency_contact_number",
            )
        }),
        ("Guardian", {"fields": ("guardian", "guardian_relationship")}),
        ("Membership", {
            "fields": (
                "membership_status", "status_changed_at", "date_filed",
                "date_became_member", "approved_by", "date_of_death",
            )
        }),
        ("Privacy", {
            "fields": (
                "consent_given", "consent_date", "consent_version", "greeting_opt_out",
            )
        }),
        ("Follow-up", {"fields": ("has_missing_data", "follow_up_notes", "notes")}),
    )

    @admin.display(description="Name", ordering="last_name")
    def full_name(self, obj):
        return obj.full_name

    @admin.action(description="Assign member numbers")
    def assign_member_no(self, request, queryset):
        count = assign_member_numbers(queryset)
        self.message_user(request, f"Assigned {count} member number(s).")

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        duplicates = find_possible_duplicates(obj)
        if duplicates.exists():
            names = ", ".join(str(p) for p in duplicates[:3])
            self.message_user(
                request,
                f"This may duplicate an existing record: {names}. Saved anyway — "
                f"check and merge by hand if it is the same person.",
                level=messages.WARNING,
            )
        super().save_model(request, obj, form, change)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        person = self.get_object(request, object_id)
        if person is not None:
            AccessLog.record(
                user=request.user,
                person=person,
                ip=request.META.get("REMOTE_ADDR"),
            )
        return super().change_view(request, object_id, form_url, extra_context)


@admin.register(Household)
class HouseholdAdmin(admin.ModelAdmin):
    list_display = ("name", "date_of_marriage")
    search_fields = ("name",)
    inlines = (HouseholdMemberInline,)
```

`committees/admin.py`:

```python
from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from committees.models import (
    Appointment, Committee, CommitteeFunction, CommitteeMembership, Position,
)


class CommitteeFunctionInline(admin.TabularInline):
    model = CommitteeFunction
    extra = 0


@admin.register(Committee)
class CommitteeAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_self_selectable", "is_active")
    list_filter = ("is_self_selectable", "is_active")
    search_fields = ("name", "code")
    prepopulated_fields = {"code": ("name",)}
    inlines = (CommitteeFunctionInline,)


@admin.register(CommitteeFunction)
class CommitteeFunctionAdmin(admin.ModelAdmin):
    list_display = ("committee", "name")
    search_fields = ("name", "committee__name")


@admin.register(CommitteeMembership)
class CommitteeMembershipAdmin(SimpleHistoryAdmin):
    list_display = ("person", "committee", "role", "function", "date_joined", "date_left")
    list_filter = ("committee", "role")
    search_fields = ("person__last_name", "person__first_name")
    autocomplete_fields = ("person", "committee", "function")


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_unique_holder")
    search_fields = ("name",)


@admin.register(Appointment)
class AppointmentAdmin(SimpleHistoryAdmin):
    list_display = ("person", "position", "start_date", "end_date")
    list_filter = ("position",)
    search_fields = ("person__last_name", "person__first_name")
    autocomplete_fields = ("person",)
```

`records/admin.py`:

```python
from django.contrib import admin

from records.models import AccessLog, FormScan


@admin.register(FormScan)
class FormScanAdmin(admin.ModelAdmin):
    list_display = ("form_type", "person", "uploaded_by", "uploaded_at")
    list_filter = ("form_type",)
    autocomplete_fields = ("person",)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(AccessLog)
class AccessLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "user", "person", "report", "ip_address")
    list_filter = ("user",)
    readonly_fields = ("user", "person", "report", "timestamp", "ip_address")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/people -v`
Expected: PASS, 14 tests.

- [ ] **Step 5: Check the encoding screen by hand**

Run:
```bash
python manage.py createsuperuser
python manage.py runserver
```
Open `http://localhost:8000/admin/people/person/add/`. Confirm the household, committee and scan sections all appear as inline blocks on the one page, and that "Save and add another" is present.

- [ ] **Step 6: Commit**

```bash
git add people committees records tests/people
git commit -m "feat: add the encoding screen with inlines and duplicate warnings"
```

---

## Task 11: Row-level and field-level scoping for Chairpersons

**Files:**
- Modify: `people/admin.py`
- Test: `tests/people/test_admin_scoping.py`

**Interfaces:**
- Consumes: `core.groups`, `PersonAdmin`.
- Produces:
  - `people.admin.CHAIRPERSON_FIELDS = ("first_name", "last_name", "nickname", "mobile_number", "email")`.
  - `people.admin.is_chairperson_only(user) -> bool` — true when the user is in `Chairperson` and in none of `ICT`, `Secretariat`, `Board`.

- [ ] **Step 1: Write the failing test**

`tests/people/test_admin_scoping.py`:

```python
import datetime as dt

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Group, User
from django.test import RequestFactory

from committees.models import Committee, CommitteeMembership, CommitteeRole
from core import groups
from people.admin import CHAIRPERSON_FIELDS, PersonAdmin
from people.models import Person

TODAY = dt.date(2026, 8, 16)


@pytest.fixture
def chair_setup(db):
    chair_person = Person.objects.create(last_name="Malong", first_name="Shan")
    on_my_committee = Person.objects.create(last_name="Reyes", first_name="Manex")
    stranger = Person.objects.create(last_name="Santos", first_name="Rhea")

    ict = Committee.objects.get(code="ict")
    food = Committee.objects.get(code="food")
    CommitteeMembership.objects.create(
        committee=ict, person=chair_person, role=CommitteeRole.CHAIRPERSON,
        date_joined=TODAY,
    )
    CommitteeMembership.objects.create(
        committee=ict, person=on_my_committee, role=CommitteeRole.MEMBER,
        date_joined=TODAY,
    )
    CommitteeMembership.objects.create(
        committee=food, person=stranger, role=CommitteeRole.MEMBER, date_joined=TODAY,
    )

    user = User.objects.create_user("chair", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.CHAIRPERSON))
    chair_person.user = user
    chair_person.save()
    return user, on_my_committee, stranger


def request_for(user):
    request = RequestFactory().get("/admin/people/person/")
    request.user = user
    return request


@pytest.mark.django_db
def test_a_chairperson_sees_only_their_own_committee(chair_setup):
    user, mine, stranger = chair_setup
    admin = PersonAdmin(Person, AdminSite())
    visible = admin.get_queryset(request_for(user))
    assert mine in visible
    assert stranger not in visible


@pytest.mark.django_db
def test_a_chairperson_sees_only_five_fields(chair_setup):
    user, _, _ = chair_setup
    admin = PersonAdmin(Person, AdminSite())
    assert tuple(admin.get_fields(request_for(user))) == CHAIRPERSON_FIELDS


@pytest.mark.django_db
def test_a_chairperson_never_sees_an_address_or_birthdate(chair_setup):
    user, _, _ = chair_setup
    admin = PersonAdmin(Person, AdminSite())
    fields = set(admin.get_fields(request_for(user)))
    for hidden in ("home_address", "date_of_birth", "civil_status", "notes"):
        assert hidden not in fields


@pytest.mark.django_db
def test_the_secretariat_sees_everyone(db):
    Person.objects.create(last_name="Santos", first_name="Rhea")
    user = User.objects.create_user("sec", password="x", is_staff=True)
    user.groups.add(Group.objects.get(name=groups.SECRETARIAT))
    admin = PersonAdmin(Person, AdminSite())
    assert admin.get_queryset(request_for(user)).count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/people/test_admin_scoping.py -v`
Expected: FAIL with `ImportError: cannot import name 'CHAIRPERSON_FIELDS' from 'people.admin'`.

- [ ] **Step 3: Write the implementation**

Add to `people/admin.py`, above `PersonAdmin`:

```python
from committees.models import CommitteeRole
from core import groups

# Spec D12: enough to run a committee, and nothing more.
CHAIRPERSON_FIELDS = ("first_name", "last_name", "nickname", "mobile_number", "email")

WIDER_ACCESS_GROUPS = (groups.ICT, groups.SECRETARIAT, groups.BOARD)


def is_chairperson_only(user) -> bool:
    """True for a user who is a Chairperson and nothing more privileged."""
    if user.is_superuser:
        return False
    names = set(user.groups.values_list("name", flat=True))
    return groups.CHAIRPERSON in names and not names & set(WIDER_ACCESS_GROUPS)
```

Add these two methods to `PersonAdmin`:

```python
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if not is_chairperson_only(request.user):
            return queryset
        chaired = (
            CommitteeMembership.objects.active()
            .filter(
                person__user=request.user,
                role__in=(CommitteeRole.CHAIRPERSON, CommitteeRole.CO_CHAIR),
            )
            .values_list("committee_id", flat=True)
        )
        return queryset.filter(
            committee_memberships__committee_id__in=chaired
        ).distinct()

    def get_fields(self, request, obj=None):
        if is_chairperson_only(request.user):
            return CHAIRPERSON_FIELDS
        return super().get_fields(request, obj)

    def get_readonly_fields(self, request, obj=None):
        if is_chairperson_only(request.user):
            return CHAIRPERSON_FIELDS
        return super().get_readonly_fields(request, obj)

    def get_fieldsets(self, request, obj=None):
        if is_chairperson_only(request.user):
            return ((None, {"fields": CHAIRPERSON_FIELDS}),)
        return super().get_fieldsets(request, obj)

    def get_inlines(self, request, obj):
        if is_chairperson_only(request.user):
            return ()
        return super().get_inlines(request, obj)
```

> `get_fieldsets` and `get_inlines` matter as much as `get_fields`. `PersonAdmin` declares `fieldsets` and `inlines`, and Django reads those in preference to `get_fields()` when rendering. Overriding only `get_fields` would leave a chairperson looking at the full form.

- [ ] **Step 4: Run the tests**

Run: `pytest tests/people -v`
Expected: PASS, 18 tests.

- [ ] **Step 5: Commit**

```bash
git add people tests/people
git commit -m "feat: scope chairpersons to their own committee and five fields"
```

---

## Task 12: The contact retention job

**Files:**
- Create: `people/management/__init__.py`, `people/management/commands/__init__.py`, `people/management/commands/purge_stale_contacts.py`
- Test: `tests/people/test_retention.py`

**Interfaces:**
- Consumes: `Person.CONTACT_FIELDS`, `settings.CONTACT_RETENTION_DAYS`.
- Produces: management command `purge_stale_contacts`, accepting `--dry-run`, returning a count of people purged.

- [ ] **Step 1: Write the failing test**

`tests/people/test_retention.py`:

```python
import datetime as dt

import pytest
from django.core.management import call_command
from django.utils import timezone

from people.models import MembershipStatus, Person


def _stamp(person, days_ago):
    Person.objects.filter(pk=person.pk).update(
        status_changed_at=timezone.now() - dt.timedelta(days=days_ago)
    )
    person.refresh_from_db()
    return person


@pytest.fixture
def transferred_long_ago(db):
    person = Person.objects.create(
        last_name="Santos", first_name="Rhea",
        membership_status=MembershipStatus.TRANSFERRED,
        mobile_number="09171234567", email="rhea@example.com",
        home_address="Km 5, La Trinidad", emergency_contact_name="Juan",
        date_of_birth=dt.date(1980, 2, 2),
    )
    return _stamp(person, 800)


@pytest.mark.django_db
def test_contact_details_are_cleared_after_two_years(transferred_long_ago):
    call_command("purge_stale_contacts")
    transferred_long_ago.refresh_from_db()
    assert transferred_long_ago.mobile_number == ""
    assert transferred_long_ago.email == ""
    assert transferred_long_ago.home_address == ""
    assert transferred_long_ago.emergency_contact_name == ""


@pytest.mark.django_db
def test_identity_and_membership_history_survive(transferred_long_ago):
    """Spec section 5.1: the register is permanent; only contact data expires."""
    call_command("purge_stale_contacts")
    transferred_long_ago.refresh_from_db()
    assert transferred_long_ago.last_name == "Santos"
    assert transferred_long_ago.date_of_birth == dt.date(1980, 2, 2)
    assert Person.objects.filter(pk=transferred_long_ago.pk).exists()


@pytest.mark.django_db
def test_a_recent_transfer_is_left_alone(db):
    person = Person.objects.create(
        last_name="Reyes", first_name="Manex",
        membership_status=MembershipStatus.TRANSFERRED,
        mobile_number="09171234567",
    )
    _stamp(person, 100)
    call_command("purge_stale_contacts")
    person.refresh_from_db()
    assert person.mobile_number == "09171234567"


@pytest.mark.django_db
def test_active_members_are_never_purged(db):
    person = Person.objects.create(
        last_name="Malong", first_name="Shan",
        membership_status=MembershipStatus.MEMBER,
        mobile_number="09764215865",
    )
    _stamp(person, 5000)
    call_command("purge_stale_contacts")
    person.refresh_from_db()
    assert person.mobile_number == "09764215865"


@pytest.mark.django_db
def test_dry_run_changes_nothing(transferred_long_ago):
    call_command("purge_stale_contacts", "--dry-run")
    transferred_long_ago.refresh_from_db()
    assert transferred_long_ago.mobile_number == "09171234567"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/people/test_retention.py -v`
Expected: FAIL with `CommandError: Unknown command: 'purge_stale_contacts'`.

- [ ] **Step 3: Write the implementation**

`people/management/commands/purge_stale_contacts.py`:

```python
import datetime as dt

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from people.models import MembershipStatus, Person

PURGEABLE_STATUSES = (MembershipStatus.TRANSFERRED, MembershipStatus.DECEASED)


class Command(BaseCommand):
    help = (
        "Clear contact details for people who transferred or died more than "
        "CONTACT_RETENTION_DAYS ago. Identity and membership history are kept "
        "permanently; rows are never deleted. Spec section 5.1."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be cleared without changing anything.",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - dt.timedelta(days=settings.CONTACT_RETENTION_DAYS)
        stale = Person.objects.filter(
            membership_status__in=PURGEABLE_STATUSES, status_changed_at__lt=cutoff
        )

        purged = 0
        for person in stale:
            fields = [f for f in Person.CONTACT_FIELDS if getattr(person, f)]
            if not fields:
                continue
            purged += 1
            self.stdout.write(
                f"{person.full_name}: clearing {', '.join(fields)}"
            )
            if options["dry_run"]:
                continue
            for field in fields:
                setattr(person, field, "")
            person.save(update_fields=fields)

        verb = "Would clear" if options["dry_run"] else "Cleared"
        self.stdout.write(self.style.SUCCESS(f"{verb} contact details for {purged} person(s)."))
        return str(purged)
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/people/test_retention.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add people tests/people
git commit -m "feat: add the contact retention purge command"
```

---

## Task 13: Database backup and deployment configuration

**Files:**
- Create: `core/management/__init__.py`, `core/management/commands/__init__.py`, `core/management/commands/backup_database.py`
- Create: `Procfile`, `runtime.txt`, `docs/RESTORE.md`
- Modify: `aeci/settings.py`
- Test: `tests/core/test_backup.py`

**Interfaces:**
- Consumes: `settings.DATABASES`, the storage backend from Task 8.
- Produces: management command `backup_database`, accepting `--output-dir`, writing `aeci-YYYY-MM-DD-HHMM.sql.gz`.

- [ ] **Step 1: Write the failing test**

`tests/core/test_backup.py`:

```python
import subprocess

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_backup_writes_a_dump(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        # pg_dump writes to the path given after -f
        target = cmd[cmd.index("-f") + 1]
        with open(target, "wb") as handle:
            handle.write(b"-- fake dump")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    call_command("backup_database", "--output-dir", str(tmp_path))

    dumps = list(tmp_path.glob("aeci-*.sql"))
    assert len(dumps) == 1
    assert calls and calls[0][0] == "pg_dump"


@pytest.mark.django_db
def test_backup_fails_loudly_when_pg_dump_errors(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        call_command("backup_database", "--output-dir", str(tmp_path))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_backup.py -v`
Expected: FAIL with `CommandError: Unknown command: 'backup_database'`.

- [ ] **Step 3: Write the implementation**

`core/management/commands/backup_database.py`:

```python
import os
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = (
        "Dump the database with pg_dump. A church register cannot be "
        "reconstructed if lost. Spec section 8.4."
    )

    def add_arguments(self, parser):
        parser.add_argument("--output-dir", default="backups")

    def handle(self, *args, **options):
        output_dir = Path(options["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)

        stamp = timezone.localtime().strftime("%Y-%m-%d-%H%M")
        target = output_dir / f"aeci-{stamp}.sql"

        db = settings.DATABASES["default"]
        command = [
            "pg_dump",
            "--no-owner",
            "--no-privileges",
            "-h", db["HOST"] or "localhost",
            "-p", str(db["PORT"] or 5432),
            "-U", db["USER"],
            "-d", db["NAME"],
            "-f", str(target),
        ]

        # Inherit the real environment. Replacing it outright would strip PATH,
        # and pg_dump would not be found on the host.
        subprocess.run(
            command, check=True, env={**os.environ, "PGPASSWORD": db["PASSWORD"]}
        )

        self.stdout.write(self.style.SUCCESS(f"Wrote {target}"))
        return str(target)
```

`Procfile`:

```
web: gunicorn aeci.wsgi --log-file -
release: python manage.py migrate --noinput
```

`runtime.txt`:

```
python-3.12.4
```

`docs/RESTORE.md`:

```markdown
# Restoring the AECI registry from a backup

A backup nobody has restored from is a rumour. Run this drill once before
go-live and once a year afterwards.

## Restore into a scratch database

1. Create an empty database:
   `createdb -h localhost -U aeci aeci_restore_test`
2. Load the dump:
   `psql -h localhost -U aeci -d aeci_restore_test -f backups/aeci-YYYY-MM-DD-HHMM.sql`
3. Point a shell at it:
   `DATABASE_URL=postgres://aeci:aeci@localhost:5432/aeci_restore_test python manage.py shell`
4. Confirm the data survived:

```python
from people.models import Person
from committees.models import Committee
print(Person.objects.count(), Committee.objects.count())
```

5. Drop the scratch database: `dropdb -h localhost -U aeci aeci_restore_test`

## Record the drill

Write the date and the row counts in this file. If the counts do not match
production, stop and investigate before trusting the backup.

| Date of drill | Person rows | Committee rows | Who ran it |
| --- | --- | --- | --- |
| | | | |
```

Append the production security settings to `aeci/settings.py`:

```python
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    X_FRAME_OPTIONS = "DENY"
```

- [ ] **Step 4: Run the whole suite**

Run: `pytest -v`
Expected: PASS, 54 tests.

- [ ] **Step 5: Commit**

```bash
git add core Procfile runtime.txt docs/RESTORE.md aeci/settings.py tests/core
git commit -m "feat: add database backup, restore drill, and production security settings"
```

---

## Task 14: Seed the current officers and chairpersons

**Files:**
- Create: `committees/management/__init__.py`, `committees/management/commands/__init__.py`, `committees/management/commands/seed_officers.py`
- Test: `tests/committees/test_seed_officers.py`

**Interfaces:**
- Consumes: `Person`, `Committee`, `CommitteeMembership`, `Position`, `Appointment`.
- Produces: management command `seed_officers`, reading a CSV at `data/officers.csv` with columns `last_name,first_name,nickname,committee_code,role,start_date`.

> **Why a CSV and not a migration:** the Board document of 5 July 2026 records most chairpersons by first name or nickname only — MJ, Jemuel, JM, Fredalyn, Diego, Shan, Juliet. Those need resolving to real people by hand (spec §6.5). A CSV the ICT Committee edits is the honest shape for data that arrives incomplete.

- [ ] **Step 1: Write the failing test**

`tests/committees/test_seed_officers.py`:

```python
import pytest
from django.core.management import call_command

from committees.models import CommitteeMembership, CommitteeRole
from people.models import Person

CSV = """last_name,first_name,nickname,committee_code,role,start_date
Santos,Rhea,,sunshine,CHAIRPERSON,2026-07-05
Reyes,Manex,,general-services,CHAIRPERSON,2026-07-05
Malong,Shan Albert,Shan,ict,CHAIRPERSON,2026-07-05
"""


@pytest.fixture
def officers_csv(tmp_path):
    path = tmp_path / "officers.csv"
    path.write_text(CSV, encoding="utf-8")
    return path


@pytest.mark.django_db
def test_officers_are_created_with_their_committees(officers_csv):
    call_command("seed_officers", "--path", str(officers_csv))
    assert Person.objects.count() == 3
    shan = Person.objects.get(last_name="Malong")
    assert shan.nickname == "Shan"
    membership = CommitteeMembership.objects.get(person=shan)
    assert membership.committee.code == "ict"
    assert membership.role == CommitteeRole.CHAIRPERSON


@pytest.mark.django_db
def test_running_it_twice_creates_no_duplicates(officers_csv):
    call_command("seed_officers", "--path", str(officers_csv))
    call_command("seed_officers", "--path", str(officers_csv))
    assert Person.objects.count() == 3
    assert CommitteeMembership.objects.count() == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/committees/test_seed_officers.py -v`
Expected: FAIL with `CommandError: Unknown command: 'seed_officers'`.

- [ ] **Step 3: Write the implementation**

`committees/management/commands/seed_officers.py`:

```python
import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from committees.models import Committee, CommitteeMembership
from people.models import Person


class Command(BaseCommand):
    help = (
        "Create officer Person records and their committee roles from a CSV. "
        "Idempotent — safe to run repeatedly as names get resolved."
    )

    def add_arguments(self, parser):
        parser.add_argument("--path", default="data/officers.csv")

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.exists():
            raise CommandError(
                f"{path} not found. Create it with columns: "
                f"last_name,first_name,nickname,committee_code,role,start_date"
            )

        created_people = created_roles = 0
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                person, made = Person.objects.get_or_create(
                    last_name=row["last_name"].strip(),
                    first_name=row["first_name"].strip(),
                    defaults={"nickname": row.get("nickname", "").strip()},
                )
                created_people += int(made)

                try:
                    committee = Committee.objects.get(code=row["committee_code"].strip())
                except Committee.DoesNotExist:
                    raise CommandError(
                        f"No committee with code {row['committee_code']!r}. "
                        f"Check the spelling against `python manage.py shell`."
                    )

                _, made = CommitteeMembership.objects.get_or_create(
                    person=person,
                    committee=committee,
                    role=row["role"].strip(),
                    defaults={"date_joined": row["start_date"].strip()},
                )
                created_roles += int(made)

        self.stdout.write(
            self.style.SUCCESS(
                f"Created {created_people} person(s) and {created_roles} committee role(s)."
            )
        )
```

Create `data/officers.csv` with the header row and the chairpersons whose full names are known. Leave the nickname-only entries out until the ICT Committee resolves them.

```csv
last_name,first_name,nickname,committee_code,role,start_date
Santos,Rhea,,sunshine,CHAIRPERSON,2026-07-05
Reyes,Manex,,general-services,CHAIRPERSON,2026-07-05
Daclitan,Kathleen,,property-and-supplies,CHAIRPERSON,2026-07-05
Bilango,Alpha,,childrens-ministry,CHAIRPERSON,2026-07-05
Abiagar,Sonia,,food,CHAIRPERSON,2026-07-05
Malong,Shan Albert,Shan,ict,CHAIRPERSON,2026-07-05
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/committees -v`
Expected: PASS, 17 tests.

- [ ] **Step 5: Run the whole suite one last time**

Run: `pytest -v`
Expected: PASS, 56 tests.

- [ ] **Step 6: Commit**

```bash
git add committees data tests/committees
git commit -m "feat: seed current officers from an editable CSV"
```

---

## Verification checklist

Before calling Plan 1 complete, confirm each of these by running the command and reading the output — not by assuming.

- [ ] `pytest -v` passes with no failures and no skips
- [ ] `python manage.py makemigrations --check --dry-run` reports no missing migrations
- [ ] `python manage.py migrate` runs clean on an empty database
- [ ] `python manage.py check --deploy` reports no errors with `DEBUG=False`
- [ ] The encoding screen at `/admin/people/person/add/` shows household, committee and scan inlines on one page
- [ ] Logging in as a Chairperson-only account shows five fields and only their own committee's people
- [ ] `python manage.py purge_stale_contacts --dry-run` runs and reports zero on fresh data
- [ ] `python manage.py backup_database` produces a file, and the drill in `docs/RESTORE.md` restores it

## What Plan 2 covers

Spec §7, once real records exist to test against: celebrations (birthdays, anniversaries, the greeting generator), operational queues, committee staffing and recruitment reports, Board statistics, printable rosters and ID cards, the membership register and officer list for corporate filings, area grouping, and the report-level access rules of §7.7.
