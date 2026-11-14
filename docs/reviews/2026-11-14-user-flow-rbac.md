# User flow and access review — 14 November 2026

Scope: current repository, migration-seeded roles, existing permission tests,
and authenticated requests with synthetic local accounts. Production account
assignments were not rechecked: Render and Neon connectors became unavailable
in this session. No hosted member records or role assignments were changed.

## Registration and review

1. A member opens `/register/`, enters profiling details and consent, and checks
   whether a record or pending submission already exists. The public check
   returns a generic notification without another member's private details.
2. A submission enters the review queue as a staged entry. It does not create a
   login, member record, or committee officer appointment.
3. Secretariat or ICT reviews the submission, corrects details, decides its
   membership status, and approves, skips, or rejects it. Board and
   Chairperson cannot approve these submissions.
4. Approval creates or enriches the person and links family/committee records
   in one transaction. The staged entry records the reviewer and decision time.
   Concurrent attempts cannot approve the same entry twice.
5. ICT separately creates a staff account if needed, assigns its access group,
   and links the account to the correct person. Registering as a member does
   not grant staff access.

### Identity resolution correction included with this review

The reported child-match failure was reproducible: a compatible name with a
different or missing birthday blocked approval and required changing identity
data. The staff screen now offers an explicit choice between an existing
record and a separate person. It also requires confirmation before using an
earlier child record as the subject or linking an existing spouse. No match is
preselected. A separate-child choice also prevents household inference from
joining the unrelated person's family.

Choices are recomputed and validated on the server. Stale or forged targets
cannot be linked. Linking a child preserves the existing child's identity
details. The original submission stays intact; the review retains the selected
IDs and the labels seen by the reviewer. Skip and Reject remain available
without completing identity decisions. Existing structural validation remains.

The legacy programmatic service API retains its prior matching behavior;
the staff review caller always enables required reviewer decisions. There is
no other production caller of this service in the repository.

## Intended role boundaries

| Role / qualification | Intended access |
| --- | --- |
| Public member | Submit profiling details; receive a generic duplicate notification. |
| Secretariat | Maintain records, review registrations, assign Oversight committee roles. No account linking. |
| Board | Read records, make membership-acceptance decisions and officer appointments. |
| Chairperson only | Read a restricted roster for their actively assigned committee. No review queue or record edits. |
| Active Pastor appointment | View celebrations; other access depends on additional groups. |
| Sunshine chair/co-chair | View celebrations through the active committee appointment. |
| ICT / superuser | Administer records and access; link logins to people. |

Wider access groups take precedence over Chairperson-only scoping. A linked
person, staff-enabled account, and active appointment are separate requirements.
Grievance and Reconciliation committee membership alone does not currently
grant Pastor celebration access; the code checks an active Pastor appointment.

## Confirmed findings still needing correction

### High: Secretariat can bypass officer-appointment restrictions

The dedicated appointment screen permits Secretariat to assign Oversight only.
The ordinary Committee Membership admin and Person inline expose unrestricted
roles. A synthetic Secretariat POST successfully created a Chairperson
appointment. Enforce the same rule in all admin paths and inlines.

Evidence: `committees/appointing.py:43`, `committees/appointing.py:100`,
`committees/admin.py:211`, `people/admin.py:139`,
`core/migrations/0002_create_groups.py:14`.

### High: Board permission permits full record editing and numbering

The Board's `change_person` grant opens all ordinary Person fields and the
member-number action. Synthetic Board requests successfully changed a name and
address and assigned a member number. The design intends membership acceptance,
not general record editing. Provide a narrow acceptance operation and restrict
the other fields/actions server-side.

Evidence: `core/migrations/0004_fix_group_permissions.py:111`,
`people/admin.py:190`, `people/admin.py:236`, `people/admin.py:332`.

### High: public-ready greetings ignore Facebook consent

A synthetic person with `public_greeting_consent=False` appeared in the birthday
message labelled "Ready to post". The celebration roster checks general greeting
opt-out and status, but its public copy output does not require Facebook opt-in.
This finding concerns the prepared output; no public post was made during review.
Separate internal reminders from public messages and require public opt-in for
the latter. For anniversaries, check both spouses. Expose these separate
preferences on ordinary Person view/edit screens.

Evidence: `people/celebrations.py:122`, `people/celebrations.py:203`,
`people/celebrations.py:282`,
`people/templates/admin/people/person/celebrations.html:63`.

### Medium: Chairperson autocomplete reveals excluded fields

Row scoping works, but a Chairperson autocomplete request returned a scoped
person's middle name and member number through `str(Person)`. Those fields are
excluded from the restricted roster display. Search also accepts the hidden
member number. Restrict autocomplete labels and searchable fields by role.

Evidence: `people/models.py:174`, `people/admin.py:45`, `people/admin.py:189`.

### Medium: deletion grants differ from the ICT-only hard-delete policy

Board and Secretariat retain committee-membership deletion permissions.
Secretariat can also delete import batches, cascading staged submissions and
their stored review/consent evidence. Confirm the intended retention rule, then
reserve deletion to ICT or provide an archive operation preserving evidence.

Evidence: `core/migrations/0002_create_groups.py:15`,
`core/migrations/0002_create_groups.py:25`,
`imports/migrations/0002_grant_group_permissions.py:33`, `imports/models.py:84`.

## Workflow improvements

- Distinguish accepting a submission into the registry from formally approving
  church membership. A new imported subject can be created as Member; an
  existing child's transition requires a named approver through its record.
- Show account readiness together: active login, staff access, groups, linked
  person, and active appointment. This explains empty Chairperson screens and
  Pastor access failures before handing an account over.
- When linked children span multiple households, ask the reviewer how to handle
  that family. The current service creates the subject but leaves those family
  links untouched and reports a notice afterward.

Other observed controls: public submissions require staff review; sensitive
review/detail accesses are logged; Chairperson history and hidden-field URL
filters are blocked; account linking is ICT-only; celebrations check designated
roles or active appointments. These controls do not resolve the findings above.
