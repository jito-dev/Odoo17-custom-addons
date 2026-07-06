# hr_recruitment_fireflies — module guidance

## What it does
Lets a recruiter attach one or more **Fireflies.ai interview links** to a candidate
(`hr.applicant`) and generate a **client-ready AI summary** of each interview:
executive summary, strengths, concerns/risks, and highlights, ready to forward to the
hiring client. Recruiters can also add **their own questions** and have them answered
from the saved transcript. Each interview keeps a **chatter log** of its analysis, lets
the recruiter add a **free-form note** next to the AI output, and links straight back to
the **original Fireflies recording**.

The candidate's **Fireflies Summary** tab shows each interview's analysis **inline as a
stacked card** — the summary is read without opening a dialog; adding another interview
appends a card below.

v1 is **manual only** — the recruiter pastes the link; there is no webhook/cron/
calendar matching yet (those are documented in the Obsidian plan as later phases).

## Main models
- **`hr.applicant.interview`** (`models/hr_applicant_interview.py`)
  One interview per record: `fireflies_link`, `interviewer_id`,
  `interview_date`, processing `state`, and the AI output (`executive_summary`,
  `strengths`, `concerns`, `highlights`). `custom_qa_line_ids` holds the recruiter's
  own questions. `custom_qa_html` is a computed read-only rendering of the answered
  questions, shown on the inline summary card. `recruiter_note` (Html) is the
  recruiter's own note — the AI never reads or overwrites it, and editing it does
  **not** trigger a re-analysis. `input_hash` + `last_generated` guard against
  re-spending an OpenAI call when transcript + role context are unchanged. Inherits
  **`mail.thread`** so every analysis event is logged to the chatter.
- **`hr.applicant.interview.qa`** (`models/hr_applicant_interview_qa.py`)
  One question line: `question`, `answer`, `coverage` (covered/partial/missed/
  not_asked), and `is_custom` (always `True` now — the interview's `custom_qa_line_ids`
  is domained on it). Rows are the recruiter's questions; **Answer** fills the answer /
  coverage in place.
- **`fireflies.client`** (`models/fireflies_client.py`)
  Reusable `AbstractModel` wrapping the Fireflies GraphQL API
  (`fetch_transcript`, `_parse_meeting_id`, `_get_api_key`). One fetch path, one place
  to enforce the 50 req/day quota.
- **`hr.applicant`** (`models/hr_applicant.py`)
  Adds `interview_ids`, counts, smart-button action.

## Business logic / flow
1. Recruiter adds an interview (**Fireflies Summary** tab card) and clicks **Analyze**.
2. `action_analyze` → `_start_analysis(force_refresh=False)`: validates the link,
   decides whether a Fireflies fetch is needed (`_needs_fetch`), checks the API key
   **only when it will fetch**, sets `state=processing`, enqueues
   `_run_interview_analysis_job` via **queue_job** (`with_delay`).
3. The job: **fetch only if needed** (no saved transcript, link changed, or refresh
   forced) → on a fresh pull run the **quality gate** (`MIN_SENTENCES`) and store
   `transcript_text` + `fetched_link`; otherwise **reuse the saved transcript (no
   Fireflies call, no quota spent)** → build the **role context** (`_get_role_context`)
   → **input-hash cost guard** → `hr.applicant._openai_call` with `InterviewSummarySchema`
   → store summary fields → `state=done` → bus notification + chatter log.
4. **Open / Edit** on a card (`action_open_form`) opens the interview as a **full page**
   (breadcrumb navigation, `target=current`) — not a modal. **Open in Fireflies**
   (`action_open_fireflies`) opens `fireflies_link` in a new tab.

## Role context from the JD (v17.0.1.7.0)
- The Q&A **question template** (`question_template_id` / `hr.form.template`) and the
  template-driven Q&A table (`qa_line_ids`) were **removed**. They produced one row per
  template question — including `not_asked` ones — which showed as empty rows.
- The summary is instead **focused using role context from the job**, via
  `_get_role_context()`: it prefers the structured **Job Requirements**
  (`hr.job.requirement_statement_ids`, extracted from the Job Description file by
  `hr_recruitment_extract_openai`); if none exist it falls back to the **plain-text
  job description** (`hr.job.description`, capped at `MAX_DESCRIPTION_CHARS`). Returns
  `([], 'none')` when the job has neither — the summary still works from the transcript.
- The context is fed to the model **as focus only** (the prompt forbids treating it as
  candidate facts or scoring it item by item). No visible requirement-by-requirement
  table is generated.

## Recruiter questions (v17.0.1.7.0)
- `custom_qa_line_ids` is an **editable list**: the recruiter adds question rows
  (**Add a question**) and clicks **Answer** (`action_answer_custom_questions`).
- `_run_custom_questions_job` reuses the **saved transcript only** (no Fireflies quota,
  no summary re-run): `_openai_call` with `CUSTOM_QUESTIONS_PROMPT` + `CustomQASchema`,
  then `_write_custom_answers` maps each AI answer back **onto the existing row** —
  matched by **question text** (normalized), falling back to position. Rows are never
  created or deleted by the job, so it's exactly one answer per question (this is what
  fixed the old "extra empty rows" behaviour).
- Its own status (`custom_state` / `custom_message`) drives a spinner / error alert
  **without** flipping the interview's main `state`.

## Fetch vs. analyze
- The transcript is pulled from Fireflies **once** and cached in `transcript_text`
  (with `fetched_link`). **Re-analyzing** reuses that cache and spends **no Fireflies
  quota**; only the OpenAI call re-runs.
- A fresh pull happens only when: there is no saved transcript, `fireflies_link` was
  edited, or the recruiter clicks **Refresh transcript** (`action_refresh_transcript`).
- The raw transcript has **no UI** — it is stored locally and never shown (the old
  *View Transcript* button and modal were removed in v17.0.1.7.0). `has_transcript`
  still gates the *Refresh transcript* button so the heavy text isn't loaded to toggle
  buttons.

## Inline summary cards (v17.0.1.7.0)
- The **Fireflies Summary** tab renders `interview_ids` as a **single-column kanban**.
  Each card shows the full analysis inline (exec summary, Strengths/Concerns cards,
  Highlights, answered Questions via `custom_qa_html`) plus a status badge and
  handles the `idle` / `processing` / `error` / `done` states.
- Card buttons: **Analyze / Retry / Re-analyze** (`action_analyze`, object buttons) and
  **Open / Edit** (`action_open_form`, full-page). Editing (link, questions, note) still
  happens on the interview **form** — a nested editable list can't live in a kanban card
  without a custom JS widget, so the form is the edit surface while reading is inline.
- Styles: shared `.o_ff_card` / `.o_ff_ok` / `.o_ff_risk` / `.o_ff_note` accents plus
  `.o_ff_kanban_card`; the `interview_ids` kanban is forced full-width single-column in
  `static/src/scss/fireflies.scss`.

## Important patterns / constraints
- **Reuse, don't rebuild:** OpenAI client/keys and `_openai_call` come from
  `hr_recruitment_extract_openai`; Fireflies + OpenAI keys live on `res.company`.
  `hr_recruitment_forms` is still a declared dependency (kept for compatibility) but
  the module no longer uses `hr.form.template`.
- AI output language is **plain business English** (not elevated/C2) and **evidence-based**:
  the prompt normalizes colloquial candidate speech into standard business English, forbids
  inventing facts, and excludes protected/personal characteristics.
- All summary HTML is built with `markupsafe` escaping; `Html` fields are sanitized
  (except `custom_qa_html`, which is built server-side from escaped values).
- Background work uses `queue_job`; ensure its runner is enabled on the environment.
- **Migrations** (`migrations/17.0.1.7.0/`): pre deletes legacy template Q&A rows
  (`is_custom = False`); post carries any leftover free-text `custom_questions` into
  question rows for interviews that had no custom rows yet.

## Changes in v17.0.1.8.0
- **Business-English output.** Both prompts (`INTERVIEW_SUMMARY_PROMPT`,
  `CUSTOM_QUESTIONS_PROMPT`) now require **plain business English, not C2/academic**, and
  explicitly normalize very casual/slangy candidate speech into a standard business
  register (short near-verbatim quotes remain allowed only in `highlights`).
- **`Type` removed from the UI.** `interview_type` is no longer shown on the form or tree
  and is no longer fed to the AI (`_build_model_input` dropped the "Interview type" line).
  The field is **kept on the model** (marked DEPRECATED) so existing data is preserved —
  no migration; the column can be dropped later.
- **Title (`name`) is no longer auto-filled.** The `_compute_name` compute was removed;
  `name` is now a plain optional `Char`. New interviews start **empty**, showing the grey
  placeholder *"e.g. Initial interview"*; existing titles are untouched.
- **Custom questions hidden (not removed).** The `o_ff_custom` block on the interview form
  is `invisible="1"`. The model, `custom_qa_line_ids`, `action_answer_custom_questions`
  and `_run_custom_questions_job` are intentionally **kept** for a later rework.

## Changes in v17.0.1.8.1
- **Recruiter Note now visible on the inline card.** Previously `recruiter_note` rendered
  only on the interview **form** (Open/Edit), so recruiters couldn't see it from the
  candidate's **Fireflies Summary** tab. The kanban card now shows a **Recruiter Note**
  block (styled `.o_ff_note`) in the `done` state **when the note has content**
  (`t-if="record.recruiter_note.raw_value"`). Editing stays on the form — a rich-text
  `Html` field can't be edited inside a kanban card without a custom JS widget.

## Changes in v17.0.1.8.2
- **Old auto-titles cleared.** `migrations/17.0.1.8.2/post-migration.py` blanks any
  interview `name` that still exactly matches the old auto pattern
  (`"<Type label> - <candidate>"`, or `"<Type label>"` with no candidate) for the record's
  current type + candidate. Hand-typed titles are preserved. New interviews already start
  empty (compute removed in v17.0.1.8.0).
- **Inline card actions.** The Fireflies Summary card gained two buttons next to
  *Open / Edit*: **Open in Fireflies** (`action_open_fireflies`, shown when
  `fireflies_link` is set — previously reachable only from the form header) and **Delete**
  (`action_delete_interview`, red, with a confirm dialog).
- **`action_delete_interview`** (`models/hr_applicant_interview.py`): `unlink()`s the
  interview and returns a `reload` client action so the removed card disappears from the
  candidate's tab.
