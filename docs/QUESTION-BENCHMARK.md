# Public question inventory and controlled standard-fixture benchmark

`jobby questions` extends the existing CLI beside JobSpy discovery. It never
initializes or reads candidate state. The collector uses only key-free public
Greenhouse GETs; it has no POST method, authentication, cookies, proxy support,
browser, or model client. The maintained synthetic runner owns document generation,
native tools, immutable attempts, browser uploads, one-click intent and mock audit
reconciliation. `ats-contract.mjs` remains structural observation only.

This is **Greenhouse-only** static metadata, not cross-ATS frequency research or
hosted/conditional-form completeness. The default engineering/research sample uses
the same `technical_title` predicate in discovery and saved-source verification:
the original declared AI/research cue regex AND engineer/engineering/scientist/researcher,
excluding sales/advisory/account/GTM/tutor/recruiter/analyst words. All three literal
regexes are recorded in the manifest. AI Automation Engineer and Research Scientist
qualify; Account Executive AI Native, AI Advisory Principal, Account Director
Enterprise AI, GTM systems directors, tutors and finance research analysts do not.
Jobs at an AI company do not qualify solely by company. Descriptions, labels, options and disclosure HTML are untrusted
data and are never evaluated. Source descriptions do not become candidate facts.
The official [Job Board API documentation](https://docs.greenhouse.io/job-board.html)
describes public GETs, question groups and alternative fields. The employer POST
API is outside this workflow.

## Collection

Run from this checkout, using the borrowed environment without installing into it.
Every output must be fresh. The explicit boards below were independently verified
by the parent on November 5; availability and selected counts must still come from
the new manifest. Historical deepmind/runwayml/baseten/modal probes were unavailable;
there is no guessed-token fallback. The worker's live smoke encountered DNS failure.

```bash
JOBBY_ROOT=/home/adcan288/tmp/jobby-question-benchmark-20261105/parent-unused-cli-root-02 personal_jobby/bin/jobby questions collect --board anthropic --board scaleai --board xai --board togetherai --board databricks --board snorkelai --board turing --target 100 --per-board-cap 25 --output /home/adcan288/tmp/jobby-question-benchmark-20261105/parent-public100-02
```

The collector lists each board once and then takes matching IDs round-robin, with
a per-board maximum. Only canonical board + posting ID determines posting identity.
Internal job IDs (board-scoped, excluding null) and board + normalized exact titles
are separately counted. A title family is a literal grouping, not inferred semantic
equivalence. Multiple locations may share an internal job. No diversity or 100-form
claim follows from a list endpoint's total alone.

Limits: 1–12 explicit slugs, target and per-board cap 1–100; 250 request attempts;
default minimum 0.3-second pacing (configurable 0.25–10); 10-second request wall/socket
budget; 900-second total HTTP budget; 8 MiB list, 2 MiB detail and 64 MiB aggregate
received-byte limits. The sequential Linux CLI uses an unshared main-thread SIGALRM
deadline to include DNS/connect/headers; embedding in threads or alongside another
active timer is unsupported and refuses the GET. HTTPS uses system certificate verification. Redirects are
refused entirely. Paths are constructed from validated slugs and integer IDs at
`boards-api.greenhouse.io`; source-supplied URLs are never fetched. List totals must
match returned rows. Failures and caps produce a shortfall, never invented forms.

`responses.jsonl` is fsynced before and after each request; `raw/NNNN.response`
contains actual response bytes, including malformed JSON. Each saved response has
an actual source URL, collection timestamp, size and SHA-256. `manifest.json` and
`questions.json` are updated atomically after each stage. On a catchable interruption
the manifest says `interrupted`; after a hard kill an unmatched request-start record
identifies uncertainty. The last completed snapshot remains usable. There is no
automatic retry/resume; preserve the directory and use a fresh path for another
explicit collection. Raw records may be ahead of the last snapshot after a hard kill.

`questions.json` is a JSON **array** of scoped signatures with exact source labels,
separate observed label variants, requiredness, complete fields/types/options,
original grouped metadata, context and source references. A required Resume question
with file and text fields means **at least one field**, not two required uploads.
Location, EEOC/compliance, demographic headers/options, consent flags and returned AI
disclosures are retained; metadata-only records do not invent input labels or
requiredness. Nested compliance sections retain section index, type, description
and other section metadata in each inner question's group context. Optional null
groups are `returned_null_coverage_unknown`, distinct from absent/returned-empty
groups, and retain a gap and original raw response. They do not reject validated
nonempty primary questions. Missing groups and unknown country remain explicit coverage gaps.
Only NFC Unicode, whitespace and case are normalized; punctuation and negation
remain significant. Field identifiers, types and submitted option values stay exact.
Company/board, language, source location/country, group context and schema/API versions
are part of the signature. Observed label repetition is distinct from approved reuse.
Aggregate JSON files are limited to 16 MiB; inventory admission leaves serialization
headroom. Excessive source or aggregate sizes are failures.

Successful data commands print one JSON result; diagnostics use stderr. Collection
shortfall prints `ok: false` and exits 1. Help is ordinary argparse help. Output is
restricted to fresh absolute directories under `/home/adcan288/tmp`, with no symlink
ancestors, 0700 directories and 0600 files. Keep answer files private.

## Local answer lookup and inert resolution contract

```bash
personal_jobby/bin/jobby questions lookup --input /home/adcan288/tmp/jobby-question-benchmark-20261105/private-request.json --output /home/adcan288/tmp/jobby-question-benchmark-20261105/private-lookup-01
```

The input is one bounded JSON object (maximum 16 MiB; up to 5000 questions and
5000 approvals), with these keys:

| Key | Value |
| --- | --- |
| `schema_version` | Integer `1` |
| `candidate_fingerprint` | Current candidate/settings scope, 64 lowercase SHA-256 hex characters |
| `source_fingerprint` | Current authoritative source snapshot scope, 64 lowercase SHA-256 hex characters |
| `questions` | Complete question objects copied from the current inventory array |
| `cache` | `{ "schema_version": 1, "approvals": [] }`, or explicitly reviewed records below |

Callers must obtain current fingerprints from their existing source/profile owner;
this inert lookup neither reads an active profile nor certifies the caller's scope.
Changing either fingerprint invalidates previous approvals. Do not substitute a
posting ID, arbitrary constant or a previous profile's hash for current scope.

Each approval has exactly this meaning: `schema_version: 1`, `fingerprint` equal to
the complete question signature, the two current scope fingerprints, `approved: true`,
an actual nonempty `approved_by`, `approved_kind`, and a nonempty string `value`
(maximum 500 characters). There are no default candidate values. Only exact standard
`First Name`/`first_name`, `Last Name`/`last_name` (`approved_kind: identity`) and
`Email`/`email` (`approved_kind: contact`) single `input_text` groups
with no options or extra metadata are reusable. An additional `description: null`
or `description: ""` is accepted; nonempty descriptions remain held. Original raw
descriptions remain fingerprint inputs. Approval is an explicit local data
contract, not cryptographic reviewer authentication. Protect the private cache files.

Phone prompts stay `needs_review` even with an explicit matching scoped approval.
Unknown/essay/employer-specific/authorization/legal/consent/demographic prompts stay
`needs_review` even if an approval file claims otherwise. Different options/types,
punctuation, employer, country/context, schema or candidate/source scope cannot match.
Multiple applicable approvals are ambiguous and held. No semantic merging, generic
essay templates, model provider, account write or form filling is connected here.

The private `answers.json` contains results and metrics; `review-queue.json` deduplicates
misses for one batched review, retaining occurrences and exact context. For a safe
identity/contact question, a reviewer resolves it by adding one scoped approval to
the input cache and rerunning lookup in a fresh output. Other questions require
individual review outside this automatic cache. `ai_orchestration_needed` counts
unique held signatures; it is a queue, not an AI call or an instruction to invoke one.
Collector `http_requests` counts attempted GETs including DNS/connect failures;
actual wire sends are not measured. Metrics separately count hits, misses, HTTP requests (zero here), actual model calls
(zero), and elapsed time. No money, speedup or network-send savings are inferred.
Stdout exposes counts and private file paths, never approved values.

## Controlled 100-case command (parent only)

After independently reviewing a successful 100-form manifest:

```bash
PYTHON_DOTENV_DISABLED=1 PYTHONDONTWRITEBYTECODE=1 /home/adcan288/jobby_bot/.venv/bin/python scripts/run_synthetic_applications.py --source-manifest /home/adcan288/tmp/jobby-question-benchmark-20261105/parent-public100-02/manifest.json --controlled-agent-answers --case-limit 100 --output /home/adcan288/tmp/jobby-question-benchmark-20261105/parent-controlled100-02 --hermes-source /home/adcan288/.hermes/hermes-agent --node /home/adcan288/.local/bin/node --playwright-module /home/adcan288/hermes-secure-browser/control/node_modules/playwright-core/index.mjs
```

The manifest and selected raw detail bytes are revalidated, including SHA-256,
canonical source URL and distinct board/ID pairs. Fewer than 100 valid inputs refuses
the default benchmark. `--case-limit 1` or `2` bounds a smoke; `--prepare-only` stops
before the browser. Without `--source-manifest`, the original five stable-role matrix
is preserved. Existing native fixture, hash, no-retry, CAPTCHA/error negative-control,
masking, delayed upload and loopback receiver tests remain unchanged.

The benchmark creates `benchmark-001` through `benchmark-100`, mapped one-to-one to
selected source IDs, with unique fictional requisitions, generations and attempts.
Benchmark mode uses the separate `tests/fixtures/benchmark-ai-agent.json`:
**AI Agent — NON-HUMAN SYNTHETIC FIXTURE**, reserved `agent@example.test`, with no
human employment, degree, residence, telephone or eligibility. Empty Experience
and Education sections satisfy the existing importer without inventing facts.
Support fact IDs resolve from actual imported fixture text. Its vocabulary describes
tested Python document/audit tooling, metadata/cache and local-browser evaluation;
it claims no measured model performance or engineering history. PyTorch remains an
explicit unsupported gap. The original Rowan five-role fixture and tests stay intact.

Without `--controlled-agent-answers`, all public groups remain held. With that explicit
flag, `controlled-nonhuman-fixture-v1` automatically approves only validated exact
`first_name`, `last_name`, `email` groups for this disclosed synthetic identity.
This is synthetic fixture approval, not human review or real-send authorization.
Phone (even optional), essays, legal, demographic, consent, authorization, unknown
and ambiguous groups remain `needs_review`; no honest phone value exists. The
maintained fixture's own resume upload and gap control remain separate from source
form coverage. No source residence or eligibility controls are replayed.

Every case runs `question_answers.lookup_batch` against one cache private to this
fresh owned run. Safe exact signatures are seeded once per current scope; subsequent
existing matches reuse them. Scope hashes derive from the actual imported profile,
AI fixture identity, settings, source PDF/DOCX/fixture hashes and native materials'
candidate/source/settings bindings. Per-case job/generation hashes are intentionally
separate; question signatures retain board/company/country/location and raw context.
Changed safe context creates a new explicit scoped fixture approval; changed options
or nonempty context stays held. No previous run or real profile/cache is loaded.

`controlled-answer-cache.json`, per-case `.answers.json` and `.controlled-answer-binding.json`
retain approvals, batched unknown queues and exact attempt/generation/resume bindings.
An immutable native audit event records the binding. Metrics separate
`first_time_synthetic_approvals`, final deterministic matches (`deterministic_answer_hits`),
genuine prior-case `existing_cache_hits`, held group occurrences and zero model calls.
`matched_groups` contains source fingerprint -> rendered field name/source type/HTML
type/value mappings. `held_groups` enumerates every other source group.
`mapped_public_fields` counts planned safe mappings; `replayed_public_fields` stays
zero until an acknowledged browser result proves actual rendered and submitted fields.
Preparation-only output therefore makes no replay claim. Receipt proof includes
both field lists and the native multipart archive hash in the immutable audit.
The receiver validates exact deterministic values, keys, uniqueness and file bytes;
tampered values, extra/duplicate fields and altered uploads fail. These denominators
describe limited safe groups, not complete production-form replays or assumed cache hits.

The child receives only the fictional form configuration and validated safe mappings
with canonical labels and source fingerprints, never employer URLs, descriptions,
names or raw public labels/HTML. All displayed data uses escaped markup/text. Canonical application/receipt URLs are reserved
`applications.example.test`; exact transport paths map to one owned ephemeral
`127.0.0.1` listener. All other context requests and service workers are blocked.
Child environment contains only explicit synthetic HOME/TMPDIR, fixed PATH/LANG and
the installed Playwright module path. No inherited credentials are passed.

The legacy output root `/home/adcan288/tmp/jobby-role-tests-20261104` stays accepted;
the additional owned root is `/home/adcan288/tmp/jobby-question-benchmark-20261105`.
Short mode-0700 Chrome temporary directories now use `b-*` directly in the additional
root, with process-group cleanup on all exits. Existing outputs/symlinks are refused;
there is no retry flag. Reports are incremental and preserve uncertain click outcomes.
Native multipart bytes, hashes, archived documents and screenshots are evidence only
when actually produced. Automated synthetic document QA is not invented human review.

The worker's two-case smoke prepared real PDF/DOCX/evidence/attempts from **synthetic
source metadata**, because live DNS was blocked. Its listener failed with literal
`listen EPERM: operation not permitted 127.0.0.1`, before Chrome navigation; zero POSTs,
acknowledgments or browser QA are claimed. The real HTTP receiver test retains the
same sandbox failure without a skip or alternate transport. Full real100 collection,
controlled100 execution and representative render inspection belong to the parent.

Parent evidence supersedes historical worker-only suite failures: `parent-tests-01.xml`
reports 420 tests passing in 62.887 seconds. The original `parent-public100-01`
collection attempted 250 GETs but admitted zero forms because of the schema gap;
preserve it unchanged. Correction offline revalidation accepted all 243 saved detail
responses, 126 matching the tighter technical predicate. This is saved-data revalidation,
not a new live collection or a completed 100-journey benchmark.

## Verification

```bash
/home/adcan288/jobby_bot/.venv/bin/python -m pytest -q tests --basetemp=/home/adcan288/tmp/jobby-question-benchmark-20261105/parent-correction-tests-01
/home/adcan288/jobby_bot/.venv/bin/python -m compileall -q personal_jobby tests scripts
/home/adcan288/.local/bin/node --check browser/synthetic-applications.mjs
/home/adcan288/.local/bin/node --check browser/ats-contract.mjs
/home/adcan288/.local/bin/node --check personal_jobby/static/app.js
```

Use a fresh absolute temporary `JOBBY_ROOT` for launcher `status --brief` checks from
another working directory. Do not inspect real candidate state, install packages,
relax the sandbox, run real submissions, mutate services or configure schedules.
The external worker receipt records actual results and retained RED/failure logs.
