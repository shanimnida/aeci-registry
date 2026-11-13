# Deploying AEGIS (the AECI registry)

**AEGIS** — the Avdei Elohim Growth Information System — is the church's
member registry. This is the walkthrough for putting it online: code in the
GitHub repo **`aeci-registry`**, database in the Neon project **`aegis`**,
application running as the Render service **`aeci-registry`**, scanned forms
in Cloudflare R2. Those are the three services' actual names — use them
consistently; "the app," "the database," "the site" all mean the same thing
throughout this document, and each has exactly one name. It is written for
the ICT Committee of Avdei Elohim Church Inc., assuming whoever reads it is
comfortable with computers but has never deployed a Django application
before.

**How to read this**: every section leads with a numbered list of what to
click or type. The explanation of *why* — what it protects against, what it
means if it goes wrong — comes after the steps, not before. Skip straight to
the numbered list if you just need to get moving; come back for the
explanation when something breaks.

Read the whole thing once before you start. Some steps (Section 9,
Cloudflare R2) don't have to happen on day one — the document says exactly
when they become necessary.

## Two things before anything else

**Do not put real member data into this system until the data privacy
consent clause has been signed.** That's scheduled for the Sunday service on
**23 August 2026**. The current paper profiling form has no consent clause
for the sensitive information it collects (civil status, birthdate, home
address, children's data, religious membership — all "sensitive personal
information" under the Data Privacy Act of 2012, RA 10173). Deploying the
system *empty* before that date is not just fine, it's encouraged: it's the
best way to find deployment problems before anything of value is at risk.
Sections 1 through 8 of this document can all happen before 23 August.
Section 7's Secretariat and Board accounts can be created and tested against
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

## If something's broken: check these five things first

This is the shortlist for a live-fire outage at 9pm, before you go reading
whole sections. Everything here is explained fully further down.

1. **The site answers every single page with a 400 error.** This is
   `ALLOWED_HOSTS` — either never set, or set to the wrong hostname. It is a
   one-field fix. See Section 6.
2. **The site loads but with no styling at all** — bare links and forms, no
   layout, no AEGIS header. `collectstatic` did not run. Check the Build
   Command still matches Section 4, step 5.
3. **Every page fails with a 500 error, specifically after logging in or on
   any page that touches a Person record.** `DATABASE_URL` is missing or
   wrong. Re-check it against the Neon connection string from Section 3.
4. **A scan upload fails outright, or "succeeds" and then can't be found
   again.** `USE_S3_STORAGE` is `False` (or R2 credentials are wrong). See
   Section 9.
5. **You suspect the nightly backup hasn't run in a while.** There is no
   automatic alert for this — it is a known, real gap (see Section 10). Check
   the repository's **Actions** tab on GitHub directly; don't assume silence
   means success.

## Contents

1. [Before you start](#1-before-you-start)
2. [Getting the code to GitHub](#2-getting-the-code-to-github)
3. [Neon — the database](#3-neon--the-database)
4. [Render — the application](#4-render--the-application)
5. [First deploy](#5-first-deploy)
6. [Setting ALLOWED_HOSTS](#6-setting-allowed_hosts)
7. [The four role groups and the first accounts](#7-the-four-role-groups-and-the-first-accounts)
8. [Seeding the officers from the CSV](#8-seeding-the-officers-from-the-csv)
9. [Cloudflare R2 — storage for scanned forms](#9-cloudflare-r2--storage-for-scanned-forms)
10. [Scheduling the two jobs](#10-scheduling-the-two-jobs)
11. [Verifying the deployment worked](#11-verifying-the-deployment-worked)
12. [Moving to paid hosting later](#12-moving-to-paid-hosting-later)

---

## 1. Before you start

The stack is: **Render** (service `aeci-registry`) runs the application,
**Neon** (project `aegis`) hosts the PostgreSQL database, **Cloudflare R2**
stores scanned form images. All three have free tiers, chosen deliberately
so the church can run this at no cost for as long as that keeps working, and
move any one of them to a paid plan later without rewriting anything
(Section 12).

**Free-tier terms change.** The numbers and features described in this
document (storage limits, sleep behaviour, what requires a paid plan) are
accurate as of when this was written. Check each provider's current pricing
page when you actually sign up — a "free tier" is a business decision the
provider can revise.

You will need accounts on:

- **GitHub** (to hold the `aeci-registry` repository)
- **Render** (to run the `aeci-registry` service)
- **Neon** (for the `aegis` database project)
- **Cloudflare** (for R2 — needed by Section 9, but worth creating now)

Create every one of these under an email address **the church controls**,
not the personal email of whichever volunteer is doing this today — for
example, an official church Gmail or Workspace address that the ICT
Committee as a body can get into. If a personal account is used instead, the
day that volunteer becomes unreachable, the church loses the ability to
redeploy the site, rotate a leaked credential, or even see why it went down.
This is the single most important housekeeping decision in this whole
document, and it costs nothing to get right the first time.

## 2. Getting the code to GitHub

1. On GitHub, create a **new, private** repository named **`aeci-registry`**
   (Settings you'll want: private, no README/license/gitignore
   auto-generated — this project already has those).
2. From this project's folder, add the new repository as a remote and push:

   ```
   git remote add origin https://github.com/<your-org-or-account>/aeci-registry.git
   git push -u origin main
   ```

   (Substitute whatever branch you intend to run in production — the URL
   GitHub gives you after creating the repo has the exact remote-add command
   pre-filled; use that if it differs from the example above.)

3. Confirm on GitHub's web UI that the files are there and the repository
   shows a padlock/"Private" label.

**Why private**, given the codebase has no secrets committed to it (`.env`
is git-ignored — see `.gitignore` — and nothing else in the repo is a
credential): `data/officers.csv` holds the real names of committee
chairpersons and is deliberately **not** git-ignored, because it's
governance data (who holds what office), not personal member data. A public
repository would put that list, and this project's own documentation of
exactly how its access-control and privacy rules work, in front of anyone on
the internet. Neither is a reason to panic, but neither needs to be public
either.

## 3. Neon — the database

1. Sign up at Neon, create a new **project** named **`aegis`**. Pick a region
   close to where the site will mostly be used (a Singapore or other nearby
   Asia-Pacific region, if offered, will feel faster than a US one — this is
   a latency preference, not a correctness requirement).
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

3. **Note the Postgres major version this project is running** — the same
   Connection Details panel (or the project's Settings page) states it, e.g.
   "PostgreSQL 18." Write it down; Section 10 needs it.
4. Save the connection string somewhere safe **temporarily** — a password
   manager entry, not a chat message, a text file on the Desktop, or an
   email to yourself. You'll paste it into Render in Section 4 as
   `DATABASE_URL`, and it won't need to live anywhere else after that.

**Note honestly**: Neon's free tier auto-suspends the database after a
period of inactivity, which adds a short delay to the first query after it's
been idle — separate from, and in addition to, Render's own sleep behaviour
described in Section 11. Check Neon's current free-tier limits (storage,
compute hours) on their pricing page; they're a separate thing from what's
described here and are more likely to change.

## 4. Render — the application

1. Sign in to Render with your GitHub account. When it asks which
   repositories to grant access to, choose **only `aeci-registry`**, not "all
   repositories" — no reason to give Render more reach than it needs.
2. **New → Web Service**, select the `aeci-registry` repository. Name the
   service **`aeci-registry`** — this is what determines the hostname
   Section 6 needs, so use this exact name if it's available.
3. **Runtime**: Python. Render reads the Python version from this project's
   own `runtime.txt` (`python-3.12.3`) automatically — nothing to set here.
4. **Root Directory**: leave blank. The project lives at the repository
   root.
5. **Build Command**:

   ```
   pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate --noinput
   ```

6. **Start Command**:

   ```
   gunicorn aeci.wsgi
   ```

   (matches the `Procfile`'s `web:` line.)
7. **Instance Type**: Free.
8. **Environment Variables** — add these now, under the service's
   Environment tab. Paste-ready values for the five variables a first deploy
   actually needs:

   | Variable | Paste this |
   | --- | --- |
   | `SECRET_KEY` | A freshly generated random value — see below. |
   | `DEBUG` | `False` |
   | `ALLOWED_HOSTS` | **Leave this one out for now.** You cannot know the right value until Render assigns the hostname, which only happens after this first deploy. Section 6 tells you exactly what to do, right after you click Create Web Service below — don't guess it here. |
   | `DATABASE_URL` | The Neon connection string from Section 3, `sslmode=require` intact. |
   | `USE_S3_STORAGE` | `False` for now; flip to `True` once you complete Section 9. |

   Do not click Create Web Service yet — finish this step first.

   **Generating a real `SECRET_KEY`**: on your own computer, in any Python 3
   installation (this doesn't need the project's own environment set up),
   run:

   ```
   python -c "import secrets; print(secrets.token_urlsafe(50))"
   ```

   Paste the output — one line of random characters — into Render's
   `SECRET_KEY` variable. Never commit it to the repository, never paste it
   into an email or chat with anyone outside the church, and never reuse it
   for anything else. **Never** use the value `dev-only-not-for-production`
   from `.env.example`.

**Why each build-command step matters, and what breaks if you skip it**:

- `pip install` — installs Django and everything else in `requirements.txt`.
- `collectstatic --noinput` — **do not skip this.** The project serves
  static files (including AEGIS's own admin CSS and JavaScript) through
  WhiteNoise's `CompressedManifestStaticFilesStorage` (`aeci/settings.py`),
  which raises an error for any static file reference that isn't in a
  manifest built by `collectstatic`. Skip this step and the entire
  application breaks — see item 2 in the troubleshooting list above.
- `migrate --noinput` — this is normally what the `Procfile`'s `release:`
  line is for (Heroku-style convention: run once, after build, before the
  new version takes traffic). **Render's free instance type doesn't run
  that Procfile line or its own equivalent "Pre-Deploy Command" feature —
  both require a paid instance type.** Folding `migrate` into the Build
  Command is the free-tier workaround, and it's safe to run on every single
  deploy: Django tracks which migrations have already applied and skips
  them.

**What each environment variable actually controls** — this is the complete
list of everything `aeci/settings.py` reads from the environment, what to
set it to, and what happens if it's wrong or left out:

| Variable | Set it to | If it's wrong or missing |
| --- | --- | --- |
| `SECRET_KEY` | A freshly generated random value (see above). **Never** the value `dev-only-not-for-production` from `.env.example`. | Missing: the application will not start at all. Set to the checked-in dev value, or any value anyone outside the church has seen: sessions, password-reset tokens and CSRF protection all depend on this staying secret — reusing a value that's sat in a public place defeats all three. |
| `DEBUG` | `False` | Missing: defaults to `False` anyway (the code's own default), so this is safe to omit, but set it explicitly so nobody has to go read the source to know. Set to `True` by mistake: Django shows a full error page — source code, settings, other environment variables — to any visitor who triggers an error, **and** the entire production-hardening block at the bottom of `settings.py` (forced HTTPS, secure cookies, HSTS) is skipped, because it's all gated on `if not DEBUG`. This is the single most damaging setting to get wrong. |
| `ALLOWED_HOSTS` | The exact hostname Render assigns, e.g. `aeci-registry.onrender.com` — set it in Section 6, **after** your first deploy, not before. | Missing or wrong: Django refuses every request with a 400 "DisallowedHost" error. The server is running fine; it just won't answer anyone, including you. This is expected right after your very first deploy — see Section 6. |
| `DATABASE_URL` | The Neon connection string from Section 3, `sslmode=require` intact. | Missing: application won't start. Wrong host or password: application starts, but every page that touches the database fails with a 500 error. |
| `USE_S3_STORAGE` | `False` for now; `True` once you complete Section 9. | See Section 9 — this is what makes uploaded scan files survive a redeploy, and it must be right before the first real scan is uploaded, not eventually. |
| `AWS_STORAGE_BUCKET_NAME`, `AWS_S3_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | From Section 9. | Only read at all when `USE_S3_STORAGE=True`. Missing while it's `True`: application won't start. Present but wrong: application starts fine, but every scan upload or view fails. |
| `PG_DUMP_PATH` | Leave unset on Render. | Only affects `backup_database`, which — see Section 10 — does not run on Render in this plan, so it has no effect here either way. |
| `BACKUP_TO_STORAGE`, `BACKUP_RETENTION_DAYS` | Leave unset on Render. | Same reasoning as `PG_DUMP_PATH` — these matter wherever `backup_database` actually executes (Section 10), which in this plan isn't Render. |

## 5. First deploy

1. Click **Create Web Service** and watch the build log.
2. Confirm the build log shows, in order: dependencies installing,
   `collectstatic` running, then `migrate` running.
3. Once the deploy says "Live," **do not visit the site yet** — go straight
   to Section 6 and set `ALLOWED_HOSTS` first. Visiting now will show a 400
   error; that's expected and explained there, not a sign anything is wrong.

**What `migrate` did automatically, that you don't do by hand**: it both
created every table the application needs *and* created the five role
groups (ICT, Secretariat, Board, Chairperson) with their
permissions already assigned, via a migration
(`core/migrations/0002_create_groups.py`) that ships with the code. You
don't do anything separate to get the groups — they exist the moment
`migrate` finishes, ready for Section 7.

## 6. Setting ALLOWED_HOSTS

1. On the Render dashboard, at the top of the `aeci-registry` service page,
   copy the exact hostname Render assigned, e.g. `aeci-registry.onrender.com`.
2. Go to the **Environment** tab and add `ALLOWED_HOSTS` set to that exact
   value.
3. Save. Render redeploys automatically — wait for it to finish.
4. Now visit `https://<your-hostname>/admin/`. You should see the AEGIS
   login page — the AEGIS name in the header, normal formatting (fonts,
   colours, layout), not a bare unstyled page and not a 400 error.

**Why this has to happen in this order, and not with `ALLOWED_HOSTS` set
before the first deploy**: the value this variable needs is the hostname
Render itself assigns, and Render only assigns it once the service exists.
Guessing it, or setting it before you have the real value, produces exactly
the outcome in item 1 of the troubleshooting list at the top of this
document: the server runs fine, but Django's `ALLOWED_HOSTS` check refuses
every single request with an uninformative 400 "DisallowedHost" error before
it ever reaches the application. That looks like total breakage — nothing
loads, no error page with useful detail, just a blank refusal — and it is
one field away from fixed. If you ever see this after everything was working
before (a service rename, a Render-side hostname change), come back to this
section.

## 7. The four role groups and the first accounts

**Creating the first ICT superuser.** Render's free instance type does
**not** provide shell or SSH access — that's a paid-plan feature, along with
"one-off jobs." (This differs from what earlier planning notes for this
project assumed; it's confirmed directly against Render's own documentation,
and it's worth knowing plainly rather than discovering it when a shell tab
that should be there isn't.) The workaround uses the same Build Command
mechanism from Section 4, plus a feature Django itself ships with —
non-interactive superuser creation from environment variables:

1. In Render's **Environment** tab, temporarily add three variables:
   `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL`, and
   `DJANGO_SUPERUSER_PASSWORD` (a real, strong, unique password — not one
   reused anywhere else).
2. Edit the **Build Command** to add, at the end:
   `&& python manage.py createsuperuser --noinput`
3. Save. Render redeploys automatically. Watch the build log for "Superuser
   created successfully."
4. Log in at `/admin/` with that username and password. You should land on
   the AEGIS home screen, with a sidebar organised into **Registry**
   (People, Households), **Committees**, **Records**, and
   **Administration** (Users, Groups).
5. **Clean up immediately, in this order:** first edit the Build Command to
   remove the `&& python manage.py createsuperuser --noinput` you added —
   leaving it in place will make the *next* deploy fail outright, because
   the command errors out on a user that already exists, which blocks every
   future deploy until someone notices and fixes it. Then delete the
   `DJANGO_SUPERUSER_PASSWORD` variable (or overwrite it with throwaway
   text) so the real password stops sitting in the dashboard in plain text.
   Save once more to trigger a final deploy with the Build Command back to
   its normal, permanent form from Section 4.
6. Because a Django superuser bypasses permission checks entirely, this
   account already has full access — you do not additionally need to put it
   in the "ICT" group for it to work, though you're welcome to for clarity's
   sake once ordinary (non-superuser) ICT accounts exist too.

**Common mistake**: skipping step 5 above. If a *later* deploy suddenly
fails in the build log with something like "that username is already
taken," this is why — go remove the `createsuperuser` clause from the Build
Command.

The five groups already exist after Section 5 — they're created by a
migration, not something you build by hand. What's left is deciding who
goes in which one, and creating their logins.

| Group | Who, in this church | What they can do |
| --- | --- | --- |
| **ICT** | The ICT Committee members who administer the system. | Everything — including the only group that can create new user accounts (nobody else can), and the only group that can link a login to a Person record (see below). |
| **Secretariat** | The Secretariat staff who encode member records day to day. | Create and edit Person records, manage households, upload scans. Cannot create logins, and cannot set someone's status to `MEMBER` without a recorded approver. |
| **Board** | The Pastor and Board members. | View full person records, appoint officers and chairpersons, approve membership status changes, read the audit log. |
| **Chairperson** | The people chairing individual committees (Section 8 seeds six of them from the current officers list). | See only name, mobile number and email for members of *their own* committee — nothing else, and no visibility into any other committee. |

**Creating an account** (do this from the AEGIS home screen, logged in as
the ICT superuser from above, or as any other account already in the ICT
group):

1. **Administration → Users → Add user.** Set a username and a temporary
   password.
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

**Linking a Chairperson's login to their Person record.** A Chairperson's
"own committee only" view works by matching their logged-in account to their
existing `Person` record. As of commit `864985b`, this is a normal admin
action, not a code workaround — do this instead of anything involving the
Build Command or `manage.py shell`:

1. Log in as ICT (or superuser) and open **Registry → People**, then open
   the Chairperson's own Person record.
2. Scroll to the **Login** section near the bottom of the form — this
   section only appears for ICT and superuser accounts; Secretariat and
   everyone else never see it, by design (`core/groups.py`'s `is_ict`
   check), because linking a login is an access-granting action and stays
   separate from day-to-day record-keeping.
3. Use the **User** field (an autocomplete — start typing the username) to
   select the account you created above for this person.
4. Save.

If you skip this, the Chairperson login still works, but their committee
screens show **zero rows** instead of their roster — it fails safe (nothing
leaks to them), it just doesn't do anything useful until linked.

## 8. Seeding the officers from the CSV

1. Temporarily append `&& python manage.py seed_officers` to the Build
   Command.
2. Deploy. Check the build log for a line like `Created 6 person(s) and 6
   committee role(s) from 6 row(s).` followed by `All rows imported
   cleanly.`
3. Remove the clause from the Build Command, redeploy once more.
4. Repeat this whenever `data/officers.csv` changes — for example, when a
   nickname gets resolved to a full legal name.

Verify in the admin: **Registry → People** should list 6 people;
**Committees → Committee memberships** should show each of them as
Chairperson of their committee.

`data/officers.csv` lists the current committee chairpersons, resolved by
the ICT Committee (some officers known only by nickname are deliberately
left out until their full names are confirmed — see the comment at the top
of `committees/management/commands/seed_officers.py`). Running
`seed_officers` creates a `Person` record and a `CommitteeMembership` for
each row. **It does not create login accounts** — that's the separate,
manual step in Section 7. A seeded Person can exist perfectly well with
nobody able to log in as them, and that's the normal state for most of
these six people.

The command is idempotent — safe to run again as names get corrected — but
if any single row fails validation, the **entire command** exits with an
error and nothing from that row is saved. Because of that, don't wire this
permanently into the Build Command: a future typo in the CSV would then
block every deploy, not just fail the seeding. Instead, run it the same
one-off way as the superuser step, above.

## 9. Cloudflare R2 — storage for scanned forms

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

**This becomes necessary the moment the first scanned paper form is
uploaded through the admin, not before** — none of Sections 1–8 upload any
files, so it's fine to do this later, right up until someone is about to
scan and upload the first form.

**What breaks if it's skipped, and how fast**: `USE_S3_STORAGE=False` means
scan uploads go to local disk on the Render instance, and on a free instance
that disk does not survive. This is not a slow-motion risk you have days to
notice — Render's free tier spins the instance down after about 15 minutes
with no traffic (the same window Section 11's sleep-behaviour check uses),
and every spin-down, plus every redeploy, wipes local disk. A scan uploaded
this evening can be gone before the same evening is over, the next time
anyone reopens the site after a short gap — not at some distant future
redeploy. The database record (`FormScan`) survives; it just points at a
file that no longer exists, and nothing in the interface warns you when
this happens — the loss is silent. Treat `USE_S3_STORAGE=False` as "scan
uploads do not actually work yet," not "scan uploads work for now."

**Storage is not separated from backups, and that's worth knowing plainly.**
Section 10 uploads database backups into this exact same bucket, under a
`backups/` key prefix. The prefix keeps filenames from colliding — it is
**not** an access boundary. The R2 API token from step 2 above is scoped to
the whole bucket, not to one prefix inside it, so anything holding that
token (the Render service, and the GitHub Actions workflow in Section 10)
can read and write both members' scanned forms and full database dumps.
There is currently no separate bucket or separate credential for backups. If
this token ever leaks, both are exposed together, not just one. Real
separation — a second bucket with its own scoped token, used only for
backups — is possible on Cloudflare's side but is not set up by this
document; it would need a small addition to `aeci/settings.py` (a second
storage backend) to actually use it, which is a code change outside this
document's scope.

## 10. Nightly backups, restore verification, and retention

The repository includes `.github/workflows/scheduled-jobs.yml`. It runs
daily at 18:00 UTC (02:00 Asia/Manila the following day) and supports manual
runs from **Actions → Nightly backup and restore check → Run workflow**.
Scheduled workflows use the repository's default branch, currently
`build/core-registry`. Keep this workflow on that branch.

Before enabling it, add these repository **Actions secrets** through GitHub's
Settings → Secrets and variables → Actions:

- `DATABASE_URL`: the production database in Neon project **aegis**, not the
  older **aeci** project. Use its direct connection for `pg_dump`.
- `AWS_STORAGE_BUCKET_NAME`
- `AWS_S3_ENDPOINT_URL`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

The storage settings must point to the same private, persistent bucket used
by the hosted scans. No production Django `SECRET_KEY` is needed by this
workflow. Missing secrets cause an explicit failed run.

Each run installs PostgreSQL 18 client tools (the production server major
version last verified), creates a compressed database backup, requires
remote storage, and downloads the uploaded object to check its SHA-256.
It then restores the backup with `ON_ERROR_STOP` into a fresh local
PostgreSQL service on the runner and checks the core tables. The restore
script refuses non-local, incorrectly named, or nonempty databases.
It never restores into the source database. No member register is uploaded
as a GitHub artifact, and SQL contents are suppressed in logs.

The job also reads each referenced scan from remote storage, runs the
existing contact-retention command, and removes expired login counters.
A failed backup, checksum, restore, or scan check stops subsequent steps.
Existing backup retention keeps the newest backup even if it is stale.

After adding secrets, run the workflow manually and inspect its results.
Only a successful run establishes that the hosted backup and restore path
works. Merely committing this workflow does not establish a backup.
GitHub Actions notifications should be enabled for workflow failures.
GitHub may disable scheduled workflows in public repositories after 60
days without activity; periodically check that the schedule remains active.
Backups contain the register and need the same access controls as scans.

To run a backup manually with production settings already supplied in the
environment, use:

```shell
python manage.py backup_database --require-remote --verify-upload
python manage.py verify_scan_storage
```

See `docs/RESTORE.md` for recovery and the isolated restore-check script.

### Tests before deployment

`.github/workflows/tests.yml` runs the full suite on PostgreSQL 18, checks
for missing migrations, collects static files, and runs Django's production
configuration checks. The isolated test settings use a fast password hasher;
never use `aeci.test_settings` on the hosted web service.

Protect `build/core-registry` with the required status check
**PostgreSQL tests**, and merge changes after that check succeeds. Render
can additionally use **After CI Checks Pass** in the service's Auto-Deploy
setting. Confirm that setting in the Render dashboard when changing the
deployment policy.

### Login protection

Login attempts use shared PostgreSQL counters. Five unsuccessful attempts
against an account, or fifty against one socket IP within fifteen minutes,
cause a fifteen-minute cooldown. Existing signed-in sessions keep working.
The form reports when a cooldown applies, including for nonexistent logins.
Successful logins reset the account counter and retain the IP budget.
The counters store HMAC digests rather than submitted usernames or IPs.

`LOGIN_ACCOUNT_FAILURE_LIMIT` and `LOGIN_IP_FAILURE_LIMIT` can override the
thresholds. Client-supplied forwarded headers are ignored. A proxy or shared
network can share the IP budget, so account-level limits provide the main
protection. Expired counters are removed by the nightly job.

## 11. Verifying the deployment worked

- [ ] `https://<your-service>.onrender.com/admin/` loads the AEGIS login
      page — not a 400, not a 500, not a bare unstyled page.
- [ ] The ICT superuser account (Section 7) logs in and sees a sidebar with
      **Registry**, **Committees**, **Records**, and **Administration**
      sections.
- [ ] **Administration → Groups** lists exactly four: ICT, Secretariat,
      Board, Chairperson.
- [ ] **Committees → Committee** lists 12 committees — these come from an
      earlier migration and exist independently of `officers.csv`.
- [ ] **Registry → People** is **empty** (0 records) until 23 August 2026 —
      confirms nobody has jumped ahead of the consent signing.
- [ ] After Section 8: **Registry → People** lists exactly 6, each showing a
      Chairperson membership on the right committee.
- [ ] After Sections 9 and 10: a manually-triggered run of the scheduled
      workflow (or a manual command) produces a new object under `backups/`
      in the R2 bucket.
- [ ] **The sleep behaviour**: visit the site, wait 20+ minutes without
      touching it, visit again. Expect a 30–60 second wait on that second
      visit while Render wakes the free instance back up. This is expected,
      not a fault — if someone's demonstrating the system on a Sunday
      morning, warn them the first click of the day will be slow.
- [ ] **Backup monitoring**: enable GitHub Actions failure notifications and
      check periodically that the nightly schedule remains active (Section 10).

## 12. Moving to paid hosting later

**What stays the same**: the code, `requirements.txt`, the `Procfile`, the
environment-variable-driven configuration in `settings.py`, the AEGIS admin
interface as the entire application, the data model, and the storage
abstraction — a paid plan doesn't mean re-plumbing how scans or backups are
stored, it's the same R2 bucket and the same environment variables. Render,
Neon and Cloudflare can each be upgraded independently of the other two;
none of them require touching the others. That's by design, not luck — the
project was built free-tier-first specifically so this would be true.

**What changes**:

- **Render, paid instance**: the free-tier sleep goes away — the site stays
  warm, no more morning wake-up delay. Shell access becomes available, so
  the one-off Build Command dance in Sections 7–8 is replaced by actually
  opening a shell and running the command once, directly. The Pre-Deploy
  Command feature becomes available, so `migrate` moves out of the Build
  Command into its proper place — run once per deploy, after the build
  succeeds, before traffic switches over. Render's own Cron Jobs feature
  becomes available, which can replace the GitHub Actions workflow from
  Section 10 — same two `manage.py` commands, just triggered by Render
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
