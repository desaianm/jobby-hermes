# Jobby for Hermes

A job-search desk inside [Hermes](https://github.com/NousResearch/hermes-agent). Import your resume, find roles across supported countries, and prepare tailored resumes and cover letters in PDF and DOCX.

## Install with your agent

Copy this into your Hermes chat, or an agent chat with terminal access to your Hermes machine:

```text
Install the Jobby plugin from https://github.com/desaianm/jobby-hermes using Hermes's plugin manager. Review its README and dependency/trust prompts first. Install it in my current Hermes profile, enable it, and verify it is enabled. Ask me before accepting dependency or trust permissions; do not bypass checks. Help me open Jobby desk and import my resume, asking for its PDF path on the backend machine. Do not submit applications or enable auto-apply.
```

Prefer the terminal? With Hermes already installed and configured:

```bash
hermes plugins install desaianm/jobby-hermes --no-enable
hermes plugins enable jobby
```

Review the installer's dependency and trust prompts. For a reproducible install, add `--ref FULL_COMMIT_SHA` using the complete 40-character commit you reviewed.

**Requirements:** Linux/POSIX and Hermes >=0.22.5. Other operating systems and packaged Desktop installers are unverified. Hermes's package manager installs the Python engine and its dependencies; no separate CLI setup is needed.

## Start using it

1. Enable the Desktop contribution in **Capabilities → Plugins**, then open **Jobby desk** from the sidebar or command palette. With a remote backend, the Desktop contribution must also be installed on your desktop machine through its supported installation flow.
2. Import a text-based resume PDF using its absolute path on the backend machine. Scanned PDFs and unsupported layouts may be rejected.
3. Review the imported facts, choose your role terms, country and location, and confirm the search. Or paste a posting you already have.
4. Select a job, prepare your documents, then download and review the PDFs and DOCX files.

## Know before you use it

- **You stay in control.** The desk does not submit applications. Auto-apply is inactive, and downloaded documents still need human review.
- **Searches use third-party providers.** JobSpy requests Indeed and LinkedIn using approved role/skill terms and preferences, not your full resume. Availability varies; independent LinkedIn success is unverified. One supported country per search, not a worldwide query.
- **Documents are generated locally.** No model API calls are used for generation. Private workspace data stays on the Hermes backend; keep source files and workspace data out of public repositories.
- **Review the output.** Check facts, job requirements and document layout. Wording overlap is not proof of suitability or hiring probability.

[Setup, troubleshooting, privacy and limitations](docs/USAGE.md) · [CLI contract](personal_jobby/CLI.md) · [Operator workflow](skills/assisted-application/SKILL.md)

<details>
<summary>See the desk</summary>

![Jobby desk showing source-backed search and document review](docs/images/jobby-desk.png)

Historical Canadian-example UI from the native demo, using a disclosed non-human test identity. Not evidence of the current international UI or live searches in other countries. Documents remain pending human review.

</details>

## License

[MIT](LICENSE). Dependencies retain their own licenses; PyMuPDF uses AGPL or commercial terms.
