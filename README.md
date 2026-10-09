# Jobby Hermes — Jobby v2

This is **Jobby v2**, the Hermes-connected version of Jobby. The earlier Jobby
implementation remains in our private `jobby_bot` repository. This public repo
contains the new native CLI integration and its tests, with a clean history
that excludes private candidate and application data.

A standalone, deterministic Python employment desk for an external
[Hermes CLI operator](https://github.com/NousResearch/hermes-agent).
Jobby keeps source-backed candidate facts, postings, documents and application
evidence in a private local workspace. Hermes supplies reasoning and browser
execution under the [operator skill](personal_jobby/skills/hermes-jobby-daily/SKILL.md).

This repository is a selective export from a private project, with fresh history.
It includes the `personal_jobby` package and seven synthetic test modules; candidate
state, screenshots, logs and the former application stack are excluded.

## Architecture and features

```text
Authoritative text PDF + confirmed criteria/answers
                         |
                         v
              Jobby CLI / optional local dashboard
                         |
              private SQLite + profile + artifacts
                         |
              grounded PDF/DOCX -> exact-generation QA
                         |
              manifest -> reviewed form -> durable reservation
                         |
              external Hermes browser -> one Submit click
                         |
              real confirmation -> reviewed evidence -> receipt
```

- Import candidate facts with source excerpts and SHA-256 provenance.
- Store postings; explicitly discover with JobSpy; deduplicate URL aliases and
  employer requisitions; hold unsupported salary, location or qualification claims.
- Tailor resumes and cover letters from existing facts using bounded equivalent
  keywords, with an evidence trail and immutable document generations.
- Bind visual approval, attachment manifests, document hashes and reviewed
  screenshots to the exact application attempt.
- Keep a durable daily ledger, exclusive renewable lease, attempted-submission
  cap, kill switch and persistent duplicate/uncertain-outcome locks.
- Inspect local state through sanitized CLI JSON or the optional FastAPI dashboard.

**External-browser boundary:** Python never calls model APIs, opens or fills
employer forms, or clicks Submit. The CLI records evidence and checks guards;
Hermes must inspect the employer page, supply truthful observations, review
documents and screenshots, and perform any authorized browser action. The skill
is supplied to Hermes separately; installing Jobby does not activate it or
configure Hermes authentication, browser tools or scheduling.

See the [CLI contract](personal_jobby/CLI.md),
[local runbook](personal_jobby/README.md), and
[offline system flow](personal_jobby/static/system-flow.html) for details.

## Install from a checkout

Use Linux, Python 3.10 or newer, `/usr/bin/python3`, and system timezone data for
`America/Toronto`. The launcher uses this checkout's `.venv/bin/python`; this
export has no root packaging metadata or installed console entrypoint.

```bash
git clone https://github.com/desaianm/jobby-hermes.git
cd jobby-hermes
python3 -m venv .venv
.venv/bin/python -m pip install -r personal_jobby/requirements.txt
.venv/bin/python -m personal_jobby --help
personal_jobby/bin/jobby --help
personal_jobby/bin/jobby init --help
```

Dependencies cover validation (Pydantic/FastAPI), PDF import and document
generation (PyMuPDF, python-docx, ReportLab), explicit discovery (python-jobspy)
and the optional dashboard (Uvicorn). Jobby does not load `.env` or require model
API credentials. Install and configure Hermes separately using its upstream guide.

Optionally expose the checkout launcher on PATH:

```bash
mkdir -p "$HOME/.local/bin"
ln -s "$PWD/personal_jobby/bin/jobby" "$HOME/.local/bin/jobby"
```

Ensure `~/.local/bin` is on PATH and inspect any existing `jobby` before replacing
it. The launcher resolves symlinks to this checkout, isolates Python imports and
works from other directories. Relative input paths resolve from the caller's
working directory. Use `python -m personal_jobby` from the repository root.

## Initialize private state

State defaults to `~/.local/share/jobby-personal`. To choose another workspace,
set an absolute `JOBBY_ROOT` before starting any CLI or dashboard process.
Keep it outside the checkout; the paths below are placeholders for your own
private workspace and authoritative resume:

```bash
export JOBBY_ROOT=/absolute/private/jobby-workspace
personal_jobby/bin/jobby init --pdf /absolute/private/authoritative-resume.pdf
personal_jobby/bin/jobby status --brief
personal_jobby/bin/jobby profile
personal_jobby/bin/jobby daily status
```

The importer requires a text PDF with supported Experience, Projects, Technical
Skills and Education sections and dated employment headings. Review imported
facts privately. Scanned PDFs and unsupported layouts may be rejected. Replacing
a source requires `init --pdf ... --replace`, backs up the profile and invalidates
live materials. Private input files and their ancestors must be free of symlinks.

Initial criteria are provisional. Confirm criteria, work eligibility and current
submission intent through the optional local dashboard before application work.
Phone is entered only through its private masked form; it is omitted from CLI
profile output and generated documents. Other profile facts remain private even
when JSON output is phone-sanitized. Keep them out of public diagnostics.

For local review, from the checkout with the same `JOBBY_ROOT`:

```bash
.venv/bin/python -m uvicorn personal_jobby.app:create_app --factory --host 127.0.0.1 --port 8090 --no-access-log
```

Open `http://127.0.0.1:8090` on the same machine. The dashboard has no account
login; use trusted local access. Remote access and secure phone entry require
separately configured authenticated HTTPS, described in the runbook.

## Evidence and submission guards

Tailoring cannot invent skills, metrics, dates, experience duration or
qualifications. Automatic document checks do not constitute visual QA: the
operator must review current PDFs, DOCX documents and previews before `approve`.
Approval binds the generation, source/settings/posting fingerprints and artifact
hashes; changes invalidate it. DOCX pagination needs Word or LibreOffice review.

An attempt captures the approved generation and actual attached filenames/hashes,
including an explicit cover-letter decision. Before a daily submit, ingest an
actually reviewed filled-form PNG with phone masked **before capture**; the
`--phone-redacted` flag attests review and does not redact pixels. Then
`daily begin-submit` durably reserves the exact posting/attempt and Toronto-day
budget before one external click. It checks the live lease, policy, intent,
confirmed criteria/answers, eligibility, document approval and duplicate locks.
Uncertain outcomes stay locked across runs and days and must never be blindly
retried. Closing or expiring a run does not release an unresolved reservation.

Only actual employer receipt evidence records `applied`. Hermes-managed receipts
require the exact attempt and reviewed employer-confirmation screenshot, preserve
submitted document copies, and use a timezone-aware timestamp. A manual reported
receipt without an attempt explicitly records documents unknown. An upload,
filled draft, reservation or configured schedule is not a completed application.

Daily operation is **disabled by default**, with no cron ID or schedule. Obtain
candidate authorization and manually configure and verify an external Hermes
scheduler before recording its configuration. `daily configure` only records
that information; it does not install cron or prove execution. Clearing desired
submission is the kill switch for new reservations. Follow the operator skill
and CLI contract for the full guarded sequence.

## Privacy and limitations

Private directories use 0700 and files 0600; state is unencrypted at rest.
Keep profiles, answers, source resumes, databases, manifests, screenshots, logs
and backups outside version control. `.gitignore` excludes common state and
artifact paths, including databases, `profile/` and `.venv`; it cannot sanitize
arbitrary files or prevent forced staging.

Current eligibility rules cover permanent full-time roles with evidenced
Toronto/GTA hybrid or Canada remote arrangements and employer-posted CAD annual
base salary. Other policies require implementation review. Discovery may be
blocked, empty or incomplete and does not replace employer verification. Unknown
required answers, login/MFA/CAPTCHA, assessments and personal attestations need
operator or human review. This is not a universal ATS adapter. Synthetic tests
demonstrate local control behavior, not completed real applications.

## Verification

Use synthetic fixtures and temporary workspaces only. Install development tools
into the checkout environment if needed:

```bash
.venv/bin/python -m pip install pytest httpx Pillow
.venv/bin/python -m pytest -q tests
.venv/bin/python -m compileall -q personal_jobby tests
node --check personal_jobby/static/app.js
```

The seven modules use temporary candidate state, synthetic PDFs/PNGs and mocked
discovery. Launcher tests require this checkout's `.venv/bin/python`; Node.js is
only needed for the JavaScript syntax check. For launcher JSON smoke checks,
set `JOBBY_ROOT` to a fresh temporary workspace and run `status --brief` or
`daily status` from another working directory. Development verification must not
read a real candidate workspace, invoke live discovery or submit applications.
