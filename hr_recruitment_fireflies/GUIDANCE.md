# hr_recruitment_fireflies — module guidance

## What it does
Lets a recruiter attach one or more **Fireflies.ai interview links** to a candidate
(`hr.applicant`) and generate a **client-ready AI summary** of each interview:
executive summary, strengths, concerns/risks, highlights, and an optional
Question & Answer breakdown. The summary can be copied to the clipboard or printed
to a clean PDF to forward to the hiring client.

v1 is **manual only** — the recruiter pastes the link; there is no webhook/cron/
calendar matching yet (those are documented in the Obsidian plan as later phases).

## Main models
- **`hr.applicant.interview`** (`models/hr_applicant_interview.py`)
  One interview per record: `fireflies_link`, `interview_type`, `interviewer_id`,
  `interview_date`, optional `question_template_id` (lens), processing `state`, and
  the AI output (`executive_summary`, `strengths`, `concerns`, `highlights`,
  `qa_line_ids`). `summary_clipboard` is a computed plain-text version used by the
  `CopyClipboardText` widget. `input_hash` + `last_generated` guard against
  re-spending an OpenAI call when the transcript is unchanged.
- **`hr.applicant.interview.qa`** (`models/hr_applicant_interview_qa.py`)
  One Q&A line: `question`, `answer`, `coverage` (covered/partial/missed/not_asked).
- **`fireflies.client`** (`models/fireflies_client.py`)
  Reusable `AbstractModel` wrapping the Fireflies GraphQL API
  (`fetch_transcript`, `_parse_meeting_id`, `_get_api_key`). Centralised so future
  features share one fetch path and one place to enforce the 50 req/day quota.
- **`hr.applicant`** (`models/hr_applicant.py`)
  Adds `interview_ids`, counts, smart-button action.

## Business logic / flow
1. Recruiter adds an interview (Interview Summary tab) and clicks **Analyze**.
2. `action_analyze` validates the link + keys, sets `state=processing`, enqueues
   `_run_interview_analysis_job` via **queue_job** (`with_delay`).
3. The job: `fireflies.client.fetch_transcript` → **quality gate** (`MIN_SENTENCES`)
   → build the lens questions from `question_template_id` → **input-hash cost guard**
   → `hr.applicant._openai_call` (reused from `hr_recruitment_extract_openai`) with
   the `InterviewSummarySchema` Pydantic model → store fields + rebuild Q&A lines →
   `state=done` → bus notification.
4. **Copy** = `CopyClipboardText` on `summary_clipboard`; **PDF** = QWeb report
   `action_report_interview_summary`.

## Important patterns / constraints
- **Reuse, don't rebuild:** OpenAI client/keys and `_openai_call` come from
  `hr_recruitment_extract_openai`; question templates from `hr_recruitment_forms`
  (`hr.form.template` / `hr.form.question`). Fireflies + OpenAI keys live on
  `res.company` (already defined by the extract module).
- AI output language is **English** (client-facing) and is **evidence-based**: the
  prompt forbids inventing facts and excludes protected/personal characteristics.
- All summary HTML is built with `markupsafe` escaping; `Html` fields are sanitized.
- Background work uses `queue_job`; ensure its runner is enabled on the environment.
- Migrations: new module → none during development; schema is created on install.
