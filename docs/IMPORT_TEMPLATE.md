# AEGIS import template

How to turn photographs of member profiling forms into something AEGIS can ingest.

**The workflow.** You photograph the forms. You give an AI the prompt below plus the photos. It
returns **CSV text** — a spreadsheet, not code. You open that in Excel, scan it against the paper
forms in your hand, and correct anything the AI got wrong. You save your corrected copy as either
`.xlsx` or `.csv`. You upload that file to AEGIS, which shows you each person one at a time for
approval. Nothing reaches the register until you approve it.

**The AI never writes to AEGIS.** It produces a file. You review and correct that file. You decide
what happens to it.

**Why a spreadsheet.** The AI used to produce JSON, which nobody but a developer can sanity-check.
A spreadsheet is something you can actually read: open it, compare a row on screen against a sheet
in your hand, fix a misread name, and re-save it — before AEGIS ever sees it. AEGIS still also
accepts the old JSON shape, if you happen to have a file already produced that way, but everything
below describes the spreadsheet workflow, which is what to use from here on.

---

## 1. The prompt

Copy everything between the lines and send it with your photographs.

**Ask the AI for CSV, not for an Excel file.** Almost every AI chat tool can type out CSV text in
its reply; almost none can actually produce a binary `.xlsx` file. Asking for "an Excel file" gets
you a rejected attachment or a tool that quietly gives up. Ask for CSV — you'll open it in Excel
yourself afterwards, and Excel opens CSV natively.

---

You are transcribing photographed member profiling forms for Avdei Elohim Church Inc., a church
in La Trinidad, Benguet, Philippines. Your output will be reviewed by a person before it is
recorded, so **accuracy matters far more than completeness**.

**Rules, in order of importance:**

1. **Never invent anything.** If you cannot read a field, leave the cell blank and describe it in
   the `Flagged Fields` column. A blank is fine. A guess is not.
2. **Never normalise or correct what is written.** Filipino surnames and place names you do not
   recognise are still correct. Transcribe what is on the page.
3. **Never fix an apparent mistake.** If a date is impossible or a phone number is too short,
   record it as written and flag it. The person reviewing decides.
4. Record what is **actually ticked**, even if it breaks the form's own rules — including a third
   committee box, or the Grievance and Reconciliation box, which should never be ticked on this
   form at all (see the committee columns below).

Return **CSV text only** — a header row followed by one row per form, using exactly the header
row below. No commentary, no markdown code fences, no explanation before or after.

```
Source Image,Member No,Last Name,First Name,Middle Name,Suffix,Date of Birth,Place of Birth,Gender,Civil Status,Nationality,Home Address,Mobile Number,Email,Spouse Name,Date of Marriage,Child 1 Name,Child 1 Date of Birth,Child 2 Name,Child 2 Date of Birth,Child 3 Name,Child 3 Date of Birth,Child 4 Name,Child 4 Date of Birth,Child 5 Name,Child 5 Date of Birth,Emergency Contact Name,Emergency Contact Relationship,Emergency Contact Number,Sunshine,General Services,Property and Supplies,Music and Arts,Children's Ministry,Youth,Events,Finance and Resource Accessing,ICT,Secretariat,Food,Grievance and Reconciliation,Date Filed,Certification Date,Form Version,Notes,Confidence,Flagged Fields
```

One example row, so the shape is unambiguous (a fictional person — do not copy these values):

```
IMG_1234.jpg,,DELACRUZ,JUAN MIGUEL,REYES,,1990-05-12,LA TRINIDAD BENGUET,MALE,MARRIED,FILIPINO,PUROK 3 ALNO LA TRINIDAD BENGUET,0917-123-4567,jm.delacruz@example.com,ROSARIO P. DELACRUZ,2014-02-01,,,,,,,,,,,ROSARIO P. DELACRUZ,Spouse,0917-123-9999,,,,X,,,X,,,,,,2026-08-10,2026-08-10,v1,,high,
```

**Field rules:**

| Column | Rule |
| --- | --- |
| `Source Image` | The exact photo filename. Required — it is how a person finds the paper again. |
| `Last Name`, `First Name` | Required, never blank — a form with no legible name at all is not something AEGIS can stage as a person. If a name is genuinely unreadable, transcribe your best reading and note it in `Flagged Fields` rather than leaving the row out; the reviewer corrects it, but there must be something to correct. |
| `Form Version` | Required — always `v1` or `v2`, never blank. `v1` if Section V is Certification. `v2` if there is a Data Privacy Consent section before it. This decides whether consent was collected. |
| `Member No` | Usually blank. Never invent one. |
| Date columns (`Date of Birth`, `Date of Marriage`, `Date Filed`, `Certification Date`, and each `Child N Date of Birth`) | `YYYY-MM-DD`. If you cannot read it confidently, leave it blank and describe the raw text in `Flagged Fields`. Record an impossible date (see "Flag these specifically" below) in the same `YYYY-MM-DD` shape rather than as free text — AEGIS checks calendar validity itself when the entry is reviewed, and needs the digits as written to do that: a date that isn't a real calendar day at all (29 February in a non-leap year), a date of birth or date of marriage in the future, a marriage date before the person's own date of birth, and a child recorded as older than the household head are all refused at approval, not silently accepted. A birth year that is merely old or unlikely — the paper backlog is full of these — is not refused; only what is actually impossible is. |
| `Gender` | `MALE` or `FEMALE`, or blank. |
| `Civil Status` | `SINGLE`, `MARRIED`, `WIDOWED`, `SEPARATED`, `ANNULLED`, or blank. |
| Phone number columns | Exactly as written, spacing and dashes included. |
| `Child 1 Name` … `Child 5 Name` and their matching `Date of Birth` columns | The printed form has exactly five child rows — five fixed slots, in order. Leave a slot's two cells blank if the form has no child there; never invent a name to fill a slot, and never leave a slot's name blank while filling in its date of birth (or the reverse). If a form genuinely lists more than five children, record the first five and describe the rest in `Notes` — do not add a sixth pair of columns. |
| Committee columns (`Sunshine` through `Food`, plus `Grievance and Reconciliation`) | Mark `X` in a column if that box is ticked on the form; otherwise leave the cell blank. Include **every** box that is ticked, even if more than two — the form permits two, but your job is to transcribe what is on the page, not to enforce that rule. `Grievance and Reconciliation` is appointed by the Board and is never printed on this form at all; if you see it ticked anyway, still mark the `X` — do not erase it — and AEGIS will flag it for the reviewer automatically. |
| `Confidence` | Required — always `high`, `medium` or `low` for the form overall, never blank. This is what the reviewer checks first, so it must always be present. |
| `Flagged Fields` | One entry per doubtful field, in the form `Column Header: what you read and why`, e.g. `Date of Birth: read as OCT 14 1092, year digit unclear`. Separate multiple entries with ` \| ` (a space, a pipe, a space). Leave the cell blank if nothing about the row is uncertain. Use the *column header* on the left of the colon (`Date of Birth`, not `date_of_birth`) so AEGIS can attach the flag to the right field on the review screen. |
| `Notes` | Anything a reviewer should know that doesn't fit `Flagged Fields`. Blank if nothing. |

**The eleven committees a member may tick**, spelled exactly as their column headers:
`Sunshine` · `General Services` · `Property and Supplies` · `Music and Arts` ·
`Children's Ministry` · `Youth` · `Events` · `Finance and Resource Accessing` · `ICT` ·
`Secretariat` · `Food`

The twelfth column, `Grievance and Reconciliation`, is appointed by the Board and never appears as
a checkbox on this form — see the committee-column rule above.

**Flag these specifically** — they occur often and a reviewer must catch them:

- More than two committee columns ticked. The form permits two.
- A phone number written in a name column, or a name in a number column.
- A date that cannot be right — 29 February in a non-leap year, a future birth year.
- A child's entry overwritten or corrected on the page.
- Anything crossed out.
- `Grievance and Reconciliation` ticked at all (see above — AEGIS also catches this one itself).

Return only the CSV text. No commentary.

---

## 2. What to do with the output

1. Save the AI's reply as a `.csv` file and open it in Excel.
2. Compare it against the paper forms, row by row, column by column. Correct anything the AI
   misread. This is the whole point of the spreadsheet: you can actually do this step.
3. Save your corrected copy as either `.xlsx` or `.csv` — AEGIS reads both. It looks at the file's
   actual contents to tell one format from another (and from the older JSON shape), not the file
   extension, so it does not matter if an email client or Excel changed the extension along the
   way.
4. **Starting from scratch instead?** Download the blank template from AEGIS's Import screen (or
   run `python manage.py generate_import_template`) rather than typing headers by hand or letting
   the AI invent a layout — give that file to the AI, or fill it in yourself.
5. Upload the file in AEGIS under **Import** — never the photographs themselves (see Privacy
   below). AEGIS checks the file's shape and, if anything about it will not stage, tells you
   exactly which row and which column, so you can fix the cell or ask the AI to redo that form.
   A spreadsheet with the wrong columns — a missing one, a misspelled header — is refused with a
   plain list of what's wrong, before AEGIS looks at a single row of data.
6. Once staged, AEGIS shows you each person individually, laid out like the paper form, with the
   AI's confidence and every flagged field displayed prominently. Every field is editable. You
   approve, correct-then-approve, skip, or reject each one, one at a time — there is no bulk
   approval. Only approved people enter the register; a rejected or skipped entry never becomes a
   `Person`, and a skipped entry stays in the batch for you to come back to later, in the same
   "how many are left" view you started from.

## 3. Why the reviewer still matters

The AI reads handwriting well but cannot know things it is not looking at. It cannot tell that
two forms are the same family, that a member changed their number last month, or that a
committee ticked in error was discussed and settled at a meeting. It also cannot see a form it
was not given.

AEGIS itself does part of that family-matching at approval time, since both parents' forms
routinely list the same children. Approving the second parent's row looks for a child already
created by the first — matched on name **and** date of birth — and reuses that person and
household instead of creating a duplicate; it does the same for the spouse named in `Spouse Name`
if that person has already been approved. Every time this happens it is reported on the approval
result ("Linked to existing child …"), so a wrong match is something you catch immediately, not
months later. When a match is uncertain — the same name with a different or missing date of birth,
or more than one candidate — AEGIS refuses to guess and asks you to correct the entry instead of
silently creating a duplicate or silently linking the wrong person.

AEGIS re-checks the church's own rules on approval — at most two committees per member, one
chairperson per committee, valid dates. A row the AI faithfully transcribed can still be refused,
because the paper itself was wrong. That refusal is information, not a bug.

Membership status is not part of the spreadsheet at all, on purpose: the AI (and the sheet)
transcribes what is on the page, but whether someone counts as a `Member`, a `Child` in the
household, or something else is a decision for the person reviewing, not something to infer from
handwriting. AEGIS defaults the reviewer's choice to `Member`, since this whole workflow exists
for the Member Profiling Form, and lets it be changed per person before approving.

## 4. Privacy

These files hold members' names, birthdates, addresses, phone numbers and their children's
details. Treat them as you would the paper forms:

- The `form images/` directory and every file produced from it — spreadsheets as much as the old
  JSON files — are excluded from version control deliberately. Do not commit them.
- Delete the working files once the import is approved. The register is the record; the
  scratch file is not.
- Sending photographs to an outside AI service means this data leaves the church's systems.
  That is a decision for the Board, and the consent members sign should say so.
