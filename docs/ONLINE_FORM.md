# The online profiling form, and the consent that goes with it

Two things live here:

1. **`docs/create_profiling_form.gs`** — a script that builds the Member Profiling Form in Google
   Forms. Paste it into script.google.com, press Run, get a link.
2. **The printed standalone consent**, below — the same wording on one page with a signature line,
   for the members who already filled in a paper form that had no consent clause on it.

Both carry the same text on purpose. `Person.consent_version` in AEGIS records *which wording* a
member agreed to, and that record is worthless if the church cannot produce the wording it names.

---

## Read this first: this is version 3, not version 2

The consent below is **not** the v2 clause drafted for the 23 August 2026 signing. It adds a
question v2 does not have — whether the member's name may be posted on the public church Facebook
page.

That makes it a new version. It cannot be called v2, because `consent_version` would then claim
people agreed to a Facebook clause they never read.

**Which to print for 23 August is a real decision, and it is yours.** The argument for printing v3
instead of v2 is in the design spec (§11) and it is the whole reason the field exists: adding this
line now costs a sentence, adding it later costs re-collecting every signature. If v3 can be
printed in time, print v3. If it cannot, print v2 as planned — but then everyone signing tomorrow
will need to be asked the Facebook question again separately, and that is the expensive path.

**Nobody in this project is a lawyer.** The text below is a good-faith RA 10173 notice written
against the Act's own requirements — identity of the collector, purpose, categories, recipients,
retention, and the data subject's rights. It is not legal advice, and the Board should read it
before it is printed. This is the same posture the design spec takes on the SEC filing formats: the
document is built to hold the right things, not to certify that it is sufficient.

---

## What still has to change in AEGIS

The form can ask the Facebook question today. **AEGIS cannot store the answer.** These are the
gaps, in the order they bite:

| Gap | What it is | Needed by |
| --- | --- | --- |
| No field for the Facebook answer | `Person` has `greeting_opt_out`, which is the *internal* greeting list and the wrong shape — it is opt-OUT and defaults to "yes, greet me". Public posting has to be a separate opt-IN field defaulting to no, exactly as spec §11 argued. Reusing `greeting_opt_out` would silently treat "happy to be greeted in the hall" as "happy to be on the internet". | Before the first Facebook post |
| `CONSENT_FORM_VERSION` still says `v2 (August 2026)` | `aeci/settings.py` line 304. Becomes `v3 (August 2026)` when v3 is adopted. | When v3 is adopted |
| Import template has no Facebook column | `docs/IMPORT_TEMPLATE.md`'s header row needs one more column, and `imports/spreadsheet.py` needs to read it. | Before importing v3 responses |
| Import template has no `Nickname` column | Pre-existing gap, unrelated to this change but visible here: the paper form v2 collects a nickname, the import spreadsheet never carried one, and Celebrations greets people by nickname. Every imported person currently has a blank one. | Worth fixing in the same pass |

None of that is built. Say the word and it is a small, contained piece of work — one field, one
migration, one column, and the tests for each.

---

## Using the Google Form

1. Sign in to **the Google account the church controls**, not a personal one. Same reasoning as
   `docs/DEPLOYMENT.md` §1: the day a volunteer becomes unreachable, the church must not lose the
   form and every response in it.
2. Go to script.google.com → **New project**, paste in `docs/create_profiling_form.gs`, **Run**.
3. Approve the permission prompt. Google warns that the script is "unverified" — that is because
   you wrote it rather than published it to the add-on store, and is expected.
4. The Execution log prints two links: one to edit the form, one to share.
5. **Fill in the church's registered address** where the consent says `[FILL IN: ...]`.
6. **Responses → Link to Sheets** to create the response spreadsheet.

### Getting responses into AEGIS

The response sheet's columns are the question titles, which were chosen to match
`docs/IMPORT_TEMPLATE.md`'s header row wherever possible — so the sheet is close to import-ready,
but not identical. Three things need doing by hand before upload:

- **Dates come out as `8/23/2026`, not `2026-08-23`.** Select those columns in Sheets and set
  Format → Number → Custom date and time → `YYYY-MM-DD`.
- **Committees arrive as one comma-joined cell** (`Sunshine, Youth`), but the import template wants
  one column per committee with an `X`. Split them by hand, or ask the Secretariat to do it in the
  review screen instead — the reviewer sees and can correct every field before approval anyway.
- **Add the columns the sheet has no source for**: `Source Image` (blank — there is no photograph
  of an online submission), `Form Version` (`v3`), and `Confidence` (`high` — a member typed this
  themselves, so there is no handwriting to misread).

The alternative, and honestly the simpler one for a first run: don't import the sheet at all. Open
each response beside the AEGIS encoding screen and type it in. Twenty-two forms is an afternoon,
and the import pipeline was built for *photographs of handwriting*, which this is not.

### What the online form deliberately does not ask

- **Member number.** Handwritten on paper forms and assigned by the Secretariat. A member typing
  their own would be inventing one.
- **Membership status.** A human decision, never inferred. Same rule as the import review screen.
- **Grievance and Reconciliation** as a committee choice. It is appointed by the Board, never
  self-selected, so it must not appear as a tickable box.
- **Anything mandatory except last name and first name.** A form that refuses to submit over a
  blank is a form people abandon. Blanks are encoded as blanks and chased later.

---

## The printed standalone consent

For members who already filled in a paper form with no consent clause on it. One page, print
double-sided if the church prefers, keep the signed copy with the original form.

> ---
>
> ## AVDEI ELOHIM CHURCH INC.
> ### Data Privacy Consent — v3 (August 2026)
>
> **Who is asking.** Avdei Elohim Church Inc. (AECI), a registered non-stock, non-profit religious
> corporation, with address at `_______________________________`, La Trinidad, Benguet.
>
> **What we collect.** Your name and nickname, date and place of birth, sex, civil status,
> nationality, home address, mobile number, email address, the name of your spouse and your date of
> marriage, the names and birth dates of your children, your emergency contact, and the committees
> you wish to serve in.
>
> **Why we collect it.** To keep the church's official register of members; to reach you about
> services, activities and pastoral care; to organise the committees; to greet members on birthdays
> and wedding anniversaries; and to contact the person you name if there is an emergency at a
> church activity.
>
> **Some of this is sensitive.** Under the Data Privacy Act of 2012 (RA 10173), your civil status,
> your age and your religious affiliation are sensitive personal information, and your children's
> details are a minor's personal data. That is why we ask for your consent in writing instead of
> assuming it.
>
> **Who can see it.** Only the Secretariat, the ICT Committee and the Board of Directors can see a
> complete record. A committee chairperson sees only the name, mobile number and email address of
> the members of their own committee — not your address, birth date, civil status or family. We do
> not sell, rent or trade your information, and we do not give it to anyone outside the church
> except where the law requires it.
>
> **How long we keep it.** Your name, membership dates and status are part of the church register
> and are kept permanently, the way a church has always kept its roll. Your contact details —
> mobile number, email, home address and emergency contact — are erased two years after your record
> is marked transferred or deceased.
>
> **Your rights.** You may ask to see your record, have it corrected, object to how it is used, or
> ask that it be erased. You may withdraw this consent at any time; withdrawing it does not undo
> what was already done lawfully before you withdrew. To do any of these, speak to the Secretariat.
> You may also complain to the National Privacy Commission (privacy.gov.ph).
>
> ---
>
> **I have read and understood the above.**
>
> ☐ **I consent** to Avdei Elohim Church Inc. collecting and using my personal information as
> described. If my children are listed on my profiling form, I give this consent as their parent or
> guardian.
>
> ☐ **I do not consent.**
>
> ---
>
> ### Optional — greetings on the church Facebook page
>
> This is a **separate** question. Your answer changes nothing above, and nothing about your
> membership.
>
> The church Facebook page is **public**. Anyone on the internet can see it, including people with
> no connection to the congregation. If you say yes, we would post only your **name and the
> occasion** — never your birth year, your age, your address, your phone number, your member
> number, or anything else about you. If you say no, the church will still greet you; it just will
> not do so on the public page. You may change your mind at any time by telling the Secretariat.
>
> ☐ **Yes**, you may greet me by name on the church Facebook page for my birthday and wedding
> anniversary.
>
> ☐ **No**, please do not post my name.
>
> ---
>
> Name (printed): `___________________________________________`
>
> Signature: `_________________________`  Date: `______________`
>
> ---
>
> *Received by (Secretariat):* `_______________________`  *Date:* `______________`
>
> ---

---

## A note on the two Facebook answers

A member can consent to the register and decline the Facebook page. That combination is normal and
must be easy — it is the reason these are two questions rather than one.

The reverse — declining the register but allowing Facebook — is not offered, and is not an
oversight. The church cannot post a greeting for someone whose name it is not allowed to hold.
