# Personal Jobby

A private deterministic FastAPI employment desk with a durable daily control CLI. Python makes no model API calls and never fills or submits browser forms. An externally configured Hermes cron agent provides reasoning and browser execution. The daily pilot defaults **disabled**, with no cron ID or schedule. Install native dependencies into the checkout `.venv` using the [root setup guide](../README.md#install-from-a-checkout). No model API credentials or legacy `.env` setup are required. See the [CLI contract](CLI.md) for native operations; shared validators do not start the server.

From the repository root, the standalone startup command is:

```bash
.venv/bin/python -m uvicorn personal_jobby.app:create_app --factory --host 127.0.0.1 --port 8090 --no-access-log
```

The optional dashboard has no separate account login; restrict it to trusted local access. A separately configured authenticated HTTPS ingress is needed for remote access and secure phone entry. This checkout does not create services or ingress. Exact hosts and same-origin JSON mutations are enforced. No external assets, arbitrary URL fetching, or arbitrary HTTP file-path access are provided.

All candidate facts, answers, settings, daily policy/leases/ledger, immutable generations, application archives and backups live in `~/.local/share/jobby-personal` by default (set absolute `JOBBY_ROOT` before startup to override): directories 0700, files 0600. Storage is **not encrypted at rest**. Phone is accepted only through the masked dashboard form; never prefilled, returned, printed, or included in documents. Blank preserves the saved phone; clearing requires the explicit checkbox. Other answer updates and source migrations preserve current answers under a shared file lock. Do not copy private files into the repository or diagnostics.

## Candidate import and criteria

An initialized profile uses only its authoritative text PDF. The importer expects the sectioned layout supported by `import_profile.py` (Experience, Projects, Technical Skills, Education and dated employment headings); scanned PDFs or other layouts need manual review and may be rejected. Each fact has a stable ID, exact source text/excerpt/path and source SHA256. A source replacement backs up the old profile privately and invalidates live materials, preserving answers. Submitted application copies remain available separately.

```bash
.venv/bin/python -m personal_jobby init --pdf /absolute/path/to/authoritative-resume.pdf
.venv/bin/python -m personal_jobby init --pdf /absolute/path/to/new-resume.pdf --replace
.venv/bin/python -m personal_jobby status --brief
```

Both default `status` and `--brief` give safe counts and short summaries. Initial generic defaults are provisional. Use current private settings rather than assuming the defaults are confirmed. Obtain explicit candidate authorization for the intended operator workflow; this repository grants none. Matching applications require confirmed criteria and current submission intent. Canadian work authorization does not imply authorization in another country. Work eligibility must be answered; phone presence is informational until the actual form requires it. Unchecking desired submission is the kill switch for every new reservation.

## Find and review

Add a posting through the dashboard, or `add /path/to/posting.json` (`-` reads stdin). Required keys: `title`, `company`, `job_url`, `description`; optional `requisition`, `location`, `arrangement`, `arrangement_evidence`, `employment_type`, `employment_evidence`, `salary`, and qualification review fields. Select arrangement and employment type, then copy exact evidence from the original description/location. Unknown arrangement/employment is held. Generic full-time does not establish permanent employment.

Search is direct JobSpy only, invoked explicitly by a person or the configured Hermes agent:

```bash
.venv/bin/python -m personal_jobby search 'AI Engineer' --limit 10
.venv/bin/python -m personal_jobby search 'AI Engineer' --location Canada --remote --hours-old 72 --limit 25
.venv/bin/python -m personal_jobby search 'AI Engineer' --location 'Toronto, ON, Canada' --hours-old 72 --limit 25
```

It directly imports JobSpy, bounds results to 25, and searches Canada. Sources can be blocked, return zero rows, or omit salary. All aggregator salaries need manual employer verification; no estimate confers eligibility. Original rows and discovery timestamps are retained. Canonical direct/archived aliases and employer requisitions deduplicate independently of role titles. Only tracking query keys (`utm_*`, `gh_src`, `lever-source`, `source`, `src`) are ignored in comparison keys; `jk`, `job_id`, and `req` remain meaningful. Original source URLs/identifiers remain unchanged; old aliases are backfilled without reassigning their owners.

Salary verification requires a public employer source URL, an exact raw CAD annual-base excerpt, verified employer provenance, and matching ordered lower/upper bounds. Upper-only, ambiguous currency, USD, hourly, estimate, total compensation and overlapping ranges are held. Explicit below-floor base pay is excluded. Current employer comes from private dated employment independently of the optional blacklist. Required qualifications and skill-specific years are conservatively held for source-grounded operator review; total employment duration is not proof of a skill's tenure.

## Documents and visual QA

Use the detail button or `prepare JOB_ID`. Selection preserves every employment role and chronology. Only the small equivalence map in `wording.py` can substitute terminology requested by the posting. Product names, numbers, dates and qualifiers stay unchanged; `evidence.json` records original/rendered facts and every exact substitution. Cover letters add only an approved first-person grammatical prefix to those facts, plus a neutral role/company salutation and closing.

PDFs use US Letter, equal .75-inch margins, Times serif, body >=10pt, one page, selectable ATS text and compact clickable links. Overflow drops optional low-priority facts, never whole employment roles or smaller fonts/margins. Skill labels are inline. Ambiguous source project links are omitted.

Generation artifact files are preserved; approval metadata records the review. Regeneration revokes old approval before rendering, writes into staging, and publishes a complete generation by an atomic pointer update. Candidate facts, source bytes, criteria, posting and artifact SHA256 bind each approval. Review **both PDFs, both DOCX documents and previews** externally; the supplied reviewer note and displayed `review_token` approve only that generation. Automatic page/font/text checks do not constitute visual approval. DOCX pagination needs LibreOffice/Word verification. The operator performs final document QA; new materials remain `pending_visual_review`.

## External Hermes browser operator audit

The external Hermes agent must follow [the repository-local operator skill](skills/hermes-jobby-daily/SKILL.md). The parent supplies this skill to the actual cron executor; it is not installed or activated by this code. It verifies public postings, grounded answers, documents and screenshots, and holds login/assessment/unknown-answer barriers. A filled-but-not-submitted draft is never a receipt or a submission reservation.

Before form filling, prepare and visually approve an explicit generation. Create a **private** manifest JSON with:

```json
{
  "operator": "hermes",
  "generation_id": "32-character-generation-id",
  "review_token": "64-character-reviewed-version-token",
  "application_url": "https://employer.example/application",
  "resume": {"filename": "resume.pdf", "sha256": "exact-64-character-sha256"},
  "cover_letter": null
}
```

This resume-only example explicitly records no cover attachment. When a cover letter is actually attached, replace `null` with its exact filename/hash object. Omitting the cover key is rejected for a Hermes-managed manifest; a generated cover draft must never be recorded as used merely because it exists. Only actually attached documents are archived.

Then capture and retain exact versions:

```bash
.venv/bin/python -m personal_jobby attempt JOB_ID --manifest /private/path/manifest.json
.venv/bin/python -m personal_jobby screenshot ATTEMPT_ID /private/path/filled.png --kind filled_form --phone-redacted --qa-note 'Checked filled form against the captured generation; phone masked before capture'
```

**Mask/remove the phone field in the external page before taking any screenshot**, and visually inspect the entire image for phone/other sensitive information before ingestion. Never screenshot the phone-entry dashboard. `--phone-redacted` is an explicit operator attestation, not an automated pixel/OCR guarantee. Only valid PNGs <=8MiB and <=4000px per dimension are accepted; textual PNG metadata is rejected. The local CLI copies immutable 0600 files, hashes them and records the QA note and generation. HTTP cannot ingest screenshot paths.

For a daily run, **before any submit click**, reserve the exact attempt using `daily begin-submit` as described below. Only the external agent clicks; Python never does. After an actual employer confirmation, ingest its reviewed sanitized screenshot and record real receipt evidence with a timezone-bearing timestamp:

```bash
.venv/bin/python -m personal_jobby screenshot ATTEMPT_ID /private/path/confirmation.png --kind employer_confirmation --phone-redacted --qa-note 'Reviewed employer confirmation; phone omitted'
.venv/bin/python -m personal_jobby receipt JOB_ID --attempt-id ATTEMPT_ID --text 'ACTUAL_SANITIZED_EMPLOYER_CONFIRMATION' --timestamp 'ACTUAL_TIMEZONE_BEARING_TIMESTAMP'
```

These commands **record**, never submit. Hermes-managed receipts require both reviewed screenshots and an explicit approved document manifest with correct filenames/hashes. A manual user-reported receipt without `--attempt-id` explicitly records **documents unknown**, even if a latest resume exists. Evidence URL may be supplied with `--url`. Applied requires receipt text or a public evidence URL and a timezone-bearing timestamp; repeated submission records are rejected.

The job detail shows submitted time, exact generation, resume/cover filenames and hashes, screenshot QA notes, and append-only attempt timeline. Captured document copies remain downloadable after regeneration, source migration or settings changes; historical download validates their manifest hashes rather than current-document freshness. File corruption fails closed. Status tracking is separate from submission execution.

## Daily policy, lease and pre-submit control

A human operator obtains candidate authorization and manually creates and verifies an external Hermes schedule before recording its real job ID. No schedule is enabled by installation. The following 09:00 America/Toronto schedule is an example, not evidence that any scheduler exists:

```bash
.venv/bin/python -m personal_jobby daily --help
.venv/bin/python -m personal_jobby daily status
.venv/bin/python -m personal_jobby daily configure --enabled true --cron-job-id "$VERIFIED_HERMES_CRON_JOB_ID" --schedule '0 9 * * *' --timezone America/Toronto --max-submissions-per-day 10
.venv/bin/python -m personal_jobby daily configure --enabled false
```

`daily-policy.json` is private 0600, under the private 0700 workspace; all its accesses use no-follow private filesystem operations. Initial policy has enabled false, null cron ID/schedule, a cap of 10 (bounded 1–25), and a generic operator-managed provenance label (not a grant of consent). Enable requires a nonempty externally verified cron ID and schedule, supplied now or retained from prior configuration. Python cannot attest that cron exists or fired. No disabled dry-run starts are provided; disabled status/configure remain available.

The executor starts and keeps the returned opaque run ID as its lease ownership across CLI exits. No process PID or secret token is required. One SQLite `BEGIN IMMEDIATE` global lease permits one live run, renewable for 30 minutes. Expired leases recover as interrupted runs. Submit locks survive recovery and day changes.

```bash
.venv/bin/python -m personal_jobby daily start --owner hermes-daily
.venv/bin/python -m personal_jobby daily heartbeat RUN_ID
.venv/bin/python -m personal_jobby daily note RUN_ID --job-id JOB_ID --outcome blocked --reason 'Employer login required' --source-url https://employer.example/jobs/POSTING
.venv/bin/python -m personal_jobby daily summary RUN_ID
.venv/bin/python -m personal_jobby daily begin-submit RUN_ID ATTEMPT_ID --phone-not-required
# Use --phone-required instead if this actual form requires phone. Exactly one flag is mandatory.
.venv/bin/python -m personal_jobby daily uncertain RUN_ID ATTEMPT_ID --reason 'Clicked once; no confirmed receipt'
.venv/bin/python -m personal_jobby daily finish RUN_ID --status partial --note 'One unresolved confirmation held'
```

Only a successful `begin-submit` authorizes one subsequent external click. It transactionally checks the live lease, enabled pilot, current confirmed criteria and desired submission, eligible posting, work answer, actual phone requirement, dedupe identities/prior application states, current visually approved exact generation/fingerprints/hashes, attached resume, optional cover decision, and intact reviewed filled-form screenshot. Failed preflight consumes no budget. Success appends `submit_started`, persists an immutable reservation, and sets `submission_pending`; it does **not** claim submission completed. Run IDs and attempt IDs above are placeholders returned by the actual commands.

The cap counts attempted-submission reservations, including unconfirmed and uncertain, by the Toronto date **at reservation time**, even when a lease crosses midnight. Same-day reruns share the cap. A reservation of the same underlying posting can never be repeated automatically. A lost command response, lost tab, fresh form, expired lease, or terminal run does not release it. Use `uncertain` after an unconfirmed click; interrupted/closed unresolved runs become uncertain automatically. A later actual guarded receipt can confirm the same archived attempt once, preserving the actual timestamp, exact attached documents and generation, including `cover_letter_used: false` for resume-only. Source changes after submission do not rewrite historical evidence. There is no automatic or CLI human-resolution unlock; a human must investigate outstanding uncertainty before any separate recovery design.

Notes support discovered/verified/queued/blocked/excluded/failed/submitted/uncertain, bounded redacted reasons and optional public URLs. They are append-only. Submitted notes require an existing corresponding job receipt and cannot mark a job applied or inflate totals. Confirmed run/day totals come from actual receipts for reserved attempts; pending/uncertain reservations remain visible. Keep private facts, answers, credentials and document contents out of notes and stdout.

`GET /api/daily` is readonly and protected by the existing host/origin/CSP controls; it shows parent-reported external Hermes configuration, latest persisted run/lease state, chronological safe events, daily counts, and unresolved holds. The small dashboard section uses self-only JavaScript and text nodes. `executor_enabled` describes policy configuration; `submission_active` additionally requires current criteria/intent and a live run lease. Neither proves an external click occurred; the API alone never clicks forms. The default legacy unavailable/false behavior remains until configuration. Phone is never a blanket form blocker.

For employer salary evidence published as structured data rather than description text, capture it externally into a private local JSON file with exactly `salary` (the existing validated salary object) and `operator_note` (a source-grounded observation). `source_url`, exact raw explicit CAD annual-base excerpt, matching bounds, employer origin and verified status are mandatory. No URLs are fetched by this command:

```bash
.venv/bin/python -m personal_jobby daily verify-job JOB_ID --evidence /private/path/employer-salary-proof.json
```

This retains the validated observation under `original_source.employer_salary_verification`, preserves original source data, and invalidates approval through the posting fingerprint. Use the native `fit JOB_ID --evidence PRIVATE_JSON` command or the optional fit API for exact arrangement/employment evidence and source-grounded qualification notes; an operator may perform that review without fabricating evidence. Verification never relaxes the eligibility rules.

## Verification and limits

Run the six fixture-only test modules listed in the root README. They use temporary candidate state, invented resume text, synthetic images and mocked discovery. They do not run real searches or submissions, read candidate state or prove employer application completion. Keep test reports private; they are not shipped artifacts.

Remaining limitations: browser execution depends on the parent's actual Hermes cron and browser tools; employer/source verification and required qualifications need grounded operator review; screenshot phone removal and document visual QA require external inspection; DOCX pagination varies by renderer; future employer questions are not guessed; local storage is restricted but unencrypted.


## Environment overrides and existing installations

`JOBBY_ROOT` selects the private state directory for CLI and dashboard at process
startup. Its default follows the current user's home; use an absolute path with
no symlink ancestors. It does not move existing state. Keep your existing private
workspace selected explicitly when reviewing an upgrade.

The dashboard allows only `localhost` and `127.0.0.1` by default.
`JOBBY_TRUSTED_HOST` adds one exact lower-case hostname (without scheme, port or
path) for an already secured ingress. Existing port and same-origin/CSP checks
still apply; this is not authentication or permission to expose the app publicly.

`JOBBY_AUTHORIZATION_SOURCE` optionally supplies the exact local policy provenance
label. The default is `operator-managed policy; confirm authorization externally`.
An existing `daily-policy.json` with a different historical label fails closed
unless the operator explicitly supplies that exact prior label at process startup.
Do not publish historical candidate authorization claims or rewrite live policy
as part of a source upgrade. This label is checked for consistency, not proof of
candidate consent; authorization must be established externally. These overrides
never enable a new workspace's disabled policy, confirm criteria, create an
external schedule or authorize a browser click on their own.
