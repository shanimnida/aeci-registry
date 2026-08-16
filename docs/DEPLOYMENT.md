# Deploying the AECI Registry

This is the walkthrough for putting the AECI member registry online: code on
GitHub, database on Neon, application on Render, scanned forms on Cloudflare
R2. It is written for the ICT Committee of Avdei Elohim Church Inc., assuming
whoever reads it is comfortable with computers but has never deployed a
Django application before. Every step says what to click or type and what
you should see happen. Where something commonly trips people up, that's
noted right there, not saved for an appendix at the end.

Read the whole thing once before you start. Some steps (Section 8, Cloudflare
R2) don't have to happen on day one — the document says exactly when they
become necessary.

## Two things before anything else

**Do not put real member data into this system until the data privacy
consent clause has been signed.** That's scheduled for the Sunday service on
**23 August 2026**. The current paper profiling form has no consent clause
for the sensitive information it collects (civil status, birthdate, home
address, children's data, religious membership — all "sensitive personal
information" under the Data Privacy Act of 2012, RA 10173). Deploying the
system *empty* before that date is not just fine, it's encouraged: it's the
best way to find deployment problems before anything of value is at risk.
Sections 1 through 7 of this document can all happen before 23 August.
Section 6's Secretariat and Board accounts can be created and tested against
an empty database too.

**This deployment must be done by the church's own people, typing their own
credentials into Render, Neon, GitHub and Cloudflare's own websites.** Don't
have someone else — a contractor, a friend who's "good with computers," an AI
assistant — do this on your behalf, even with good intentions. Every step
below asks you to create an account, generate a password, or paste a
database connection string. None of that should pass through anyone's hands
but the church's own. If you're reading this while an AI assistant is
sitting in the same chat window offering to "help," the help stops at
reading and explaining this document — the account creation and credential
entry are yours to do.

## Contents

1. [Before you start](#1-before-you-start)
2. [Getting the code to GitHub](#2-getting-the-code-to-github)
3. [Neon — the database](#3-neon--the-database)
4. [Render — the application](#4-render--the-application)
5. [First deploy](#5-first-deploy)
6. [The five role groups and the first accounts](#6-the-five-role-groups-and-the-first-accounts)
7. [Seeding the officers from the CSV](#7-seeding-the-officers-from-the-csv)
8. [Cloudflare R2 — storage for scanned forms](#8-cloudflare-r2--storage-for-scanned-forms)
9. [Scheduling the two jobs](#9-scheduling-the-two-jobs)
10. [Verifying the deployment worked](#10-verifying-the-deployment-worked)
11. [Moving to paid hosting later](#11-moving-to-paid-hosting-later)

---

## 1. Before you start

The stack is: **Render** runs the application, **Neon** hosts the
PostgreSQL database, **Cloudflare R2** stores scanned form images. All three
have free tiers, chosen deliberately so the church can run this at no cost
for as long as that keeps working, and move any one of them to a paid plan
later without rewriting anything (Section 11).

**Free-tier terms change.** The numbers and features described in this
document (storage limits, sleep behaviour, what requires a paid plan) are
accurate as of when this was written. Check each provider's current pricing
page when you actually sign up — a "free tier" is a business decision the
provider can revise.

You will need accounts on:

- **GitHub** (to hold the code)
- **Render** (to run the application)
- **Neon** (for the database)
- **Cloudflare** (for R2 — needed by Section 8, but worth creating now)

Create every one of these under an email address **the church controls**,
not the personal email of whichever volunteer is doing this today — for
example, an official church Gmail or Workspace address that the ICT
Committee as a body can get into. If a personal account is used instead, the
day that volunteer becomes unreachable, the church loses the ability to
redeploy the site, rotate a leaked credential, or even see why it went down.
This is the single most important housekeeping decision in this whole
document, and it costs nothing to get right the first time.

## 2. Getting the code to GitHub

1. On GitHub, create a **new, private** repository (Settings you'll want:
   private, no README/license/gitignore auto-generated — this project
   already has those).

   **Why private, given the codebase has no secrets committed to it**
   (`.env` is git-ignored — see `.gitignore` — and nothing else in the repo
   is a credential): `data/officers.csv` holds the real names of committee
   chairpersons and is deliberately **not** git-ignored, because it's
   governance data (who holds what office), not personal member data. A
   public repository would put that list, and this project's own
   documentation of exactly how its access-control and privacy rules work,
   in front of anyone on the internet. Neither is a reason to panic, but
   neither needs to be public either.

2. From this project's folder, add the new repository as a remote and push:

   ```
   git remote add origin https://github.com/<your-org-or-account>/<repo-name>.git
   git push -u origin main
   ```

   (Substitute whatever branch you intend to run in production — the URL
   GitHub gives you after creating the repo has the exact remote-add command
   pre-filled; use that if it differs from the example above.)

3. Confirm on GitHub's web UI that the files are there and the repository
   shows a padlock/"Private" label.

## 3. Neon — the database

1. Sign up at Neon, create a new **project**. Pick a region close to where
   the site will mostly be used (a Singapore or other nearby Asia-Pacific
   region, if offered, will feel faster than a US one — this is a latency
   preference, not a correctness requirement).

2. Neon creates a default database and role for you. Open the project's
   **Connection Details** / **Connection string** panel and copy the full
   string. It looks like:

   ```
   postgresql://<user>:<password>@<host>/<dbname>?sslmode=require
   ```

   Confirm `sslmode=require` is present — Neon includes it by default, and
   the application's own backup command (`core/management/commands/
   backup_database.py`) depends on that same setting being there for its own
   connection, so don't strip it off.

3. Save this string somewhere safe **temporarily** — a password manager
   entry, not a chat message, a text file on the Desktop, or an email to
   yourself. You'll paste it into Render in the next section as
   `DATABASE_URL`, and it won't need to live anywhere else after that.

4. Note honestly: Neon's free tier auto-suspends the database after a period
   of inactivity, which adds a short delay to the first query after it's
   been idle — separate from, and in addition to, Render's own sleep
   behaviour described in Section 10. Check Neon's current free-tier limits
   (storage, compute hours) on their pricing page; they're a separate thing
   from what's described here and are more likely to change.

## 4. Render — the application

1. Sign in to Render with your GitHub account. When it asks which
   repositories to grant access to, choose **only this one repository**, not
   "all repositories" — no reason to give Render more reach than it needs.

2. **New → Web Service**, select the repository from Section 2.

3. **Runtime**: Python. Render reads the Python version from this project's
   own `runtime.txt` (`python-3.12.3`) automatically — nothing to set here.

4. **Root Directory**: leave blank. The project lives at the repository
   root.

5. **Build Command**:

   ```
   pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate --noinput
   ```

   Three things happen here, and all three matter:
   - `pip install` — installs Django and everything else in
     `requirements.txt`.
   - `collectstatic --noinput` — **do not skip this.** The project serves
     static files (including the Django admin's own CSS and JavaScript)
     through WhiteNoise's `CompressedManifestStaticFilesStorage`
     (`aeci/settings.py`), which raises an error for any static file
     reference that isn't in a manifest built by `collectstatic`. Skip this
     step and the admin site itself — the entire application — breaks.
   - `migrate --noinput` — this is normally what the `Procfile`'s `release:`
     line is for (Heroku-style convention: run once, after build, before the
     new version takes traffic). **Render's free instance type doesn't run
     that Procfile line or its own equivalent "Pre-Deploy Command" feature —
     both require a paid instance type.** Folding `migrate` into the Build
     Command is the free-tier workaround, and it's safe to run on every
     single deploy: Django tracks which migrations have already applied and
     skips them.

6. **Start Command**:

   ```
   gunicorn aeci.wsgi
   ```

   (matches the `Procfile`'s `web:` line.)

7. **Instance Type**: Free.

8. **Environment Variables** — add these under the service's Environment
   tab. This table is the complete list of everything `aeci/settings.py`
   reads from the environment, what to set it to, and — this is the part
   worth reading carefully — what actually happens if it's wrong or left
   out.

   | Variable | Set it to | If it's wrong or missing |
   | --- | --- | --- |
   | `SECRET_KEY` | A freshly generated random value — see below. **Never** the value `dev-only-not-for-production` from `.env.example`. | Missing: the application will not start at all. Set to the checked-in dev value, or any value anyone outside the church has seen: sessions, password-reset tokens and CSRF protection all depend on this staying secret — reusing a value that's sat in a public place defeats all three. |
   | `DEBUG` | `False` | Missing: defaults to `False` anyway (the code's own default), so this is safe to omit, but set it explicitly so nobody has to go read the source to know. Set to `True` by mistake: Django shows a full error page — source code, settings, other environment variables — to any visitor who triggers an error, **and** the entire production-hardening block at the bottom of `settings.py` (forced HTTPS, secure cookies, HSTS) is skipped, because it's all gated on `if not DEBUG`. This is the single most damaging setting to get wrong. |
   | `ALLOWED_HOSTS` | The exact hostname Render assigns, e.g. `aeci-registry.onrender.com` — copy it from the Render dashboard after your first deploy rather than guessing it. | Missing or wrong: Django refuses every request with a 400 "DisallowedHost" error. The server is running fine; it just won't answer anyone, including you. |
   | `DATABASE_URL` | The Neon connection string from Section 3, `sslmode=require` intact. | Missing: application won't start. Wrong host or password: application starts, but every page — the entire admin site touches the database — fails with a 500 error. |
   | `USE_S3_STORAGE` | `False` for now; `True` once you complete Section 8. | See Section 8 — this is what makes uploaded scan files survive a redeploy. |
   | `AWS_STORAGE_BUCKET_NAME`, `AWS_S3_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | From Section 8. | Only read at all when `USE_S3_STORAGE=True`. Missing while it's `True`: application won't start. Present but wrong: application starts fine, but every scan upload or view fails. |
   | `PG_DUMP_PATH` | Leave unset on Render. | Only affects `backup_database`, which — see Section 9 — does not run on Render in this plan, so it has no effect here either way. |
   | `BACKUP_TO_STORAGE`, `BACKUP_RETENTION_DAYS` | Leave unset on Render. | Same reasoning as `PG_DUMP_PATH` — these matter wherever `backup_database` actually executes (Section 9), which in this plan isn't Render. |

   **Generating a real `SECRET_KEY`**: on your own computer, in any Python 3
   installation (this doesn't need the project's own environment set up),
   run:

   ```
   python -c "import secrets; print(secrets.token_urlsafe(50))"
   ```

   Paste the output — one line of random characters — into Render's
   `SECRET_KEY` variable. Never commit it to the repository, never paste it
   into an email or chat with anyone outside the church, and never reuse it
   for anything else.

## 5. First deploy

1. Click **Create Web Service** and watch the build log.

2. What happens automatically, in order: dependencies install,
   `collectstatic` runs, then `migrate` runs — which both creates every
   table the application needs *and* creates the five role groups (ICT,
   Secretariat, Treasurer, Board, Chairperson) with their permissions
   already assigned, via a migration (`core/migrations/0002_create_groups.py`)
   that ships with the code. You don't do anything separate to get the
   groups — they exist the moment `migrate` finishes.

3. Once the deploy says "Live," visit `https://<your-service>.onrender.com/admin/`.
   You should see a **styled** Django admin login page. If it loads with no
   styling at all — plain black text on white, no layout — `collectstatic`
   didn't run; check the Build Command from Section 4.

4. **Creating the first ICT superuser.** Render's free instance type does
   **not** provide shell or SSH access — that's a paid-plan feature, along
   with "one-off jobs." (This differs from what earlier planning notes for
   this project assumed; it's confirmed directly against Render's own
   documentation, and it's worth knowing plainly rather than discovering it
   when a shell tab that should be there isn't.) The workaround uses the
   same Build Command mechanism from Section 4, plus a feature Django itself
   ships with — non-interactive superuser creation from environment
   variables:

   1. In Render's **Environment** tab, temporarily add three variables:
      `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL`, and
      `DJANGO_SUPERUSER_PASSWORD` (a real, strong, unique password — not one
      reused anywhere else).
   2. Edit the **Build Command** to add, at the end:
      `&& python manage.py createsuperuser --noinput`
   3. Save. Render redeploys automatically. Watch the build log for
      "Superuser created successfully."
   4. Log in at `/admin/` with that username and password. You should land
      on the admin index page listing **Groups**, **Users**, and four apps:
      Committees, Core, People, Records.
   5. **Clean up immediately, in this order:** first edit the Build Command
      to remove the `&& python manage.py createsuperuser --noinput` you
      added — leaving it in place will make the *next* deploy fail outright,
      because the command errors out on a user that already exists, which
      blocks every future deploy until someone notices and fixes it. Then
      delete the `DJANGO_SUPERUSER_PASSWORD` variable (or overwrite it with
      throwaway text) so the real password stops sitting in the dashboard in
      plain text. Save once more to trigger a final deploy with the
      Build Command back to its normal, permanent form from Section 4.
   6. Because a Django superuser bypasses permission checks entirely, this
      account already has full access — you do not additionally need to put
      it in the "ICT" group for it to work, though you're welcome to for
      clarity's sake once ordinary (non-superuser) ICT accounts exist too
      (Section 6).

   **Common mistake**: skipping step 5 above. If a *later* deploy suddenly
   fails in the build log with something like "that username is already
   taken," this is why — go remove the `createsuperuser` clause from the
   Build Command.

## 6. The five role groups and the first accounts

The five groups already exist after Section 5 — they're created by a
migration, not something you build by hand. What's left is deciding who
goes in which one, and creating their logins.

| Group | Who, in this church | What they can do |
| --- | --- | --- |
| **ICT** | The ICT Committee members who administer the system. | Everything — including the only group that can create new user accounts (nobody else can). |
| **Secretariat** | The Secretariat staff who encode member records day to day. | Create and edit Person records, manage households, upload scans. Cannot create logins, and cannot set someone's status to `MEMBER` without a recorded approver. |
| **Treasurer** | Nobody yet, deliberately. | Zero permissions in this phase — fund release, OR numbers and the ledger are future work. The group exists now so accounts slot in cleanly later; there's no reason to create an actual Treasurer login yet, and doing so would just be a login that can see nothing. |
| **Board** | The Pastor and Board members. | View full person records, appoint officers and chairpersons, approve membership status changes, read the audit log. |
| **Chairperson** | The people chairing individual committees (Section 7 seeds six of them from the current officers list). | See only name, mobile number and email for members of *their own* committee — nothing else, and no visibility into any other committee. |

**Creating an account** (do this from the admin, logged in as the ICT
superuser from Section 5, or as any other account already in the ICT
group):

1. **Authentication and Authorization → Users → Add user.** Set a username
   and a temporary password.
2. Save, then on that user's own change page: check **"Staff status."** This
   is unchecked by default on a newly created user, and without it, the
   person cannot log into `/admin/` at all, even with the correct password —
   this is the single most common thing to forget here.
3. Under **Groups**, add them to the one group from the table above that
   matches their role.
4. Tell the person their temporary password over the phone or in person, not
   email — this system will eventually hold sensitive personal data, and
   it's worth building the habit of not putting credentials in writing from
   day one.

**A gap worth knowing about, for Chairperson accounts specifically.** A
Chairperson's "own committee only" view works by matching their logged-in
account to their existing `Person` record (`committees/admin.py` and
`people/admin.py` both filter on `person__user=request.user`). That link —
the `Person.user` field — exists on the data model, but it is **not**
currently on the Person edit screen in the admin, so there's no button to
click to set it. Until that's added to the admin (a small code change,
outside the scope of this document — worth raising with whoever next works
on the app), the only way to set it is the same one-off Build Command
technique from Section 5:

1. Temporarily append to the Build Command, substituting the real username
   and the chairperson's actual name as it appears in `data/officers.csv`:

   ```
   && python manage.py shell -c "from django.contrib.auth.models import User; from people.models import Person; p = Person.objects.get(last_name='Malong', first_name='Shan Albert'); p.user = User.objects.get(username='shan'); p.save()"
   ```

2. Deploy, confirm no error in the build log, then remove that clause from
   the Build Command exactly as in Section 5.5, and redeploy once more.

If you skip this, the Chairperson login still works, but their committee
screens will show **zero rows** instead of their roster — it fails safe
(nothing leaks to them), it just doesn't do anything useful until linked.

## 7. Seeding the officers from the CSV

`data/officers.csv` lists the current committee chairpersons, resolved by
the ICT Committee (some officers known only by nickname are deliberately
left out until their full names are confirmed — see the comment at the top
of `committees/management/commands/seed_officers.py`). Running
`seed_officers` creates a `Person` record and a `CommitteeMembership` for
each row. **It does not create login accounts** — that's the separate,
manual step in Section 6. A seeded Person can exist perfectly well with
nobody able to log in as them, and that's the normal state for most of
these six people.

The command is idempotent — safe to run again as names get corrected — but
if any single row fails validation, the **entire command** exits with an
error and nothing from that row is saved. Because of that, don't wire this
permanently into the Build Command: a future typo in the CSV would then
block every deploy, not just fail the seeding. Instead, run it the same
one-off way as the superuser step:

1. Temporarily append `&& python manage.py seed_officers` to the Build
   Command.
2. Deploy. Check the build log for a line like `Created 6 person(s) and 6
   committee role(s) from 6 row(s).` followed by `All rows imported
   cleanly.`
3. Remove the clause from the Build Command, redeploy once more.
4. Repeat this whenever `data/officers.csv` changes — for example, when a
   nickname gets resolved to a full legal name.

Verify in the admin: **People → Person** should list 6 people; **Committees
→ Committee memberships** should show each of them as Chairperson of their
committee.

## 8. Cloudflare R2 — storage for scanned forms

**This becomes necessary the moment the first scanned paper form is
uploaded through the admin** — not before. None of Sections 1–7 upload any
files, so it's fine to do this later, right up until someone is about to
scan and upload the first form.

**What breaks if it's skipped**: `aeci/settings.py` has a comment explaining
exactly why R2 matters here — "a free-tier host resets its filesystem on
every redeploy and on idle spin-down." Render's free tier does precisely
that after roughly 15 minutes of inactivity. A scan uploaded without R2
configured writes to local disk, looks completely fine at the moment of
upload, and then silently vanishes the next time the service redeploys or
wakes from sleep. The database record (`FormScan`) survives; it just points
at a file that no longer exists. Nothing in the interface warns you when
this happens — the loss is silent.

1. Sign up for Cloudflare (same rule as Section 1: a church-controlled
   email), then create an **R2 bucket** — name it something recognisable,
   e.g. `aeci-registry-scans`.
2. Create an **R2 API token** scoped to that one bucket only (Cloudflare's
   R2 dashboard has "Manage R2 API Tokens") with Object Read & Write
   permission — not a token with access to your whole Cloudflare account.
   Copy the Access Key ID and Secret Access Key it gives you; you won't be
   able to see the secret again after this screen closes.
3. Note your Cloudflare **Account ID** (shown in the R2 dashboard).
4. On Render, set:

   | Variable | Value |
   | --- | --- |
   | `USE_S3_STORAGE` | `True` |
   | `AWS_STORAGE_BUCKET_NAME` | the bucket name from step 1 |
   | `AWS_S3_ENDPOINT_URL` | `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` |
   | `AWS_ACCESS_KEY_ID` | from step 2 |
   | `AWS_SECRET_ACCESS_KEY` | from step 2 |

   Save — Render redeploys automatically.

5. **Verify**: upload a test scan through the admin (or the first real one,
   once consent is signed), then check the Cloudflare R2 dashboard for a new
   object in the bucket.

6. **If uploads fail with a signature error**: R2 needs AWS Signature
   Version 4, which recent versions of the underlying `boto3` library use by
   default in most setups — but if it doesn't work out of the box, that's a
   one-line settings change (`AWS_S3_SIGNATURE_VERSION = "s3v4"`), which is
   application code and out of scope for this document. Flag it to whoever
   next works on the app rather than trying to route around it here.

7. **Free-tier honesty**: R2's free allowance (storage and the number of
   read/write operations) and, notably, its lack of egress fees even beyond
   the free tier, are part of why it was chosen — but check Cloudflare's
   current numbers at signup rather than trusting a number written here.

Backups (Section 9) will reuse this exact same bucket, under a `backups/`
key prefix, so scanned forms and database backups never mix in storage.

## 9. Scheduling the two jobs

Nothing runs `backup_database` or `purge_stale_contacts` automatically yet.
The `Procfile`'s `release:` line and Render's own "Pre-Deploy Command"
feature both only run around a deploy — neither is a scheduler, and (as
covered in Section 4) neither is even available on Render's free instance
type in the first place.

**Render's free tier has no cron feature.** Render does have a Cron Jobs
product, but it's a separate, paid offering — not part of the free web
service instance this plan uses. That rules out the simplest-sounding
option outright, so here are the two honest ones:

### Option A — a scheduled GitHub Actions workflow (recommended)

This runs entirely on GitHub's own servers, on a schedule, completely
independent of Render — it talks directly to Neon and R2 using the same
credentials Render uses, so Render having no shell and no cron doesn't
matter here at all.

- **Cost**: free. GitHub gives every private repository on the free plan
  2,000 Actions minutes a month; two short jobs (a minute or two each)
  running nightly use a small fraction of that.
- **Trade-off**: someone has to set it up once — a workflow file plus a
  handful of repository secrets — and GitHub **automatically disables**
  scheduled workflows after 60 days with no commits to the repository (this
  applies to private repos too, despite GitHub's wording sometimes
  suggesting otherwise; only an actual push resets the clock, not issues or
  comments). For a project that might go quiet for months once it's
  working, that's a real risk worth planning around — check the repository's
  **Actions** tab occasionally, and know that any small commit (even a
  documentation fix) resets the 60-day clock.

To set this up, add a file at `.github/workflows/scheduled-jobs.yml`
(this document doesn't create it for you — add it yourself, reviewing it
before you commit, same as anything else that touches production
credentials):

```yaml
name: Nightly backup and retention purge

on:
  schedule:
    - cron: "0 18 * * *"   # 18:00 UTC = 02:00 Asia/Manila the next day
  workflow_dispatch: {}     # adds a manual "Run workflow" button too

jobs:
  maintenance:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12.3"

      - name: Install PostgreSQL client and Python dependencies
        run: |
          sudo apt-get update
          sudo apt-get install -y postgresql-client
          pip install -r requirements.txt

      - name: Nightly backup
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          SECRET_KEY: ${{ secrets.SECRET_KEY }}
          USE_S3_STORAGE: "True"
          BACKUP_TO_STORAGE: "True"
          AWS_STORAGE_BUCKET_NAME: ${{ secrets.AWS_STORAGE_BUCKET_NAME }}
          AWS_S3_ENDPOINT_URL: ${{ secrets.AWS_S3_ENDPOINT_URL }}
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
        run: python manage.py backup_database

      - name: Retention purge
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          SECRET_KEY: ${{ secrets.SECRET_KEY }}
        run: python manage.py purge_stale_contacts
```

Add the secrets it references under the repository's **Settings → Secrets
and variables → Actions**: `DATABASE_URL` and `SECRET_KEY` (the same values
Render uses — `SECRET_KEY` is required because Django loads the full
settings module for any `manage.py` command, even ones that don't render a
page) and the four `AWS_*` values from Section 8. If a failure alert
matters to you, add a `if: failure()` step that hits a free notification
webhook — left out here to keep the example focused.

### Option B — run both commands by hand

- **Cost**: no setup at all.
- **Trade-off**: entirely dependent on a person remembering. A backup
  routine nobody actually runs on schedule isn't a backup routine.

To run either command against production from your own computer: set
`DATABASE_URL` (and, for `backup_database`, the four `AWS_*` variables) as
one-off environment variables for that terminal session only — see
`docs/RESTORE.md`'s section on passwords and shell history for why not to
type them where they'll be saved to disk — then run
`python manage.py backup_database` or `python manage.py purge_stale_contacts`
directly.

### Which to pick

For a church this size, with one part-time ICT volunteer: **Option A.** The
one-time setup cost is small, and it removes "did anyone remember" from the
list of things that can go wrong with the only copy of the church's
membership register. Keep Option B as the documented fallback, and it's how
the restore drill in `docs/RESTORE.md` is meant to be run anyway — a restore
is not something to automate.

## 10. Verifying the deployment worked

- [ ] `https://<your-service>.onrender.com/admin/` loads a **styled** login
      page — not a 500 error, not plain unstyled HTML.
- [ ] The ICT superuser account (Section 5) logs in and sees **Groups**,
      **Users**, and four apps (Committees, Core, People, Records) on the
      admin index page.
- [ ] **Authentication and Authorization → Groups** lists exactly five:
      ICT, Secretariat, Treasurer, Board, Chairperson.
- [ ] **Committees → Committee** lists 12 committees — these come from an
      earlier migration and exist independently of `officers.csv`.
- [ ] **People → Person** is **empty** (0 records) until 23 August 2026 —
      confirms nobody has jumped ahead of the consent signing.
- [ ] After Section 7: **People → Person** lists exactly 6, each showing a
      Chairperson membership on the right committee.
- [ ] After Sections 8 and 9: a manually-triggered run of the scheduled
      workflow (or a manual command) produces a new object under `backups/`
      in the R2 bucket.
- [ ] **The sleep behaviour**: visit the site, wait 20+ minutes without
      touching it, visit again. Expect a 30–60 second wait on that second
      visit while Render wakes the free instance back up. This is expected,
      not a fault — if someone's demonstrating the system on a Sunday
      morning, warn them the first click of the day will be slow.

## 11. Moving to paid hosting later

**What stays the same**: the code, `requirements.txt`, the `Procfile`, the
environment-variable-driven configuration in `settings.py`, the Django
admin as the entire application, the data model, and the storage
abstraction — a paid plan doesn't mean re-plumbing how scans or backups are
stored, it's the same R2 bucket and the same environment variables. Render,
Neon and Cloudflare can each be upgraded independently of the other two;
none of them require touching the others. That's by design, not luck — the
project was built free-tier-first specifically so this would be true.

**What changes**:

- **Render, paid instance**: the free-tier sleep goes away — the site stays
  warm, no more morning wake-up delay. Shell access becomes available, so
  the one-off Build Command dance in Sections 5–7 is replaced by actually
  opening a shell and running the command once, directly. The Pre-Deploy
  Command feature becomes available, so `migrate` moves out of the Build
  Command into its proper place — run once per deploy, after the build
  succeeds, before traffic switches over. Render's own Cron Jobs feature
  becomes available, which can replace the GitHub Actions workflow from
  Section 9 — same two `manage.py` commands, just triggered by Render
  instead of GitHub.
- **Neon, paid plan**: removes the free tier's storage and compute ceiling,
  and the auto-suspend delay.
- **Cloudflare R2**: likely never needs to become paid for a church this
  size — a few hundred scanned forms sits well within any reasonable free
  allowance, and R2 doesn't charge for egress even past its free tier. Worth
  checking only if that ever seems close.

None of this has to happen at once, or ever, if the free tier keeps meeting
the church's needs. Upgrade whichever one first becomes a real constraint,
and leave the other two alone.
