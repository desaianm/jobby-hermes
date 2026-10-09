# Native Jobby CLI for Hermes

Install the source launcher using the [root setup guide](../README.md#install-from-a-checkout).
An optional `~/.local/bin/jobby` symlink points to `personal_jobby/bin/jobby`;
once installed on PATH, it works from any working directory. Relative input
paths resolve from your working directory. The generic launcher resolves its own
symlinks and runs the repository `.venv/bin/python -I`, adding only the trusted
repository to the import path. It does not read `.env` or invoke model APIs.

No extra integration service or HTTP calls are needed for these operations.
The backend app is not started. Hermes uses its existing browser tools to inspect
employer postings, fill forms and click Submit after authorization. The CLI
provides local preflight guards and records; it is not a universal ATS submitter.

## Output and commands

Run `jobby --help`, `jobby COMMAND --help`, and `jobby daily ACTION --help`.
Successful data commands emit one sanitized JSON document on stdout and exit 0.
Help is plain text and exits 0. Operational failures exit 1 with a generic stderr
message withholding input values; syntax errors exit 2 and may quote arguments.
Never put private phone values, credentials or review tokens in argv. Check exit
status before parsing the entire stdout document. Stop dependent work on failure.

| Command | Exact usage | Purpose |
| --- | --- | --- |
| Status | `jobby status --brief` | Fetch active settings, counts, job summaries and executor capability |
| Profile | `jobby profile` | Public source facts and known answers, with `phone_present` only |
| Show | `jobby show JOB_ID` | Sanitized `job`, `events`, `materials`, `current_artifact_directory` |
| Initialize | `jobby init --pdf /private/source.pdf [--replace]` | Import authoritative source; replacement invalidates documents and backs up profile |
| Add | `jobby add /private/posting.json` or `jobby add -` | Store posting; `-` reads JSON stdin |
| Search | `jobby search 'TERM' --limit 10 --location 'LOCATION' --hours-old 72 [--remote]` | Discovery only; verify against the employer |
| Fit | `jobby fit JOB_ID --evidence /private/fit.json` | Record typed, source-grounded arrangement, employment and qualifications review |
| Prepare | `jobby prepare JOB_ID` | Generate grounded immutable artifacts; returns pending visual review |
| Approve | `jobby approve JOB_ID --review /private/review.json` | Record actual operator visual QA of the exact current generation |
| Attempt | `jobby attempt JOB_ID --manifest /private/manifest.json` | Capture exact approved attached documents; does not submit |
| Screenshot | `jobby screenshot ATTEMPT_ID /private/image.png --kind filled_form --qa-note 'ACTUAL_SAFE_QA_NOTE' --phone-redacted` | Ingest an already sanitized, visually reviewed PNG |
| Receipt | `jobby receipt JOB_ID --attempt-id ATTEMPT_ID --timestamp 'ACTUAL_AWARE_TIMESTAMP' --text 'ACTUAL_SANITIZED_CONFIRMATION' --url 'ACTUAL_PUBLIC_CONFIRMATION_URL'` | Record real existing confirmation; does not submit |

Receipt needs an aware timestamp and actual text or public URL evidence; either
`--text` or `--url` can be omitted. Omitting `--attempt-id` records a user-reported
receipt with documents unknown; Hermes must use its captured attempt.
Screenshot kind is `filled_form` or `employer_confirmation`.

## Facts, evidence and privacy

Fetch `status` settings each run instead of assuming salary, location, employer
exclusions or submission intent. `show` and `profile` supply posting and candidate
source facts directly. Source hashes and excerpts retain provenance; inspect the
authoritative documents privately when necessary. Do not fabricate requirements,
qualifications, answers, salary evidence, QA or confirmation. Tailoring permits
only existing bounded equivalent keywords supported by source facts; it cannot
add a missing skill, metric, experience duration or qualification.

`profile` returns `{ "profile": { ... }, "phone_present": true|false }`.
`profile.answers.phone` is omitted entirely. Other known facts and answers are
allowed. All command results use the shared recursive phone/credential filter.
Secret fields are omitted; recognizable credential text and sensitive URL
query/fragment values are masked. Supported ATS posting identifiers and ordinary
synthetic reserved-example URLs remain intact; this is not generic ATS validation.
Posting ingestion stores only the filtered snapshot when filtration is needed,
with `original_source.privacy_filtration` recording the input SHA-256, no raw
retention, and that the snapshot is not exact source evidence. Unchanged source
facts and structured salary JSON remain exact. Salary raw and arrangement/employment
excerpts that would require filtration are rejected; supply a clean public source
excerpt rather than treating rewritten text as proof. Receipt text/URLs and event
notes are filtered records, not a retained raw confirmation. Source resume files
and the private phone answer retain their existing private storage semantics;
this filter is not an encryption or screenshot-pixel privacy guarantee.
Private state defaults to `~/.local/share/jobby-personal` (override with absolute
`JOBBY_ROOT` before process startup; relative roots fail before state creation); do not dump
candidate files into chat or logs. Phone goes through the existing private form
handling path. Mask/remove it in the browser **before capture**, then visually
inspect the PNG. `--phone-redacted` records that attestation, not pixel redaction.
PNG text metadata is rejected; strip it privately before ingestion.

`show.materials` is the current metadata, including QA state, generation ID,
review token, fingerprints and artifact hashes when available. The resolved
`current_artifact_directory` points to `artifacts/JOB_ID/generations/GENERATION_ID`,
never an old flat artifact folder. It is null when no safe current directory
exists. `stale`, `invalidated` and `generation_in_progress` are explicit QA states;
a path's existence alone is not authorization to use its documents. Changes to
profile/source, settings, posting or artifact bytes invalidate approval through
the existing fingerprints. Regenerate and review again.

Fit and review JSON files must be at most 16000 bytes. Files and all ancestor
directories must be free of symlinks. They use the same `app.Fit` and
`app.Approval` validation as the API, rejecting unknown keys. No tokens in argv.

Fit shape (substitute actual evidence; these strings are placeholders):

```json
{
  "arrangement": "hybrid",
  "arrangement_evidence": "EXACT_EMPLOYER_LOCATION_AND_ARRANGEMENT_EXCERPT",
  "employment_type": "permanent_full_time",
  "employment_evidence": "EXACT_EMPLOYER_EMPLOYMENT_EXCERPT",
  "qualifications_reviewed": true,
  "qualification_review_note": "ACTUAL_REQUIREMENTS_REVIEW_AGAINST_CANDIDATE_SOURCE_FACTS"
}
```

`arrangement` and `employment_type` are required. Arrangement values:
`unknown|hybrid|remote|onsite`. Employment values:
`unknown|permanent_full_time|contract|temporary|part_time`. Evidence and note strings
are optional, default empty, max 2000 characters each; `qualifications_reviewed`
defaults false. Required qualifications need a nonempty source-grounded note;
setting the boolean cannot bypass missing qualifications. Location/arrangement
and permanent full-time evidence must match the posting. Fit re-assesses
eligibility, records `fit_verification`, preserves original source and preserves
statuses outside `discovered|needs_review|eligible`, including terminal states.

Review shape, populated **after actually reviewing** the current PDF, DOCX and
preview privately:

```json
{
  "reviewer": "ACTUAL_OPERATOR",
  "note": "ACTUAL_VISUAL_QA_FINDINGS",
  "review_token": "EXACT_CURRENT_64_LOWERCASE_HEX_TOKEN"
}
```

All three fields are required. Reviewer length 1–250; note length 1–2000;
review token must match the exact current generation. `approve` neither performs
QA nor bypasses stale-token rejection. Do not copy these placeholder claims into
records as if review occurred.

`daily verify-job` evidence shape:

```json
{
  "salary": {
    "raw": "EXACT_EMPLOYER_CAD_ANNUAL_BASE_EXCERPT",
    "source_url": "https://employer.example/jobs/ACTUAL_REQUISITION",
    "origin": "employer",
    "currency": "CAD",
    "unit": "annual",
    "kind": "base",
    "lower": 120000,
    "upper": null,
    "verified": true
  },
  "operator_note": "ACTUAL_SOURCE_OBSERVATION"
}
```

Numbers are illustrative, not assumed criteria or observed evidence. Enter exact
posted bounds matching the raw excerpt and read the active minimum. Only these
two top-level keys are allowed; private evidence is bounded to 16000 bytes with
no symlinks. Salary keys are exactly those shown (all default when omitted);
unknown keys are rejected. `origin` values: `employer|aggregator|estimate|unknown`.
Other salary strings are validated as strings, but eligible verification requires
employer, CAD, annual, base, verified true, a public source URL and exact bounds.
Estimates, ambiguous salary, hourly, total compensation and overlapping ranges
remain held; this command performs no URL fetch. It preserves the original source
and adds the externally observed verification provenance.

Attempt manifest shape (use real metadata and attachment decisions):

```json
{
  "operator": "hermes",
  "generation_id": "ACTUAL_APPROVED_GENERATION_ID",
  "review_token": "EXACT_REVIEWED_TOKEN",
  "application_url": "https://employer.example/ACTUAL_APPLICATION",
  "resume": {"filename": "resume.pdf", "sha256": "ACTUAL_SHA256"},
  "cover_letter": null
}
```

Explicit `cover_letter: null` means none attached; otherwise provide its exact
filename/hash object. Capture the approved current generation and actual attached
files, not newly regenerated substitutions. Historical snapshots preserve them.

## Verified daily reference

All following syntax has been checked against command help. Configuration is
parent-reported external scheduler state, not proof a scheduler is healthy.
Do not configure or activate a pilot merely because these commands are available.

```bash
jobby daily status
jobby daily configure --enabled false
jobby daily configure --enabled true --cron-job-id ACTUAL_EXTERNAL_CRON_ID --schedule 'ACTUAL_EXTERNAL_SCHEDULE' --timezone America/Toronto --max-submissions-per-day 10
jobby daily start --owner OPAQUE_OWNER
jobby daily heartbeat RUN_ID
jobby daily verify-job JOB_ID --evidence /private/salary.json
jobby daily note RUN_ID --job-id JOB_ID --outcome blocked --reason 'ACTUAL_SAFE_REASON' --source-url 'ACTUAL_PUBLIC_SOURCE_URL'
jobby daily begin-submit RUN_ID ATTEMPT_ID --phone-required
jobby daily begin-submit RUN_ID ATTEMPT_ID --phone-not-required
jobby daily uncertain RUN_ID ATTEMPT_ID --reason 'ACTUAL_SAFE_UNCERTAINTY'
jobby daily finish RUN_ID --status partial --note 'ACTUAL_SAFE_RUN_OUTCOME'
jobby daily summary RUN_ID
jobby daily summary
```

Use exactly one begin-submit phone flag based on the actual form. Configure
requires `--enabled true|false`; cron ID and schedule are required when enabling.
Optional timezone is only `America/Toronto`; cap is 1–25, initially 10.
Finish statuses: `completed|partial|blocked|failed`. Note outcomes:
`blocked|discovered|excluded|failed|queued|submitted|uncertain|verified`.
Note requires reason; source URL is optional. Finish note is optional. Summary
accepts an optional run ID. Notes cannot invent a submitted result without receipt.

## Daily operator workflow

The following is a template for an already authorized, configured pilot. Replace
IDs with returned IDs and all evidence placeholders with real observations.
Do not run later steps until their prerequisites actually occurred.

```bash
jobby status --brief
jobby daily status
jobby profile
jobby daily start --owner OPAQUE_OWNER
jobby daily heartbeat RUN_ID
jobby search 'TERM_FROM_ACTIVE_SETTINGS' --limit 10
jobby show JOB_ID
# Hermes inspects the actual employer posting and writes private salary/fit evidence.
jobby daily verify-job JOB_ID --evidence /private/salary.json
jobby fit JOB_ID --evidence /private/fit.json
jobby show JOB_ID
jobby prepare JOB_ID
jobby show JOB_ID
# Operator actually reviews current artifacts, then writes exact token + QA findings.
jobby approve JOB_ID --review /private/review.json
jobby attempt JOB_ID --manifest /private/manifest.json
# Hermes fills the actual form; masks phone BEFORE capture; operator reviews PNG.
jobby screenshot ATTEMPT_ID /private/filled.png --kind filled_form --qa-note 'ACTUAL_SAFE_QA_FINDINGS' --phone-redacted
jobby daily heartbeat RUN_ID
jobby daily begin-submit RUN_ID ATTEMPT_ID --phone-not-required
# Only after successful authorization: click Submit once via existing Hermes tools.
# Observe actual employer confirmation, capture phone-safe PNG and review it.
jobby screenshot ATTEMPT_ID /private/confirmation.png --kind employer_confirmation --qa-note 'ACTUAL_SAFE_CONFIRMATION_QA' --phone-redacted
jobby receipt JOB_ID --attempt-id ATTEMPT_ID --timestamp 'ACTUAL_AWARE_TIMESTAMP' --text 'ACTUAL_SANITIZED_EMPLOYER_CONFIRMATION'
jobby daily finish RUN_ID --status completed --note 'ACTUAL_SAFE_RUN_OUTCOME'
jobby daily summary RUN_ID
```

Start owns one global 30-minute lease; heartbeat during work and stop on guard
failure or expiry. Begin-submit persistently reserves the posting/attempt and
Toronto-day budget immediately before the click. It checks policy, intent,
criteria, eligibility, answers, current approval/hashes, filled-form screenshot
and duplicates. Reservation is not confirmation. Use `--phone-required` instead
when the actual form requires phone.

Caps count attempted reservations, including uncertain outcomes, across reruns
in `America/Toronto`. URL aliases and employer requisitions protect against
duplicate postings. If click/result is uncertain, use `daily uncertain`, retain
the hold and never blindly retry or create another attempt to evade it. Reconcile
using real employer evidence and record a later receipt for the exact reserved
attempt. Finishing or expiring a run retains unresolved reservations as uncertain.
Record unsupported forms, missing answers and browser failures truthfully with
`daily note`, finish with the actual outcome, then read the ledger summary.


## Setup and compatibility

Use the native-only requirements and repository `.venv` described in the root
setup guide; legacy model API credentials and `.env` are unnecessary. `fit` and
`approve` import shared FastAPI/Pydantic validators but never start the app.
Only `search` performs direct JobSpy network discovery. The optional local
dashboard and generic defaults/overrides are documented in the [runbook](README.md).
Every operator must obtain current candidate authorization externally. A default
policy provenance label, successful preflight or this document is not consent.
Scheduler configuration starts disabled and must be explicitly managed by a
human operator; the CLI does not configure the external scheduler.
