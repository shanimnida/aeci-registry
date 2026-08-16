# AECI Information System — Phase A: People & Committees

**Design document**
Avdei Elohim Church Inc. (AECI)
Date: 2026-08-16
Author: ICT Committee (Shan Albert Malong) with Claude
Status: Approved design, pending implementation plan

---

## 1. Context

Avdei Elohim Church Inc. is a registered non-stock, non-profit religious corporation
in La Trinidad, Benguet, Philippines. It holds Sunday worship services in rented
premises at the College of Veterinary Medicine Social Hall, Benguet State University.

The church currently operates on a library of Word-template paper forms with
handwritten control numbers and signature-based approval chains:

| Form | Control No. | Routing |
| --- | --- | --- |
| Member Profiling | `MEM-` | Secretariat |
| Event / Activity Request | `EARF-` | Board of Directors |
| Fund Request | `FR-` | Board → Treasurer releases, records OR No. |
| Cash Disbursement Voucher | `CDV-` | Treasurer |
| Fund Reimbursement | `RB-` | Treasurer, 15-day deadline, budget-vs-actual variance |
| Minutes of Meeting | — | Secretary, quorum + action items |

These forms already encode referential integrity: an EARF references an FR number, and
an RB references an FR number and reconciles actual spend against the approved budget.
The system formalises what the paper already implies.

Member profiling data exists today only on paper. Collection is **ongoing**, not a
fixed backlog, so encoding is a continuous activity rather than a one-time migration.

### 1.1 Scope decomposition

The full information system comprises four independent subsystems. Each receives its
own design document, implementation plan, and release.

| | Subsystem | Contents | Status |
| --- | --- | --- | --- |
| **A** | People & Committees | Person records, households, committee rosters, officers | **This document** |
| **B** | Requests & Approvals | EARF / FR / RB / CDV with control numbers, routing, statuses | Future |
| **C** | Finance | Treasurer's ledger, OR numbers, budget vs actual, reports | Future |
| **D** | Governance records | Minutes, quorum, action-item tracking, official letters | Future |

Subsystem A is built first because B, C and D all reference its Person and Committee
records.

### 1.2 Out of scope for Phase A

- Member self-service logins (the schema accommodates them; none are issued)
- Any custom front-end — Phase A ships on the Django admin
- Attendance tracking, baptism and child dedication records, transfer letters,
  visitor cards. These forms do not yet exist at AECI. The schema leaves room; the
  features are deferred.
- OCR of scanned forms (see §6.4)
- Everything in subsystems B, C and D

---

## 2. Decisions

Decisions agreed during design, with the reasoning that produced them.

| # | Decision | Rationale |
| --- | --- | --- |
| D1 | **Django + PostgreSQL** | Built-in RBAC via groups and permissions; the admin is a usable day-one back office; boring and stable for a volunteer-maintained system |
| D2 | **Free-tier cloud now, paid later** | No vendor lock-in. Plain Postgres and a standard framework, so the move is a config change |
| D3 | **`Person` is the base record; `Member` is a status on it** | Children, visitors, non-attending spouses and deceased members all need rows. This is how Planning Center, Breeze, Rock RMS and Realm all model it |
| D4 | **Record now, login later** | `Person.user` is a nullable link. Member portals are opt-in and modestly adopted everywhere; requiring logins would stall the project on onboarding before the Secretariat gets any value |
| D5 | **Admin-first first release** | The Secretariat can encode real forms before any custom UI exists, and the schema gets proven against real data before screens are built on it |
| D6 | **Children are full `Person` records** | A child currently appears on two paper forms (the parent's profiling form and the Children's Ministry list). One row de-duplicates them. Growing up becomes a status change, not a re-entry |
| D7 | **12 committees, not 11** | The Board document lists Grievance and Reconciliation, absent from the profiling form. Deliberate — it is appointed, not self-selected |
| D8 | **Membership is decided by humans, recorded by the system** | An attendance threshold would make software adjudicate a covenant relationship, would penalise the sick, travelling and poor, and would constitute automated decision-making on sensitive data under RA 10173 |
| D9 | **`member_no` assigned at formal acceptance** | A `MEM-` number appears on official documents. Issuing one to a person never accepted leaves permanent gaps in the register |
| D10 | **Identity numbers carry no year; transaction numbers do** | `MEM-0001` is permanent. `EARF-2026-001` is filed and reported per year |
| D11 | **Scans go to S3-compatible object storage from day one** | Free-tier app hosting has an ephemeral filesystem; local uploads are lost on redeploy and idle spin-down |
| D12 | **Chairpersons see name, mobile and email only** | Enough to run a committee; withholds address, birthdate, civil status, family and emergency contact from twelve people who do not need them |
| D13 | **No OCR** | Handwriting recognition on Filipino names and handwritten dates takes longer to verify than to type, and a silently mis-read birthdate is worse than a blank one |

---

## 3. Data model

Eleven concrete models plus one abstract base, across four Django apps.

### 3.1 `core`

**`TimeStampedModel`** (abstract)

| Field | Type | Notes |
| --- | --- | --- |
| `created_at` | DateTimeField | auto_now_add |
| `updated_at` | DateTimeField | auto_now |
| `created_by` | FK → User | null, on_delete=PROTECT |
| `updated_by` | FK → User | null, on_delete=PROTECT |

**`ControlNumberSequence`** — atomic allocation of control numbers.

| Field | Type | Notes |
| --- | --- | --- |
| `prefix` | CharField(8) | `MEM`, `EARF`, `FR`, `RB`, `CDV` |
| `year` | IntegerField | null for year-less sequences such as `MEM` |
| `last_value` | IntegerField | default 0 |

Unique together: `(prefix, year)`. Allocation uses `select_for_update()` inside a
transaction so two Secretariat users encoding simultaneously cannot collide.

Formats: `MEM-0001` (4 digits, no year, never resets). `EARF-2026-001`,
`FR-2026-001`, `RB-2026-001`, `CDV-2026-001` (3 digits, resets annually) — Phase B.

### 3.2 `people`

**`Person`** — the core record.

| Field | Type | Notes |
| --- | --- | --- |
| `member_no` | CharField(12) | unique, **null** — only members hold one |
| `last_name` | CharField(100) | **required** |
| `first_name` | CharField(100) | **required** |
| `middle_name` | CharField(100) | blank |
| `suffix` | CharField(20) | blank |
| `date_of_birth` | DateField | null |
| `place_of_birth` | CharField(200) | blank |
| `gender` | CharField, choices | `MALE`, `FEMALE`; blank permitted |
| `civil_status` | CharField, choices | `SINGLE`, `MARRIED`, `WIDOWED`, `SEPARATED`, `ANNULLED`; blank permitted |
| `nationality` | CharField(60) | default `Filipino` |
| `home_address` | TextField | blank |
| `mobile_number` | CharField(20) | blank |
| `email` | EmailField | blank |
| `membership_status` | CharField, choices | See §3.2.1; default `VISITOR` |
| `status_changed_at` | DateTimeField | null; drives the retention job |
| `date_filed` | DateField | null; the date written on the paper form |
| `date_became_member` | DateField | null |
| `approved_by` | FK → Person | null; who accepted this person into membership |
| `guardian` | FK → self | null; for children whose guardian may sit outside the household |
| `guardian_relationship` | CharField(60) | blank |
| `emergency_contact_name` | CharField(200) | blank |
| `emergency_contact_relationship` | CharField(60) | blank |
| `emergency_contact_number` | CharField(20) | blank |
| `consent_given` | BooleanField | default False |
| `consent_date` | DateField | null |
| `consent_version` | CharField(20) | blank |
| `has_missing_data` | BooleanField | default False; maintained on save, see §6.3 |
| `follow_up_notes` | TextField | blank |
| `notes` | TextField | blank |
| `user` | OneToOne → User | null, blank — the login-later hook (D4) |

Every field except `last_name` and `first_name` is optional. Paper forms arrive with
blanks, and a system that refuses incomplete records is a system the Secretariat
abandons.

#### 3.2.1 `membership_status`

`VISITOR` · `CHILD` · `MEMBER` · `INACTIVE` · `TRANSFERRED` · `DECEASED`

`CHILD` means a minor under the family's membership who is not yet a full member. It
is **not** derived from date of birth: a nineteen-year-old who has never formally
joined is not automatically a member.

Records are never deleted. Status changes instead. Any status change stamps
`status_changed_at`.

**`Household`**

| Field | Type | Notes |
| --- | --- | --- |
| `name` | CharField(200) | e.g. "Malong Family" |
| `address` | TextField | blank |
| `date_of_marriage` | DateField | null — belongs to the household, not a person |

**`HouseholdMember`**

| Field | Type | Notes |
| --- | --- | --- |
| `household` | FK → Household | |
| `person` | FK → Person | |
| `role` | CharField, choices | `HEAD`, `SPOUSE`, `CHILD`, `OTHER` |

Unique together: `(household, person)`. The spouse row and the five children rows of
the paper form both collapse into this one table.

### 3.3 `committees`

**`Committee`**

| Field | Type | Notes |
| --- | --- | --- |
| `name` | CharField(120) | |
| `code` | SlugField | unique |
| `description` | TextField | blank |
| `is_self_selectable` | BooleanField | default True; **False for Grievance and Reconciliation** (D7) |
| `is_active` | BooleanField | default True |

Seeded with twelve committees. Only the eleven with `is_self_selectable=True` appear
as checkboxes on the member profiling form.

| Committee | Self-selectable |
| --- | --- |
| Sunshine | yes |
| General Services | yes |
| Property and Supplies | yes |
| Music and Arts | yes |
| Children's Ministry | yes |
| Youth | yes |
| Events | yes |
| Finance and Resource Accessing | yes |
| **Grievance and Reconciliation** | **no** |
| ICT | yes |
| Secretariat | yes |
| Food | yes |

**`CommitteeFunction`** — the sub-teams the Board document records.

| Field | Type | Notes |
| --- | --- | --- |
| `committee` | FK → Committee | |
| `name` | CharField(120) | |
| `description` | TextField | blank |

Unique together: `(committee, name)`. Known functions: Sunshine → Ushering & Marshall,
Transport, Benevolence. General Services → Construction and Repair, Maintenance,
Building Tools. Property and Supplies → Musical Instruments, Supplies. Music and Arts
→ Sounds, Song Leading, Instrument. Committees without sub-functions simply have no
rows, so the layer is optional.

**`CommitteeMembership`**

| Field | Type | Notes |
| --- | --- | --- |
| `committee` | FK → Committee | |
| `person` | FK → Person | |
| `function` | FK → CommitteeFunction | null |
| `role` | CharField, choices | `CHAIRPERSON`, `CO_CHAIR`, `MEMBER`, `OVERSIGHT` |
| `date_joined` | DateField | |
| `date_left` | DateField | null — active while null |

Validation rules, enforced in `clean()` so they surface as ordinary admin form errors:

1. **Max two self-selected committees.** A person may hold at most two *active*
   memberships with `role=MEMBER` on committees where `is_self_selectable=True`.
   Appointed roles (`CHAIRPERSON`, `CO_CHAIR`, `OVERSIGHT`) are exempt — otherwise
   chairing Grievance would consume one of Diego's two picks.
2. **One active chairperson per committee.**
3. `function`, if set, must belong to `committee`.
4. `OVERSIGHT` requires an active Board `Appointment` for that person.

**`Position`** — church-level offices, distinct from committees.

| Field | Type | Notes |
| --- | --- | --- |
| `name` | CharField(120) | Pastor, Chairperson of the Board, Treasurer, Secretary, Board Member |
| `code` | SlugField | unique |
| `is_unique_holder` | BooleanField | True for Treasurer, Secretary, Pastor; False for Board Member |

**`Appointment`**

| Field | Type | Notes |
| --- | --- | --- |
| `person` | FK → Person | |
| `position` | FK → Position | |
| `start_date` | DateField | |
| `end_date` | DateField | null — active while null |

Validation: where `position.is_unique_holder`, no two appointments may overlap in
time. Keeping appointment history means Phase B can answer "who was Treasurer when
this FR was released", not merely "who is Treasurer now".

### 3.4 `records`

**`FormScan`**

| Field | Type | Notes |
| --- | --- | --- |
| `person` | FK → Person | **null** — a scan may be uploaded before encoding |
| `form_type` | CharField, choices | `MEMBER_PROFILING`, `EARF`, `FR`, `RB`, `CDV`, `MOM`, `OTHER` |
| `file` | FileField | S3-compatible object storage (D11) |
| `uploaded_by` | FK → User | |
| `uploaded_at` | DateTimeField | auto_now_add |
| `notes` | TextField | blank |

**`AccessLog`** — who *viewed* which person's record.

| Field | Type | Notes |
| --- | --- | --- |
| `user` | FK → User | |
| `person` | FK → Person | |
| `timestamp` | DateTimeField | auto_now_add |
| `ip_address` | GenericIPAddressField | null |

Change history is separate, provided by `django-simple-history` on `Person`,
`CommitteeMembership` and `Appointment`. Simple-history records who changed what; it
does not record who looked. Under RA 10173 the view log is the one that answers a
member's complaint that their address circulated.

---

## 4. Roles and permissions

Five Django groups. A sixth conceptual role, Member, exists in the design and receives
no login in Phase A.

| Capability | ICT | Secretariat | Treasurer | Board / Pastor | Chairperson |
| --- | :--: | :--: | :--: | :--: | :--: |
| Create / edit Person records | ✅ | ✅ | — | — | — |
| View full Person record | ✅ | ✅ | — | ✅ | ⚠️ |
| Assign `MEM-` number | ✅ | ✅ | — | — | — |
| Set status → `MEMBER` | ✅ | ✅ \* | — | ✅ | — |
| Manage households & children | ✅ | ✅ | — | — | — |
| Edit committee rosters | ✅ | ✅ | — | ✅ | own only |
| Appoint officers / chairpersons | ✅ | — | — | ✅ | — |
| Upload form scans | ✅ | ✅ | — | — | — |
| View own committee roster | ✅ | ✅ | — | oversight only | ✅ |
| Create user accounts | ✅ | — | — | — | — |
| Read audit log | ✅ | — | — | ✅ | — |
| Hard-delete anything | ✅ | — | — | — | — |

\* The Secretariat *records* an acceptance, supplying `approved_by`; it does not
originate one. The required approver field is how D8 is enforced in code.

**The Treasurer group holds no Phase A capabilities.** Every cell in its column is
empty by design: the Treasurer's work — fund release, OR numbers, the ledger — lives
in subsystems B and C. The group is created now so that accounts and group membership
are in place before those subsystems land, and so the separation of duties above is
stated completely. If it proves confusing to have a login that can see nothing, defer
creating Treasurer accounts until Phase B; the group definition costs nothing either
way.

⚠️ A Chairperson sees **name, mobile number and email** for members of their own
committee. Home address, birthdate, civil status, household, children and emergency
contact are hidden, as is every person not on their roster (D12).

**Separation of duties.** The Secretariat manages records but cannot create logins;
ICT creates logins but cannot set membership status. Neither role can unilaterally
manufacture a member.

**Deletion.** Nobody deletes people; status changes instead. Hard delete is ICT-only,
logged, and exists solely for genuine mistakes such as a duplicated row.

### 4.1 Implementation layers

| Layer | Mechanism |
| --- | --- |
| Model-level | Django groups and permissions, built in |
| Row-level ("only my committee") | `get_queryset()` overrides on the relevant `ModelAdmin` |
| Field-level (the ⚠️ above) | `get_fields()` / `get_readonly_fields()` overrides |

No third-party permissions library is required.

---

## 5. Privacy and compliance

The profiling form collects civil status, date of birth, home address, children's
names and birthdates, and religious membership. Under the **Data Privacy Act of 2012
(RA 10173)**, marital status, age and religious affiliation are expressly *sensitive
personal information*, and the children's records are minors' data.

The current paper form carries a truthfulness certification but **no data privacy
consent clause**. This is being corrected: consent will be signed by members at the
next Sunday service. `Person.consent_given`, `consent_date` and `consent_version`
record it, so the church can demonstrate consent per person and per form version.

### 5.1 Retention policy

To be ratified by the Board so that it is church policy rather than an ICT decision.

| Data | Retention |
| --- | --- |
| Identity and membership history — name, birthdate, membership event dates | **Indefinite.** This is the church register; churches have kept membership rolls permanently, and the purpose is ongoing |
| Contact and sensitive extras — mobile, email, home address, emergency contact | **Purged two years** after status becomes `TRANSFERRED` or `DECEASED`; the purpose for holding them has ended |
| Rows | **Never hard-deleted.** Fields are blanked; the person remains |

Implemented as the `purge_stale_contacts` management command, run on a schedule,
keyed on `status_changed_at`, writing each purge to the audit log.

### 5.2 Other measures

- HTTPS enforced; secure cookie and HSTS settings
- Sensitive fields excluded from admin list views and search results
- Every view of a Person detail page written to `AccessLog`
- Small account surface — no member logins means roughly 15–25 accounts total
- Paper forms retained after encoding as both backup and signed consent evidence

---

## 6. The encoding workflow

Phase A's entire user-facing purpose. The Secretariat works from a physical stack of
forms, which is still growing as collection continues.

### 6.1 The loop

```
photograph form → upload as FormScan → create Person → household + children
  → committee picks → assign MEM- → mark encoded → next
```

The admin is tuned for this one flow: a single page with household members and
committee memberships as **inline sections** rather than separate screens, and "Save
and add another" as the default action. Encoding a form must never require navigating
away and back.

### 6.2 Assistance the system provides

| Feature | Behaviour |
| --- | --- |
| `MEM-` assignment | Auto-suggests the next free number, **overridable** — many paper forms already carry a handwritten one |
| Duplicate detection | Soft warning on similar name plus birthdate. Never a hard block; two people genuinely can share a name |
| Max-two committees | Model-level validation surfacing as a normal form error |
| Child already present | Where a child was captured from a sibling's form, search offers the existing `Person` rather than creating a second |
| Search | By name, `MEM-`, mobile number, or committee |

### 6.3 Incomplete forms

Blanks are encoded as blanks. On save, `has_missing_data` is set when any expected
field is empty, and a **"Needs follow-up"** admin view lists who to chase and for
what, with `follow_up_notes` for context. The Secretariat works the stack at speed
now and cleans up over subsequent Sundays.

The field is stored rather than computed because a Python property cannot be filtered
in the database, and the follow-up queue is a filtered list view.

### 6.4 Why no OCR

Handwriting recognition on Filipino names and handwritten dates yields output that
takes longer to verify than to type, and a silently mis-read birthdate is worse than a
blank one. Scans are stored as evidence and for reference, never parsed.

### 6.5 Known data-quality issue

The Board and Committee document of 5 July 2026 records most chairpersons by first
name only — MJ, Jemuel, JM, Fredalyn, Diego, Shan, Juliet. Linking these to `Person`
rows requires manual resolution by the ICT Committee at seeding time. This is an
encoding task, not a design problem, but it will surface on day one.

---

## 7. Architecture and deployment

### 7.1 Project layout

Small apps with clear seams, so later subsystems bolt on rather than cut in.

| App | Owns | Phase |
| --- | --- | --- |
| `core` | Abstract base model, audit configuration, control-number allocation | A |
| `people` | Person, Household, HouseholdMember, guardian links | A |
| `committees` | Committee, CommitteeFunction, CommitteeMembership, Position, Appointment | A |
| `records` | FormScan, AccessLog | A |
| `requests` | EARF, FR, RB, CDV and approval routing | B |
| `finance` | Ledger, OR numbers, budget vs actual | C |
| `governance` | Minutes, quorum, action items | D |

### 7.2 Stack

- Python 3.12+, Django 5.x
- PostgreSQL
- `django-simple-history` — change tracking
- `django-storages` + `boto3` — S3-compatible scan storage
- `Pillow` — image handling
- `django-environ` — settings from environment
- `gunicorn`, `whitenoise`
- `pytest`, `pytest-django`

Phase A is **admin-only**: no Tailwind, no HTMX, no custom templates. Those arrive in
Phase B, when committee heads need mobile screens. Building a front-end now would
serve users who do not yet exist.

### 7.3 Deployment

All free tier, all replaceable, no lock-in (D2). Specific providers to be confirmed
against current free-tier terms at build time.

| Component | Choice |
| --- | --- |
| Application | Render or Fly.io |
| Database | Neon or Supabase Postgres |
| Scan storage | Cloudflare R2 or Backblaze B2 |
| Local development | Postgres via docker-compose, matching production |

**The ephemeral filesystem catch.** Free-tier application hosting resets its disk on
every redeploy and on idle spin-down. Scans stored as ordinary uploaded files are
lost. Object storage from day one is therefore not an optimisation but a correctness
requirement (D11), and Django's storage backend keeps it a settings change when the
church moves to paid hosting.

### 7.4 Backups

Higher stakes here than anywhere else in the system: a lost church register cannot be
reconstructed.

- Nightly `pg_dump` to object storage, 30-day retention
- An admin export action so the Secretariat can pull a spreadsheet on demand
- A **written and tested** restore procedure. A backup nobody has restored from is a
  rumour
- Paper forms retained after encoding

---

## 8. Testing

The permission matrix of §4 *is* the test suite — every role against every capability,
parametrised.

| Area | Cases |
| --- | --- |
| Permissions | Each of five groups × each capability, positive and negative |
| Row-level scoping | A chairperson sees own roster only; sees no other committee |
| Field-level scoping | Address, birthdate, civil status, family absent from chairperson views |
| Committee rules | Max-two cap; appointed roles exempt; one chairperson per committee; function belongs to committee |
| Control numbers | `MEM-` uniqueness, sequence allocation, manual override, concurrent allocation under `select_for_update` |
| Status transitions | `status_changed_at` stamped; `approved_by` required for `MEMBER` |
| Appointments | Unique-holder positions cannot overlap |
| Retention | `purge_stale_contacts` blanks the right fields, spares identity data, respects the two-year boundary, logs |
| Audit | Person views written to `AccessLog`; edits captured by simple-history |
| Encoding | Incomplete records save; `has_missing_data` set correctly; follow-up queue filters |

---

## 9. Open items

Tracked, not blocking implementation.

| # | Item | Owner | Blocks |
| --- | --- | --- | --- |
| 1 | Photographs of filled paper profiling forms → `data/scanned-forms/` | ICT | Encoding, not build |
| 2 | Existing `MEM-` register — is one kept, highest number assigned, are numbers already handwritten | ICT | Seeding |
| 3 | Full legal names for chairpersons recorded by first name only (§6.5) | ICT | Seeding |
| 4 | Data privacy consent clause signed at next Sunday service | Church | Go-live |
| 5 | Board ratification of the retention policy (§5.1) | Board | Go-live |
| 6 | Filled examples of FR, RB, CDV and a real MoM | ICT | Phase B design |
| 7 | Attendance, baptism and dedication, transfer letter, visitor card forms — do not yet exist | Church | Future phases |

---

## 10. Next step

Produce the implementation plan for Phase A from this document.
