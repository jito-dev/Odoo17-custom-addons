# hr_recruitment_fireflies — module guidance

## What it does
Lets a recruiter attach one or more **Fireflies.ai interview links** to a candidate
(`hr.applicant`) and generate a **client-ready AI summary** of each interview:
executive summary, strengths, concerns/risks, highlights, and an optional
Question & Answer breakdown, ready to forward to the hiring client. Each interview
keeps a **chatter log** of its analysis, lets the recruiter add a **free-form note**
next to the AI output, and links straight back to the **original Fireflies recording**.

v1 is **manual only** — the recruiter pastes the link; there is no webhook/cron/
calendar matching yet (those are documented in the Obsidian plan as later phases).

## Main models
- **`hr.applicant.interview`** (`models/hr_applicant_interview.py`)
  One interview per record: `fireflies_link`, `interview_type`, `interviewer_id`,
  `interview_date`, optional `question_template_id` (lens), processing `state`, and
  the AI output (`executive_summary`, `strengths`, `concerns`, `highlights`,
  `qa_line_ids`). `recruiter_note` (Html) is the recruiter's own note — it
  supplements the AI output, the AI never reads or overwrites it, and editing it
  does **not** trigger a re-analysis. `show_details` is a **non-stored UI toggle**
  that expands the heavier Highlights / Q&A sections (collapsed by default).
  `input_hash` + `last_generated` guard against re-spending an OpenAI call when the
  transcript is unchanged. The model inherits **`mail.thread`**, so every analysis
  event (started / analyzed / skipped / failed) is logged to the chatter.
- **`hr.applicant.interview.qa`** (`models/hr_applicant_interview_qa.py`)
  One Q&A line: `question`, `answer`, `coverage` (covered/partial/missed/not_asked),
  plus **`is_custom`** — `False` for template-driven lines (`qa_line_ids`), `True` for
  ad-hoc recruiter questions (`custom_qa_line_ids`). Both o2m fields on the interview
  are **domained on `is_custom`**, so the two Q&A tables never mix and a full
  re-analysis rebuilds only the template lines.
- **`fireflies.client`** (`models/fireflies_client.py`)
  Reusable `AbstractModel` wrapping the Fireflies GraphQL API
  (`fetch_transcript`, `_parse_meeting_id`, `_get_api_key`). Centralised so future
  features share one fetch path and one place to enforce the 50 req/day quota.
- **`hr.applicant`** (`models/hr_applicant.py`)
  Adds `interview_ids`, counts, smart-button action.

## Business logic / flow
1. Recruiter adds an interview (**Fireflies Summary** tab) and clicks **Analyze**.
2. `action_analyze` → `_start_analysis(force_refresh=False)`: validates the link,
   decides whether a Fireflies fetch is needed (`_needs_fetch`), checks the API key
   **only when it will fetch**, sets `state=processing`, enqueues
   `_run_interview_analysis_job` via **queue_job** (`with_delay`).
3. The job: **fetch only if needed** (`_needs_fetch`: no saved transcript, link
   changed, or refresh forced) → on a fresh pull run the **quality gate**
   (`MIN_SENTENCES`) and store `transcript_text` + `fetched_link`; otherwise **reuse
   the saved transcript (no Fireflies call, no quota spent)** → build the lens
   questions from `question_template_id` → **input-hash cost guard** (skips the
   OpenAI call when transcript+questions are unchanged and a summary exists) →
   `hr.applicant._openai_call` (reused from `hr_recruitment_extract_openai`) with the
   `InterviewSummarySchema` Pydantic model → store fields + rebuild Q&A lines →
   `state=done` → bus notification + chatter log.
4. **Open in Fireflies** (`action_open_fireflies`) returns an `ir.actions.act_url`
   that opens `fireflies_link` (the original recording/transcript) in a new tab.
   There is **no PDF export and no clipboard copy** — the rendered summary is plain
   selectable text; both features were removed in v17.0.1.4.0.

## Fetch vs. analyze (v17.0.1.1.0)
- The transcript is pulled from Fireflies **once** and cached in `transcript_text`
  (with `fetched_link` recording which link produced it). **Re-analyzing** — e.g.
  after changing `question_template_id` to add questions — reuses that cached
  transcript and spends **no Fireflies quota**; only the OpenAI call re-runs.
- A fresh pull happens only when: there is no saved transcript, `fireflies_link`
  was edited, or the recruiter clicks **Refresh transcript** (`action_refresh_transcript`
  → `_start_analysis(force_refresh=True)`).
- The raw transcript is **hidden behind the "View Transcript" button**
  (`action_view_transcript`), which opens it in a modal
  (`hr_applicant_interview_transcript_view_form`) instead of a permanent notebook tab.

## Question template auto-default (v17.0.1.6.0)
- `question_template_id` is now a **stored computed, `readonly=False`** field
  (`_compute_question_template_id`, depends on `applicant_id.job_id`): it **defaults
  to the candidate's job template** (`hr.job.form_template_id`) so recruiters set it
  **once on the job** and every interview stage inherits it — no per-interview picking.
- The compute **never overwrites a manual choice** (`if rec.question_template_id: continue`),
  so overriding or clearing it on a specific interview sticks. Same editable-default
  pattern as `_compute_name`.

## Custom questions (v17.0.1.5.0)
- A recruiter can type **ad-hoc questions** (`custom_questions`, one per line) in the
  "Ask Your Own Questions" card and click **Answer these questions**
  (`action_answer_custom_questions`).
- `_run_custom_questions_job` reuses the **saved transcript only** (no Fireflies quota,
  no OpenAI summary re-run): it calls `_openai_call` with `CUSTOM_QUESTIONS_PROMPT` +
  `CustomQASchema` (qa-only) and rebuilds **only** `custom_qa_line_ids`. The client
  summary (executive_summary / strengths / concerns / highlights) and the template
  Q&A are never touched.
- Its own lightweight status (`custom_state` / `custom_message`) drives a spinner /
  error alert **without** flipping the interview's main `state` (so the summary block
  stays visible while custom questions run). Requires a saved transcript first
  (analyze the interview before asking custom questions).

## UI / look (v17.0.1.5.0)
- **Metadata trimmed:** `meeting_id`, `last_generated` (Last Analyzed) and `model_used`
  (Model Used) were **removed from the form** — they remain stored, and the model used
  is still recorded in the chatter. `fireflies_link` stays visible (it's the required
  input) alongside the **Open in Fireflies** button.
- **Highlights** is now **always shown** once analyzed (no longer behind *Show details*);
  the *Show details* toggle still gates only the template Q&A table.
- **Custom Q&A** card uses a teal accent (`.o_ff_custom`).

## UI / look (v17.0.1.4.0)
- **Chatter** at the bottom of the interview form logs each analysis run
  (`message_post` from `_start_analysis` and `_run_interview_analysis_job`).
- **Recruiter Note** is a blue-accented card (`.o_ff_note`) inside the summary
  block — editable, visually integrated with (not detached from) the AI output.
- **Show details** (`boolean_toggle` on the non-stored `show_details`) collapses the
  Highlights and Q&A sections by default; the exec summary + Strengths/Concerns
  cards stay visible.
- **Open in Fireflies** header button (`fa-external-link`) links to the original
  recording; the **PDF** button and the **Copy summary** clipboard widget are gone.

## UI / look (v17.0.1.2.0)
- The client-facing summary is a visually separated block (`.o_ff_summary`) with
  two bordered cards — **Strengths** (green left accent, `.o_ff_ok`) and
  **Concerns / Risks** (red, `.o_ff_risk`) — plus icon headers. Styles live in
  `static/src/scss/fireflies.scss`, loaded via `web.assets_backend`.
- **Cheap vs expensive actions:** *Re-analyze* is neutral; *Refresh transcript*
  carries a warning-tinted button (`.o_ff_refresh_btn`) **and** a confirm dialog,
  because it spends the Fireflies daily quota. Heavier friction on the costly path.
- `has_transcript` (computed boolean) drives the transcript/refresh button
  visibility so the heavy `transcript_text` is **not** loaded into the form; the
  raw text is fetched only when the "View Transcript" modal opens.
- The error state shows a red banner; **Retry** lives in the header (same
  `action_analyze`), not inside the banner.

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
