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
- Any visitor-facing feature. Visitors are not given the profiling form, so no visitor
  data exists to work with (D14).
- Member photographs. Useful for recognising faces, but photographs of minors need
  their own consent conversation, which is not a Phase A fight.
- Duplicate *merging*. Phase A finds duplicates (§7.2); merging waits until enough
  have accumulated to show what merging should actually do.
- SMS notification of any kind (D17).
- OCR of scanned forms (see §6.4)
- **Skills and talents inventory.** Proposed and declined for Phase A. Worth
  revisiting: the ICT Committee's own event proposal states that identifying members
  with particular skills is a goal.
- **Calendar feed (`.ics`) of celebrations.** Proposed and declined.
- **Pastoral care notes.** Proposed and declined. Would raise the sensitivity of the
  whole database and needs the Board's explicit agreement first.
- **Self-service verification kiosk.** Proposed and declined, and recommended against:
  authenticating on `member_no` plus date of birth means anyone knowing two facts about
  a person can read their record.
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
| D14 | **Default status is `RELATED`; `VISITOR` is unused for now** | AECI does not give the profiling form to visitors. Every record entering the system is a member, their child, or someone named on their form. Defaulting to `VISITOR` would assert attendance nobody recorded |
| D15 | **`approved_by` is required on transition to `MEMBER`, not on creation as `MEMBER`** | Requiring it on creation would make the paper backlog un-encodable, since nobody knows which meeting accepted a long-standing member. Scoping it to transitions keeps encoding fast and future decisions attributable |
| D16 | **Phase A includes a read-only reporting layer** (§7) | Requested by the Church Secretary, and every report is a query over data the schema already holds. No new collection, and the marginal cost over the encoding tool is small |
| D17 | **Greeting lists show month and day only, and there is no SMS** | Birth year reveals age to twelve chairpersons who have no need for it. SMS costs money per message in the Philippines and email coverage on the paper forms is patchy; an on-screen list with an optional weekly email digest covers the need |
| D18 | **The paper form is revised to v2 before the next collection** | Consent is signed on 23 August 2026. Whatever is printed that day governs the next batch of members, so the consent clause, the nickname field and the Grievance note had to land first. The footer carries "v2 (August 2026)", which is what `consent_version` stores |

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
| `nickname` | CharField(60) | blank; the name a person actually goes by. Used in greetings, and needed because the Board document records several officers only as "MJ", "JM" |
| `date_of_birth` | DateField | null |
| `place_of_birth` | CharField(200) | blank |
| `gender` | CharField, choices | `MALE`, `FEMALE`; blank permitted |
| `civil_status` | CharField, choices | `SINGLE`, `MARRIED`, `WIDOWED`, `SEPARATED`, `ANNULLED`; blank permitted |
| `nationality` | CharField(60) | default `Filipino` |
| `home_address` | TextField | blank |
| `mobile_number` | CharField(20) | blank |
| `email` | EmailField | blank |
| `membership_status` | CharField, choices | See §3.2.1; default `RELATED` |
| `status_changed_at` | DateTimeField | null; drives the retention job |
| `date_of_death` | DateField | null; removes the person from all greeting lists (§7.1) |
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
| `greeting_opt_out` | BooleanField | default False; suppresses this person from birthday and anniversary lists |
| `has_missing_data` | BooleanField | default False; maintained on save, see §6.3 |
| `follow_up_notes` | TextField | blank |
| `notes` | TextField | blank |
| `user` | OneToOne → User | null, blank — the login-later hook (D4) |

Every field except `last_name` and `first_name` is optional. Paper forms arrive with
blanks, and a system that refuses incomplete records is a system the Secretariat
abandons.

#### 3.2.1 `membership_status`

`MEMBER` · `CHILD` · `RELATED` · `VISITOR` · `INACTIVE` · `TRANSFERRED` · `DECEASED`

| Value | Meaning |
| --- | --- |
| `MEMBER` | Formally accepted into membership. Holds a `member_no` |
| `CHILD` | A minor under the family's membership, not yet a full member |
| `RELATED` | Exists in the database only because they are connected to a member — a spouse who does not attend, a guardian outside the household. Not a visitor, not a member |
| `VISITOR` | Attends but has not joined. **Currently unused**: AECI does not give the profiling form to visitors, so no visitor records exist yet. Retained for when visitor cards are introduced |
| `INACTIVE` | A member who has stopped participating |
| `TRANSFERRED` | Moved to another congregation |
| `DECEASED` | See also `date_of_death` |

`CHILD` is **not** derived from date of birth: a nineteen-year-old who has never
formally joined is not automatically a member.

**The default is `RELATED`, not `VISITOR`.** A bare `Person` row created incidentally
— a guardian named on a child's record, a spouse named on a profiling form — is a
related person. Defaulting such rows to `VISITOR` would assert an attendance fact
nobody recorded, and would pollute visitor reporting the moment visitor cards arrive.

Records are never deleted. Status changes instead. Any status change stamps
`status_changed_at`.

#### 3.2.2 When `approved_by` is required

D8 requires a human approver for membership. Applied naively this would make the
paper backlog un-encodable, because nobody knows which Board meeting accepted a member
who joined years ago. The rule is therefore scoped to transitions:

- **Creating** a `Person` already at status `MEMBER` does **not** require
  `approved_by`. This is the Secretariat recording an acceptance that happened before
  the system existed.
- **Changing** an existing `Person` to `MEMBER` from any other status **does** require
  `approved_by`. This is an acceptance happening now, and the system must record who
  made it.

Encoding the backlog stays fast; every future membership decision stays attributable.

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

Validation rules, in `clean()`. Rules 2–4 are hard refusals, surfacing as ordinary
admin form errors. Rule 1 is a soft warning only — see the amendment below.

1. **Max two self-selected committees — soft, amended 2026-08-17.** The profiling
   form prints "select up to TWO (2) committees you wish to be part of," and AEGIS
   counts a person's active memberships with `role=MEMBER` on committees where
   `is_self_selectable=True` against that limit. Appointed roles (`CHAIRPERSON`,
   `CO_CHAIR`, `OVERSIGHT`) are exempt — otherwise chairing Grievance would consume
   one of Diego's two picks. **This used to be a hard refusal — a third such
   membership could not be saved.** It no longer is. Of the first thirty profiling
   forms collected, four (`IMG_5874`, `IMG_5885`, `IMG_5893`, `IMG_5894`) ticked
   three or four committees, and the church accepted those forms as filed. The
   two-committee line is a policy printed on a form, not a structural fact about
   the data the way rule 2 below is — software refusing to save what the church
   itself already accepted was the software being wrong, not the form. AEGIS still
   tells whoever is recording the membership that the count is over two
   (`CommitteeMembership.self_selected_overflow_count`, shown as a warning in the
   admin and on the import review screen), but it never blocks the save.
2. **One active chairperson per committee — hard.** Two people simultaneously
   chairing the same committee is structurally incoherent, not merely against
   policy, so this still refuses.
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

**Separation of duties, stated honestly.** The Secretariat manages records but cannot create
logins. The Board accepts members but cannot administer accounts. Neither of those two roles can
unilaterally manufacture a member, and that separation *is* enforced by permissions.

**ICT is exempt, and the earlier wording of this section was wrong to imply otherwise.** ICT holds
the full permission set — it is the system administrator role — so it can technically do anything,
including creating a login and granting membership. An earlier draft claimed ICT "cannot set
membership status" while the matrix above simultaneously granted it, which was a contradiction
rather than a rule. There is no way to give one role the ability to repair the system and also
withhold the ability to misuse it.

What constrains ICT is therefore not permission but evidence: every change is captured by
`django-simple-history`, every view of a person's record is written to `AccessLog`, and both are
readable by the Board. The check on the administrator is that the administrator's actions are
visible to someone else, not that they are blocked. A church deploying this should understand that
whoever holds the ICT account is trusted, and should choose that person accordingly.

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

**The purge must reach the change history, not only the live record.** `Person` carries
`django-simple-history`, so every edit writes a complete copy of the contact fields to the
historical table, which the admin renders on its history page. A purge that blanks only the
current row leaves every earlier value readable indefinitely and delivers none of the policy
above. The command therefore blanks all contact fields across every stored revision as well, and
must use the full contact field list rather than only the fields currently populated on the live
row, because history can hold a value the live record has since lost.

**Household addresses follow the household, not the person.** `Household.address` holds the same
home address as its members. It is cleared only once *every* member of that household is
purgeable and past the window — one person transferring must not erase an address the rest of
the family still needs.

Implemented as the `purge_stale_contacts` management command, run on a schedule, keyed on
`status_changed_at`. Each purge writes a `PurgeRecord` naming the person, the fields cleared and
the number of revisions scrubbed. That record is the only durable evidence a purge occurred once
the history is scrubbed, so it is readonly and undeletable through the admin, and the person's
identity is snapshotted as text so it survives independently of the person row.

**Known residuals, accepted:** free-text `notes` and `follow_up_notes` are not scrubbed and can
accumulate phone numbers written by hand — a data-entry habit for the Secretariat to avoid,
rather than something the command can safely guess at. A linked `User.email` also survives, which
is moot while Phase A issues no member logins but must be revisited if that changes.

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
| Max-two committees | Soft warning past two (§3.3, amended 2026-08-17). Never a hard block; the printed cap is church policy, and the church has already accepted forms that ticked more |
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

## 7. Reporting and dashboards

A read-only layer over the schema of §3. Requested by the Church Secretary, and
extended to cover gaps visible in the Board and Committee document of 5 July 2026.
Nothing here requires collecting data the church does not already gather (D16).

### 7.1 Celebrations

The Secretary's original request. The natural owner is the **Sunshine Committee**,
which handles greetings and benevolence, so its chairperson sees this alongside the
Secretariat.

| Report | Source |
| --- | --- |
| Upcoming birthdays | `Person.date_of_birth` |
| Wedding anniversaries | `Household.date_of_marriage` |
| Membership anniversaries | `Person.date_became_member` |
| Committee service anniversaries | `CommitteeMembership.date_joined` |

**Exclusions, applied to every celebration list:** `membership_status` of `DECEASED`
or `TRANSFERRED`, any person with `date_of_death` set, and any person with
`greeting_opt_out`. A deceased member appearing on a birthday list is the kind of
error that is embarrassing once and preventable permanently.

**Display:** month and day only, never the year (D17).

**Greeting text generator.** Composes a ready message using the person's `nickname`,
for pasting into the church Facebook page or Messenger. AECI's congregation is reached
primarily through that page, so this converts a list of dates into a task that takes
seconds.

**Delivery:** on-screen list, plus an optional weekly email digest to the Secretariat
and the Sunshine chairperson. No SMS (D17).

**Interaction with data quality:** many paper forms carry no birthdate. Those people
cannot appear here, which makes the celebrations page a standing, visible argument for
working the follow-up queue (§6.3).

### 7.2 Operational queues

Work the Secretariat currently tracks from memory.

| Queue | Rule |
| --- | --- |
| Needs follow-up | `has_missing_data` is true |
| Consent not yet signed | `consent_given` is false |
| New members to welcome | `date_became_member` within the last 60 days |
| Officer terms expiring | `Appointment.end_date` within the next 90 days |
| Children ageing into Youth | Turning 13 within 90 days |
| Children ageing out of `CHILD` | Turning 18 within 90 days — prompts a human decision, never an automatic status change (D8) |
| Possible duplicates | Similar name plus birthdate. Finder only; merging is out of scope |
| Recent changes | From `django-simple-history`, so the Secretariat lead can catch encoding mistakes early |

### 7.3 Committee management

Serves the "Finalize Committee Members and Functions" and "Oversight Board per
Committee" action items in the Board document, which currently has visible blanks —
Sunshine records no Co-Chair or Core Members, General Services no Oversight.

| Report | Contents |
| --- | --- |
| Staffing gaps | Committees lacking an active chairperson, a co-chair, or an assigned Board `OVERSIGHT` appointment |
| Recruitment availability | Members at the two-committee cap, versus members serving on none |
| Contact export | Name, mobile and email for one committee, in a form that can be pasted into a group chat. Chairperson-scoped, so no one can export the whole congregation |

### 7.4 Board statistics

For church planning sessions such as the "Presentation and Discussion of Church Plans"
scheduled in the Board document.

Headcount by `membership_status`; committee sizes and vacancies; age bands (children,
youth, young adult, adult, senior); gender split; new members per month; and overall
data completeness as a percentage.

### 7.5 Printable and copyable output

For people who will not log in.

| Output | Use |
| --- | --- |
| Committee roster | Posting and handouts |
| Children's Ministry roster | Includes guardian names and numbers, for pickup and safety |
| Emergency contact sheet | Events, trips, outings |
| Pre-filled profiling form | Prints a person's record in the layout of the paper form, so they can verify it and sign. Closes the loop on both accuracy and consent |
| Church ID cards | Printable cards carrying name, nickname and `member_no`. Groundwork for attendance should it ever be introduced |
| Area listing | Members grouped by locality, for home visits and for any future neighbourhood grouping. Derived from `home_address`; no new field required |

### 7.6 Statutory and corporate records

AECI is a registered non-stock, non-profit corporation, and the registry holds exactly
the data its corporate filings describe. Two outputs follow almost for free.

| Output | Contents |
| --- | --- |
| **Membership register** | The church's book of members: `member_no`, full name, date admitted, and current status, in register order. Produced on demand instead of reconstructed by hand |
| **Officer and trustee list** | Every `Appointment` with position, holder and dates, for the corporation's annual filings |

**Caveat to confirm, not to assume.** The exact form and content a Philippine
non-stock corporation must keep and file is a question for whoever handles AECI's SEC
filings. These reports are built to hold the data and produce a clean listing; they are
not a claim about statutory sufficiency. Confirm the required format before relying on
either for a filing.

### 7.7 Access rules for reports

Every report honours the field-level restrictions of §4. A chairperson's contact
export cannot contain fields a chairperson may not see.

| Report group | Visible to |
| --- | --- |
| Celebrations | Secretariat, Sunshine chairperson, ICT |
| Operational queues | Secretariat, ICT |
| Committee management | Secretariat, Board, ICT; chairpersons see their own committee only |
| Board statistics | Board, Secretariat, ICT — aggregate figures only, no individuals |
| Printable output | Secretariat, ICT; chairpersons for their own committee |
| Statutory records | Board, Secretariat, ICT only. These list the whole congregation, so they carry the widest exposure of any output in Phase A |

**Audit granularity.** A report listing thirty people writes **one** `AccessLog` entry
naming the report and its scope, not thirty. Per-person logging is reserved for the
Person detail view. Logging every row would bury the signal the log exists to provide.

---

## 8. Architecture and deployment

### 8.1 Project layout

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

### 8.2 Stack

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

### 8.3 Deployment

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

### 8.4 Backups

Higher stakes here than anywhere else in the system: a lost church register cannot be
reconstructed.

- Nightly `pg_dump` to object storage, 30-day retention
- An admin export action so the Secretariat can pull a spreadsheet on demand
- A **written and tested** restore procedure. A backup nobody has restored from is a
  rumour
- Paper forms retained after encoding

---

## 9. Testing

The permission matrix of §4 *is* the test suite — every role against every capability,
parametrised.

| Area | Cases |
| --- | --- |
| Permissions | Each of five groups × each capability, positive and negative |
| Row-level scoping | A chairperson sees own roster only; sees no other committee |
| Field-level scoping | Address, birthdate, civil status, family absent from chairperson views |
| Committee rules | Max-two cap warns rather than refuses (amended 2026-08-17); appointed roles exempt; one chairperson per committee still refused; function belongs to committee |
| Control numbers | `MEM-` uniqueness, sequence allocation, manual override, concurrent allocation under `select_for_update` |
| Status transitions | `status_changed_at` stamped; `approved_by` required when *changing* to `MEMBER`; **not** required when *creating* at `MEMBER` (§3.2.2) — the backlog must stay encodable |
| Appointments | Unique-holder positions cannot overlap |
| Retention | `purge_stale_contacts` blanks the right fields on the live row **and across every historical revision**, spares identity data, tests the two-year boundary at 729 and 731 days, exercises `DECEASED` as well as `TRANSFERRED`, clears a household address only once nobody in it is current, and writes a `PurgeRecord` |
| Audit | Person views written to `AccessLog`; edits captured by simple-history; a list report writes exactly one entry, not one per row (§7.6) |
| Encoding | Incomplete records save; `has_missing_data` set correctly; follow-up queue filters |
| Celebration exclusions | Deceased, transferred, `date_of_death` set, and `greeting_opt_out` people never appear on any greeting list. Birth **year** never rendered |
| Date-boundary reports | Birthdays and anniversaries roll correctly across a year end, and handle 29 February |
| Report access | Each report against each role; a chairperson's contact export contains no field they may not see; Board statistics expose aggregates only |

---

## 10. Open items

Tracked, not blocking implementation.

| # | Item | Owner | Blocks |
| --- | --- | --- | --- |
| 1 | Photographs of filled paper profiling forms → `data/scanned-forms/` | ICT | Encoding, not build |
| 2 | Existing `MEM-` register — is one kept, highest number assigned, are numbers already handwritten | ICT | Seeding |
| 3 | Full legal names for chairpersons recorded by first name only (§6.5) | ICT | Seeding |
| 4 | Form v2 drafted with the consent clause (D18). Remaining: open in Word to check page layout, print, and collect signatures on 23 August 2026 | ICT / Church | Go-live |
| 5 | Board ratification of the retention policy (§5.1) | Board | Go-live |
| 6 | Filled examples of FR, RB, CDV and a real MoM | ICT | Phase B design |
| 7 | Attendance, baptism and dedication, transfer letter, visitor card forms — do not yet exist | Church | Future phases |

---

## 11. Planned: a public API for the church website

Requested 2026-08-17, explicitly **not for now** — the church intends to build a public website
after AEGIS, and to announce birthdays and wedding anniversaries there rather than in AEGIS's own
reports. Recorded here so the decision that matters is made before the code exists, not after.

**The thing to get right is not the API. It is the change in audience.** Every privacy decision in
this document was made for an audience of roughly twenty officers — D12 withholds addresses from
twelve chairpersons, D17 shows month and day but never the birth year so nobody learns an age. A
public website is a different question entirely: the audience becomes anyone on the internet,
including people who have no connection to the congregation.

Two consequences follow, and both are cheaper to decide now than to retrofit:

- **`greeting_opt_out` is the wrong default for publication.** It works for an internal list: the
  church greets its members unless someone asks otherwise. For a public page, the honest default is
  the reverse — nobody's name appears until they have said it may. That is a second, separate
  field, not a reinterpretation of the existing one, because a member who is happy to be greeted in
  the hall has not thereby agreed to be listed on the internet.
- **The consent form should say so.** Members are signing a data privacy clause that describes
  internal church use. Publication to a public website is a different purpose, and adding a line
  now costs a sentence; adding it later costs re-collecting every signature.

**Shape, when it is built:** read-only, no personal data beyond a display name and a day and month,
never a birth year, never a member number, never contact details. Authenticated and rate-limited
even so, because an endpoint returning "everyone with a birthday this week" is a membership roster
by another name if it can be enumerated. Serving a pre-rendered list the website fetches is
safer than exposing a queryable interface.

---

## 12. Next step

Produce the implementation plan for Phase A from this document.
