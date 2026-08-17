# AEGIS import template

How to turn photographs of member profiling forms into something AEGIS can ingest.

**The workflow.** You photograph the forms. You give an AI the prompt below plus the photos. It
returns one JSON file. You upload that file to AEGIS, which shows you each person one at a time
for approval. Nothing reaches the register until you approve it.

**The AI never writes to AEGIS.** It produces a file. You decide what happens to it.

---

## 1. The prompt

Copy everything between the lines and send it with your photographs.

---

You are transcribing photographed member profiling forms for Avdei Elohim Church Inc., a church
in La Trinidad, Benguet, Philippines. Your output will be reviewed by a person before it is
recorded, so **accuracy matters far more than completeness**.

**Rules, in order of importance:**

1. **Never invent anything.** If you cannot read a field, use `null` and list it in
   `uncertain_fields`. A blank is fine. A guess is not.
2. **Never normalise or correct what is written.** Filipino surnames and place names you do not
   recognise are still correct. Transcribe what is on the page.
3. **Never fix an apparent mistake.** If a date is impossible or a phone number is too short,
   record it as written and flag it. The person reviewing decides.
4. Record what is **actually ticked**, even if it breaks the form's own rules.

Return **one JSON array**, one object per form, matching this shape exactly:

```json
[
  {
    "source_image": "IMG_5871.jpg",
    "form_version": "v1",
    "member_no": null,
    "date_filed": null,
    "last_name": "JOSE",
    "first_name": "MARK JEROME",
    "middle_name": "GANUELAS",
    "suffix": null,
    "date_of_birth": "1992-10-14",
    "place_of_birth": "BAGUIO CITY",
    "gender": "MALE",
    "civil_status": "MARRIED",
    "nationality": "FILIPINO",
    "home_address": "KC-109 CRUZ, LA TRINIDAD, BENGUET",
    "mobile_number": "0991-922-6025",
    "email": "mjjose1925@gmail.com",
    "spouse_name": "GLEAN K. JOSE",
    "date_of_marriage": "2015-10-17",
    "children": [
      { "full_name": "SHILOH ANDREI K. JOSE", "date_of_birth": "2016-02-25" },
      { "full_name": "SHEKINAH LARIEL K. JOSE", "date_of_birth": "2023-11-20" }
    ],
    "emergency_contact_name": "GLEAN K. JOSE",
    "emergency_relationship": "SPOUSE",
    "emergency_number": "0991 922 6034",
    "committees": ["Music and Arts", "Events"],
    "certification_date": "2026-08-16",
    "confidence": "high",
    "uncertain_fields": [],
    "notes": null
  }
]
```

**Field rules:**

| Field | Rule |
| --- | --- |
| `source_image` | The exact filename. Required — it is how a person finds the paper again. |
| `last_name`, `first_name` | Required text, never `null` and never blank — a form with no legible name at all is not something AEGIS can stage as a person. If a name is genuinely unreadable, transcribe your best reading and flag it in `uncertain_fields` rather than omitting it; the reviewer corrects it, but there must be something to correct. |
| `form_version` | Required — always `"v1"` or `"v2"`, never `null`. `"v1"` if Section V is Certification. `"v2"` if there is a Data Privacy Consent section before it. This decides whether consent was collected. |
| `member_no` | Usually blank. Never invent one. |
| dates | `YYYY-MM-DD`. If you cannot read it confidently, use `null` and put the raw text in `uncertain_fields`. Record an impossible date (see "Flag these specifically" below) in the same `YYYY-MM-DD` shape rather than as free text — AEGIS checks calendar validity itself when the entry is reviewed, and needs the digits as written to do that. |
| `gender` | `MALE` or `FEMALE`, or `null`. |
| `civil_status` | `SINGLE`, `MARRIED`, `WIDOWED`, `SEPARATED`, `ANNULLED`, or `null`. |
| phone numbers | Exactly as written, spacing and dashes included. |
| `children` | Required array, `[]` if none — never omitted and never `null`. Never pad to five. |
| `committees` | Required array, `[]` if none ticked — never omitted and never `null`. Exact strings from the list below. Include **all** ticked, even if more than two. |
| `confidence` | Required — always `"high"`, `"medium"` or `"low"` for the form overall, never `null`. This is what the reviewer checks first, so it must always be present. |
| `uncertain_fields` | Required array, `[]` if nothing is uncertain — never omitted and never `null`. One entry per doubtful field: `{"field": "date_of_birth", "read_as": "OCT 14 1092", "why": "year digit unclear"}` |
| `notes` | Anything a reviewer should know. `null` if nothing. |

**The eleven committees**, spelled exactly:
`Sunshine` · `General Services` · `Property and Supplies` · `Music and Arts` ·
`Children's Ministry` · `Youth` · `Events` · `Finance and Resource Accessing` · `ICT` ·
`Secretariat` · `Food`

There is a twelfth, Grievance and Reconciliation, which is appointed by the Board and never
appears on this form. If you see it ticked, record it and flag it in `notes`.

**Flag these specifically** — they occur often and a reviewer must catch them:

- More than two committees ticked. The form permits two.
- A phone number written in a name field, or a name in a number field.
- A date that cannot be right — 29 February in a non-leap year, a future birth year.
- A child's entry overwritten or corrected on the page.
- Anything crossed out.

Return only the JSON array. No commentary.

---

## 2. What to do with the output

Save it as a `.json` file. Upload it in AEGIS under **Import** — only the JSON file, never the
photographs themselves (see Privacy below). AEGIS checks the file's shape and, if anything about
it will not stage, tells you exactly which entry and which field, so you can fix the file or ask
the AI to redo that form. Once staged, AEGIS shows you each person individually, laid out like
the paper form, with the AI's confidence and every field it flagged in `uncertain_fields`
displayed prominently. Every field is editable. You approve, correct-then-approve, skip, or
reject each one, one at a time — there is no bulk approval. Only approved people enter the
register; a rejected or skipped entry never becomes a `Person`, and a skipped entry stays in the
batch for you to come back to later, in the same "how many are left" view you started from.

## 3. Why the reviewer still matters

The AI reads handwriting well but cannot know things it is not looking at. It cannot tell that
two forms are the same family, that a member changed their number last month, or that a
committee ticked in error was discussed and settled at a meeting. It also cannot see a form it
was not given.

AEGIS re-checks the church's own rules on approval — at most two committees per member, one
chairperson per committee, valid dates. A row the AI transcribed faithfully can still be
refused, because the paper itself was wrong. That refusal is information, not a bug.

Membership status is not part of the AI's JSON at all, on purpose: the AI transcribes what is on
the page, but whether someone counts as a `Member`, a `Child` in the household, or something else
is a decision for the person reviewing, not something to infer from handwriting. AEGIS defaults
the reviewer's choice to `Member`, since this whole workflow exists for the Member Profiling
Form, and lets it be changed per person before approving.

## 4. Privacy

These files hold members' names, birthdates, addresses, phone numbers and their children's
details. Treat them as you would the paper forms:

- The `form images/` directory and these JSON files are excluded from version control
  deliberately. Do not commit them.
- Delete the working files once the import is approved. The register is the record; the
  scratch file is not.
- Sending photographs to an outside AI service means this data leaves the church's systems.
  That is a decision for the Board, and the consent members sign should say so.
