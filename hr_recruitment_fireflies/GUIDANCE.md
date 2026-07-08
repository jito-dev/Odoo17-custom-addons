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

## Changes in v17.0.1.16.0 — Newest-first cards & stage-named drafts
- **Newest interview on top.** `hr.applicant.interview._order` changed from
  `sequence, id` to **`sequence, id desc`**, so the just-created draft / freshly-analyzed
  interview shows at the **top** of the stacked Fireflies Summary cards and older analyses
  drop below it. `sequence` stays the primary key (manual ordering still wins if ever set);
  `id desc` is only the newest-first tiebreak.
- **Draft Title pre-filled from the stage.** `_seed_questions_from_stage` now sets
  `name = source_stage.name` when the title is empty (only when the stage actually has
  template questions, i.e. the same condition that seeds them). The `source_stage` is the
  stage whose template drove the questions (own stage, or the paired **Call Stage** on a
  Call Booked companion — same one reported in the "Seeded from … stage" chatter line).
  Covers every creation path (autopilot stage-entry draft + the *Analyze* quick-link).
  This supersedes the v17.0.1.8.0 "Title is no longer auto-filled" note **for auto-created
  drafts**: a recruiter-typed title is still never overwritten.

## Changes in v17.0.1.15.1 — Fix "False" in notifications
- **`_notify_label()` helper.** The "summary ready" / "questions answered" notifications
  formatted a bare `self.name` into `"%s"`; on the common empty-title draft that rendered
  the literal **`False`**. They now use `_notify_label()` = `name or candidate name or
  "interview"`, so the message always reads sensibly.

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

## Changes in v17.0.1.9.0 — Recruiter questions re-enabled & reworked (Phase 1)
Supersedes the "Custom questions hidden" note in v17.0.1.8.0. The feature is **visible
again** and polished; still **manual, transcript-only, and independent of the client
summary** (a separate "Ask AI" run, no Fireflies quota spent, summary untouched).
- **Form UI un-hidden & de-nested.** The `o_ff_custom` block is no longer `invisible="1"`
  and no longer lives inside the `state == 'done'` summary `div`. It is now a **peer of
  the summary**, gated on **`has_transcript`** (available as soon as a transcript is
  cached, even during a re-analysis). It has a teal (`--info`) identity to read as
  separate from the primary/purple Analyze pipeline, plus the standing helper line
  *"Answered only from the saved transcript — this does not change the client summary."*
- **Two buttons + empty state.** **Ask AI** (`custom_state in (idle,error)`) and
  **Re-answer** (`custom_state == done`, with a confirm), both hidden while `processing`
  and both hidden when there are no questions (an empty-state hint shows instead, so the
  button never dead-ends into the server `UserError`). A new **non-stored**
  `custom_qa_count` compute drives this. The question tree gained a `handle` for
  reordering; `answer`/`coverage` stay read-only.
- **Inline Q&A on the candidate card.** The Fireflies Summary kanban card now renders
  the answered questions via the existing `custom_qa_html` (read-only, edit on the form),
  guarded by `t-if="record.custom_qa_html.raw_value"` — same pattern as Highlights /
  Recruiter Note. `custom_qa_html` now also renders a **coverage chip** per row
  (`_COVERAGE_LABEL` map → `.o_ff_cov--*` SCSS); still fully `escape()`-d, so the field's
  `sanitize=False` stays safe.
- **Better AI answers (`CUSTOM_QUESTIONS_PROMPT`).** Rewritten with an explicit coverage
  rubric + examples (clear `missed` vs `not_asked`), multi-part question handling, an
  anti-hedging rule, "echo the question word-for-word, exactly one entry per question"
  (hardens the `_write_custom_answers` text-match), and a short inline
  `Evidence: "<quote ≤20 words>"` appended to `covered`/`partial` answers — **folded into
  the answer text, so no schema/model/migration change.**
- **Sharper grounding.** `_build_custom_input` now also passes the **structured Job
  Requirements** (the `requirements` branch of `_get_role_context` only — not the 4000-char
  JD) to help interpret questions; guarded to never be answered instead of the questions.
- **Safety guard.** `_run_custom_questions_job` now raises (keeps existing answers) when
  the model returns an **empty `qa` list**, instead of silently clobbering previously
  answered rows with blanks.
- **No migration / no stored-schema change.** `custom_qa_count` is non-stored; evidence is
  in-text. Version bumped `17.0.1.8.3 → 17.0.1.9.0`.
- **Deferred to Phase 2:** per-stage default questions on `hr.job.stage.config` (register
  the new field in that module's `_PAYLOAD_FIELDS`) with auto-seeding of `custom_qa_line_ids`.
- **Verify note (queue_job):** the local **odoo_dev tmux** session is started with
  `--load=base,web,queue_job`, so the runner **IS active** here (verified: a probe job goes
  `pending → done` in ~1s), and **Ask AI** completes on its own. This differs from **odoo.sh**,
  which has no `--load` and so no runner — there, run the job manually via `odoo shell`
  (`interview._run_custom_questions_job(user_id)`). Prod has the runner.

## Changes in v17.0.1.10.0 — Per-(job, stage) default questions (Phase 2)
Recruiters can now define **default interview questions per (vacancy, stage)** that are
**auto-seeded** into a new interview, so a candidate's interview starts with the right
questions already listed and the recruiter only clicks **Ask AI**.
- **New dependency:** `hr_recruitment_job_stage_config`.
- **Storage:** a `Text` field **`interview_question_template`** (one question per line) added
  to `hr.job.stage.config` via `_inherit` (`models/hr_job_stage_config.py`). Chosen over a
  child model to avoid a new model/ACL; `_fireflies_question_lines()` returns the template as
  a de-duplicated, order-preserving list. **Reserved in `_PAYLOAD_FIELDS`** of
  `hr_recruitment_job_stage_config` (bumped to 17.0.1.3.2) so the stage scope-flip cleanup
  counts these questions as payload and never drops a config row whose only data is them —
  this is the module's documented contract; missing it silently deletes rows.
- **Config UI:** a new **"Interview Questions"** page on the stage-config form
  (`views/hr_job_stage_config_views.xml`, inherits
  `hr_recruitment_job_stage_config.view_hr_job_stage_config_form`).
- **Seeding:** `hr.applicant.interview.create` (override) → `_seed_questions_from_stage()`
  looks up the `(applicant.job_id, applicant.stage_id)` config row and copies its questions
  into `custom_qa_line_ids` (as `is_custom=True` rows), logging a chatter line. **Idempotent
  and non-destructive:** only a brand-new interview *with no questions of its own* is seeded;
  editing the template later never touches existing interviews. Pass context
  `fireflies_no_seed_questions=True` to opt out (e.g. programmatic/copy).
- **No migration** (fresh column, no reshape). Phase 2 completes the plan from
  v17.0.1.9.0; Phase-1 recruiter editing/answering is unchanged.

## Changes in v17.0.1.15.0 — Transcript retention (GDPR data minimization)
- **Daily retention cron** (`data/ir_cron_data.xml` → `hr.applicant.interview._gc_transcripts`)
  clears the stored raw `transcript_text` (+ `meeting_id`) once an interview is older than
  its company's retention window. The **AI summary, recruiter note and answered questions are
  kept** — only the heavy transcript (personal data) is removed. A purged interview simply
  re-fetches from Fireflies if it is ever re-analyzed (`_needs_fetch` returns True once
  `transcript_text` is empty), so re-analysis still works (costs one Fireflies request).
- **Per-company window** `res.company.fireflies_transcript_retention_days` (default **30**;
  related field on `res.config.settings`, shown in Settings → Recruitment under the Fireflies
  Autopilot toggle). **0 disables** retention (keep transcripts indefinitely).
- **Age** is measured from `last_generated`, falling back to `create_date`. Only terminal
  interviews (`done`/`error`) are purged — never a `processing` one (its job may still need
  the text). Each purge posts a chatter line.
- **No migration** (new Integer column + new cron). Reversible: `-u` recreates nothing to undo;
  set the window to 0 to stop purging.

## Changes in v17.0.1.14.2 — Stop generating Highlights
- **Highlights no longer generated by the AI.** Removed from `InterviewSummarySchema`,
  `INTERVIEW_SUMMARY_PROMPT` (output bullet + the near-verbatim-quote allowance that pointed
  at it), and `_apply_summary`; the unused kanban field declaration was dropped too. The
  `highlights` **field is kept** on the model (marked DEPRECATED) so existing analyzed
  interviews keep their data; re-adding the schema slot + prompt bullet + view block brings it
  back. Saves output tokens on every analysis.

## Changes in v17.0.1.14.1 — Hide Highlights, shorten note label
- **Highlights removed from the UI** (interview form + candidate card). The `highlights`
  field, its `InterviewSummarySchema` slot and prompt bullet are **kept** (still generated,
  just not shown), so it is trivially reversible — re-add the view block to bring it back.
- **Internal note label shortened** to just "Internal note" (was "Internal note — not shared
  with client") on both form and card.
- View-only change; applied with `-u` (no restart needed, no migration).

## Changes in v17.0.1.14.0 — Paste-a-link, draft under the hood
Reworks the autopilot entry point so the recruiter never sees an empty draft.
- **Empty drafts hidden.** The Fireflies Summary tab's `interview_ids` kanban is now
  domained `[('fireflies_link','!=',False)]` and `create="false"`, so linkless auto-drafts
  stay out of sight; only interviews that have a link (processing / done / error) are listed.
- **Paste-a-link box.** New `hr.applicant.fireflies_quick_link` Char + **Analyze** button at
  the top of the tab (`action_fireflies_analyze_quick_link`): routes the pasted link to the
  pending hidden draft (or creates a fresh interview that seeds the stage's questions), starts
  the analysis, and clears the box. Works with or without the autopilot toggle (the button is
  an explicit analyze; if autopilot already auto-started on the link write, it is not started
  twice). The result card appears on the standard post-button record reload.
- The stage-entry auto-draft (v1.12) is unchanged — it just lives **under the hood** now until
  it gets a link. No migration (new non-stored-workflow Char column).

## Changes in v17.0.1.13.0 — Interview card redesign
Light recompose of the interview **form** (and the candidate summary **card**) for scanning,
reconciled against a redesign brief that was written for the old v1.1 (its `qa_line_ids`,
`question_template_id`, `interview_type`, Copy-for-client/PDF, and the `"]}` highlights bug
are all obsolete/removed here — not reintroduced).
- **Key-fact chips (new).** Three AI-extracted `Char` fields — `candidate_location`,
  `availability`, `salary_expectation` — added to `InterviewSummarySchema` +
  `INTERVIEW_SUMMARY_PROMPT` (fill ONLY when explicitly stated, else ""), written in
  `_apply_summary`. Rendered as chips (`.o_ff_chips`/`.o_ff_chip`) above the summary, each
  hidden when empty; the whole row hides when all three are empty. Only populate on new/
  re-run analyses (old interviews show none until re-analyzed).
- **Q&A moved above Strengths/Concerns**, and `custom_qa_html` is now **covered-first**
  (`covered → partial → missed → not_asked`, then sequence) on both form and card.
- **Internal note.** `recruiter_note` moved out of the summary into an `alert alert-warning`
  captioned *"Internal note — not shared with client"* (`.o_ff_internal_label`), on form and
  card. It was already excluded from any client export (there is no Copy/PDF export).
- Labels lowered to sentence case ("Summary for client", "Concerns / risks").
- No migration (new Char columns; `custom_qa_html` non-stored).

## Changes in v17.0.1.12.0 — Fireflies Autopilot (hands-free)
Opt-in, per-company **`res.company.fireflies_autopilot`** (default **False**; toggle in
Settings → Recruitment → *Fireflies Autopilot*). When ON, for that company:
1. **Auto-draft on stage entry.** `hr.applicant.create`/`write` (on `stage_id`) →
   `_fireflies_autocreate_draft_interview()`: when the candidate is on a stage that resolves
   to interview questions (its own template, or the paired Call Stage's when on a Call Booked
   companion — via `hr.applicant._fireflies_resolve_stage_questions()`), a **draft interview**
   is created (which seeds those questions). Idempotent (never a 2nd empty draft), wrapped in
   try/except so it can never block a stage move.
2. **Auto-analyze on link paste.** `hr.applicant.interview.write`/`create` →
   `_fireflies_maybe_autostart()`: when a usable `fireflies_link` is present and a fetch is
   needed, it calls `_start_analysis()`. The transcript is still fetched **once** and cached —
   no extra Fireflies quota. Guarded by context `fireflies_no_autostart` + try/except.
3. **Auto-answer questions.** At the end of a successful `_run_interview_analysis_job`, if
   autopilot is on and there are question rows, it chains `_run_custom_questions_job` — so one
   pasted link yields **summary + answered questions** with no clicks.
- **`fireflies_link` is now optional** (was `required=True`) so an empty draft can exist;
  Analyze still validates the link is set. Odoo drops the column NOT NULL on `-u` — no migration.
- New models: `res.company` (+field), `res.config.settings` (related) + settings view.
  Prod stays unaffected until the toggle is switched on.

## Changes in v17.0.1.11.0 — Call Stage-aware question seeding
- **Questions belong on the Call Stage, not its Call Booked companion.** A Fireflies
  interview is usually created *after* the call, when the candidate has already moved from
  the Call Stage to its paired **Call Booked** status stage. So `_seed_questions_from_stage`
  now resolves in two steps: (1) the candidate's current (job, stage) config; (2) if that has
  no questions AND the current stage is a **Call Booked companion**, it falls back to the
  questions on the **paired Call Stage** (`hr.job.stage.config` where `is_call_stage=True` and
  `call_booked_stage_id = current stage`, same job).
- **No hard dependency on `hr_recruitment_call_stage`:** the fallback is **feature-detected**
  (`'call_booked_stage_id' in Config._fields`), so seeding still works when call_stage is
  absent. The chatter message names whichever stage actually supplied the questions.
- Companion side handled in `hr_recruitment_call_stage` v17.0.24.14.0: the
  *"Configure Call Stage for This Job"* button is **hidden on Call Booked companion stages**
  (new context-aware compute `is_call_booked_companion_for_job`), with a warning banner that
  points the recruiter to configure everything (including these questions) on the Call Stage.

## Changes in v17.0.1.10.1 — Questions form UX fix
- **Shorter form / no wide answer column.** The editable questions list on the interview
  form now shows **only the question** (+ drag handle); the wide `answer`/`coverage` tree
  columns were removed (they made rows tall and the form overly long).
- **Answers shown stacked below.** `custom_qa_html` now renders each Q&A as a stacked item —
  the question (with its coverage chip) on top and the **answer highlighted in a card just
  below it** (`.o_ff_qa_item` / `.o_ff_qa_q` / `.o_ff_qa_a`, `white-space: pre-wrap` so the
  `Evidence:` line stays readable) instead of a one-line `<li>`. The form gains a read-only
  **Answers** block (shown only when answered); the candidate kanban card inherits the same
  nicer layout. Still fully `escape()`-d → `sanitize=False` safe.
