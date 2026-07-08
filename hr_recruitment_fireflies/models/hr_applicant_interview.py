# -*- coding: utf-8 -*-
import hashlib
import logging
from datetime import timedelta
from typing import List

from markupsafe import Markup, escape
from pydantic import BaseModel, Field

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

from .openai_prompts import INTERVIEW_SUMMARY_PROMPT, CUSTOM_QUESTIONS_PROMPT

_logger = logging.getLogger(__name__)

# Minimum number of transcript sentences before we bother calling the model.
# Guards against hallucinating a summary from an empty/too-short transcript and
# against wasting an OpenAI call.
MIN_SENTENCES = 4

# Cap the plain-text job description we feed as role context, to keep the prompt
# small when a job has no structured requirements to fall back on.
MAX_DESCRIPTION_CHARS = 4000

_COVERAGE_VALUES = {'covered', 'partial', 'missed', 'not_asked'}

# Short label + CSS class for the coverage chip rendered inside custom_qa_html
# on the inline summary card. Class names must match static/src/scss/fireflies.scss.
_COVERAGE_LABEL = {
    'covered': ('Covered', 'o_ff_cov--covered'),
    'partial': ('Partial', 'o_ff_cov--partial'),
    'missed': ('Not answered', 'o_ff_cov--missed'),
    'not_asked': ('Not asked', 'o_ff_cov--muted'),
}


# --- Pydantic models for structured output ---
class QAItem(BaseModel):
    question: str
    answer: str = ""
    coverage: str = Field(
        default="not_asked",
        description="One of: covered, partial, missed, not_asked",
    )


class InterviewSummarySchema(BaseModel):
    executive_summary: str = ""
    candidate_location: str = ""
    availability: str = ""
    salary_expectation: str = ""
    strengths: List[str] = Field(default_factory=list)
    concerns: List[str] = Field(default_factory=list)


class CustomQASchema(BaseModel):
    """Structured output for the recruiter's own questions (Q&A only)."""
    qa: List[QAItem] = Field(default_factory=list)


class HrApplicantInterview(models.Model):
    """A single Fireflies interview attached to a candidate, plus its AI summary."""
    _name = 'hr.applicant.interview'
    _description = 'Candidate Interview (Fireflies)'
    _inherit = ['mail.thread']
    # Newest first: the just-created draft / freshly-analyzed interview sits on top
    # of the stacked summary cards, with older analyses below. `sequence` stays the
    # primary key so manual ordering (if ever set) still wins; `id desc` is the
    # newest-first tiebreak within the same sequence.
    _order = 'sequence, id desc'

    applicant_id = fields.Many2one(
        'hr.applicant',
        string="Candidate",
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(
        related='applicant_id.company_id',
        store=True,
        readonly=True,
    )
    sequence = fields.Integer(string="Sequence", default=10)

    name = fields.Char(
        string="Title",
        help="Short label for this interview. Optional — left empty by default; "
             "the form shows a placeholder hint until the recruiter types a title.",
    )
    # DEPRECATED: no longer surfaced in the UI nor fed to the AI (as of v17.0.1.8.0).
    # Kept on the model to preserve existing data; safe to drop the column later.
    interview_type = fields.Selection(
        selection=[
            ('screening', 'Screening Call'),
            ('technical', 'Technical Interview'),
            ('client', 'Client Interview'),
            ('hr', 'HR Interview'),
            ('final', 'Final Interview'),
            ('other', 'Other'),
        ],
        string="Type",
        default='screening',
        required=True,
    )
    interview_date = fields.Date(string="Interview Date")
    interviewer_id = fields.Many2one(
        'res.users',
        string="Interviewer",
        default=lambda self: self.env.user,
    )

    fireflies_link = fields.Char(
        string="Fireflies Link",
        help="Paste the Fireflies meeting link (or transcript id) for this interview. "
             "Optional so an empty draft can be auto-created on a call stage; "
             "Analyze still requires it and validates it is set.",
    )
    meeting_id = fields.Char(string="Meeting ID", readonly=True, copy=False)
    fetched_link = fields.Char(
        readonly=True,
        copy=False,
        help="The Fireflies link that produced the stored transcript. Used to "
             "reuse the saved transcript instead of re-fetching from Fireflies.",
    )

    # --- Processing state ---
    state = fields.Selection(
        selection=[
            ('idle', 'Draft'),
            ('processing', 'Processing'),
            ('done', 'Analyzed'),
            ('error', 'Error'),
        ],
        string="Status",
        default='idle',
        copy=False,
        index=True,
    )
    state_message = fields.Text(string="Status Message", readonly=True, copy=False)

    # --- AI summary output ---
    executive_summary = fields.Html(string="Summary for Client", readonly=True, copy=False, sanitize=True)
    strengths = fields.Html(string="Strengths", readonly=True, copy=False, sanitize=True)
    concerns = fields.Html(string="Concerns / Risks", readonly=True, copy=False, sanitize=True)
    # DEPRECATED (v17.0.1.14.x): no longer shown in the UI nor generated by the AI.
    # Kept on the model to preserve data on already-analyzed interviews; safe to drop later.
    highlights = fields.Html(string="Highlights", readonly=True, copy=False, sanitize=True)

    # --- Key facts for the summary chips (filled by the AI only when discussed) ---
    candidate_location = fields.Char(
        string="Location", readonly=True, copy=False,
        help="Candidate location / timezone, extracted from the interview when mentioned.")
    availability = fields.Char(
        string="Availability", readonly=True, copy=False,
        help="Availability / start date / notice period, when mentioned.")
    salary_expectation = fields.Char(
        string="Salary Expectation", readonly=True, copy=False,
        help="Compensation expectation, when mentioned.")

    # --- Recruiter's own questions (answered from the saved transcript only) ---
    # The recruiter adds questions as rows; "Answer" fills the answer/coverage in
    # place. There is no separate template-driven Q&A table anymore.
    custom_qa_line_ids = fields.One2many(
        'hr.applicant.interview.qa', 'interview_id', string="Questions", copy=False,
        domain=[('is_custom', '=', True)],
    )
    custom_qa_html = fields.Html(
        string="Answered Questions",
        compute='_compute_custom_qa_html',
        sanitize=False,
        help="Read-only rendering of the answered questions for the summary card.",
    )
    custom_qa_count = fields.Integer(
        compute='_compute_custom_qa_count',
        help="Number of recruiter questions on this interview. Drives the "
             "Ask AI / empty-state UI without loading the question rows.",
    )
    custom_state = fields.Selection(
        selection=[
            ('idle', 'Idle'),
            ('processing', 'Processing'),
            ('done', 'Done'),
            ('error', 'Error'),
        ],
        string="Questions Status",
        default='idle',
        copy=False,
    )
    custom_message = fields.Text(string="Questions Message", readonly=True, copy=False)

    transcript_text = fields.Text(string="Transcript", readonly=True, copy=False)

    # Recruiter's own note. Supplements the AI summary; the AI never reads or
    # overwrites it, and editing it does not trigger a re-analysis.
    recruiter_note = fields.Html(
        string="Recruiter Note",
        sanitize=True,
        help="Your own notes on this interview, shown alongside the AI summary.",
    )

    has_summary = fields.Boolean(compute='_compute_has_summary')
    has_transcript = fields.Boolean(
        compute='_compute_has_transcript',
        help="Lightweight guard for the UI so the heavy transcript text is not "
             "loaded into the form just to toggle buttons.",
    )

    # --- Cost / cache guards ---
    input_hash = fields.Char(readonly=True, copy=False)
    last_generated = fields.Datetime(string="Last Analyzed", readonly=True, copy=False)
    model_used = fields.Char(string="Model Used", readonly=True, copy=False)

    @api.depends('state', 'executive_summary')
    def _compute_has_summary(self):
        for rec in self:
            rec.has_summary = rec.state == 'done' and bool(rec.executive_summary)

    @api.depends('transcript_text')
    def _compute_has_transcript(self):
        for rec in self:
            rec.has_transcript = bool(rec.transcript_text)

    @api.depends('custom_qa_line_ids')
    def _compute_custom_qa_count(self):
        for rec in self:
            rec.custom_qa_count = len(rec.custom_qa_line_ids)

    @api.depends('custom_qa_line_ids.question', 'custom_qa_line_ids.answer',
                 'custom_qa_line_ids.coverage')
    def _compute_custom_qa_html(self):
        """Render the answered questions as a compact read-only list for the card.

        Each row shows a coverage chip + the question + the answer. All values are
        escaped and the chip class is drawn from a fixed map, so the output is safe
        despite the field's sanitize=False (nothing user-controlled reaches the HTML
        un-escaped)."""
        rank = {'covered': 0, 'partial': 1, 'missed': 2, 'not_asked': 3}
        for rec in self:
            answered = rec.custom_qa_line_ids.filtered(lambda r: r.answer).sorted(
                key=lambda r: (rank.get(r.coverage, 9), r.sequence, r.id))
            if not answered:
                rec.custom_qa_html = False
                continue
            items = []
            for r in answered:
                label, cls = _COVERAGE_LABEL.get(
                    r.coverage or 'not_asked', _COVERAGE_LABEL['not_asked'])
                items.append(Markup(
                    "<div class='o_ff_qa_item'>"
                    "<div class='o_ff_qa_q'>"
                    "<span class='o_ff_cov %s'>%s</span>%s</div>"
                    "<div class='o_ff_qa_a'>%s</div>"
                    "</div>") % (
                    cls, escape(label), escape(r.question or ''), escape(r.answer or '')))
            rec.custom_qa_html = Markup(
                "<div class='o_ff_qa'>%s</div>") % Markup('').join(items)

    # --- Create / write: seed questions + autopilot ---
    @api.model_create_multi
    def create(self, vals_list):
        interviews = super().create(vals_list)
        if not self.env.context.get('fireflies_no_seed_questions'):
            for interview in interviews:
                # Only a brand-new interview with no questions of its own gets
                # seeded, so re-parenting / manual rows are never clobbered.
                if not interview.custom_qa_line_ids:
                    interview._seed_questions_from_stage()
        # Autopilot: if created straight away with a link, start the analysis.
        for interview in interviews:
            interview._fireflies_maybe_autostart()
        return interviews

    def write(self, vals):
        res = super().write(vals)
        # Autopilot: pasting/replacing the Fireflies link starts the analysis.
        if 'fireflies_link' in vals:
            for rec in self:
                rec._fireflies_maybe_autostart()
        return res

    def _fireflies_maybe_autostart(self):
        """Autopilot only: kick off the analysis once a usable Fireflies link is
        present. No-op unless the company toggle is on, a link is set, the record
        is not already processing, and a fetch is actually needed. Never raises —
        a missing key or transient error must not block saving the link."""
        self.ensure_one()
        if self.env.context.get('fireflies_no_autostart'):
            return
        company = self.company_id or self.env.company
        if not company.fireflies_autopilot:
            return
        if not self.fireflies_link or self.state == 'processing':
            return
        if not self._needs_fetch():
            return
        try:
            self.with_context(fireflies_no_autostart=True)._start_analysis(force_refresh=False)
        except Exception as e:  # noqa: BLE001 - never block the save
            _logger.warning(
                "Fireflies autopilot: could not auto-start analysis for %s: %s",
                self.id, e)

    def _seed_questions_from_stage(self):
        """Copy the resolved (job, stage) default interview questions onto this
        interview as recruiter question rows. Resolution (own stage, or the paired
        Call Stage when on a Call Booked companion) lives on
        ``hr.applicant._fireflies_resolve_stage_questions``.

        No-op when nothing resolves. Never overwrites existing rows (idempotent);
        editing a template later does not touch interviews already created.
        """
        self.ensure_one()
        if self.custom_qa_line_ids or not self.applicant_id:
            return
        questions, source_stage = self.applicant_id._fireflies_resolve_stage_questions()
        if not questions:
            return
        self.custom_qa_line_ids = [
            (0, 0, {'question': q, 'is_custom': True, 'sequence': (i + 1) * 10})
            for i, q in enumerate(questions)
        ]
        # Pre-fill the draft Title from the stage whose template seeded the
        # questions, so the card is labelled (e.g. "Screening Call") instead of
        # showing an empty title. Only set when the recruiter hasn't typed one.
        if not self.name and source_stage:
            self.name = source_stage.name
        self.message_post(body=_(
            "Seeded %s question(s) from the \"%s\" stage template.",
            len(questions), source_stage.name))

    # --- Actions ---
    def _needs_fetch(self, force_refresh=False):
        """Whether we must pull the transcript from Fireflies (vs. reuse the saved one)."""
        self.ensure_one()
        return force_refresh or not self.transcript_text or self.fetched_link != self.fireflies_link

    @api.model
    def _gc_transcripts(self):
        """Daily cron: purge stored raw transcripts past each company's retention
        window (GDPR data minimization).

        Only the heavy ``transcript_text`` (and the Fireflies ``meeting_id``) is
        cleared; the AI summary, recruiter note and answered questions are kept.
        A purged interview simply re-fetches from Fireflies if it is ever
        re-analyzed (``_needs_fetch`` returns True once ``transcript_text`` is
        empty). Retention is per-company via
        ``res.company.fireflies_transcript_retention_days`` (0 disables it).
        Only terminal interviews (``done``/``error``) are touched — a
        ``processing`` one may still have a running job that needs the text.
        """
        now = fields.Datetime.now()
        purged = 0
        for company in self.env['res.company'].sudo().search([]):
            days = company.fireflies_transcript_retention_days
            if not days or days <= 0:
                continue  # retention disabled for this company
            cutoff = now - timedelta(days=days)
            # Age is measured from the last analysis; fall back to create_date
            # for interviews that never recorded last_generated.
            stale = self.sudo().search([
                ('company_id', '=', company.id),
                ('transcript_text', '!=', False),
                ('state', 'in', ['done', 'error']),
                '|',
                ('last_generated', '<', cutoff),
                '&', ('last_generated', '=', False), ('create_date', '<', cutoff),
            ])
            for rec in stale:
                rec.write({'transcript_text': False, 'meeting_id': False})
                rec.message_post(body=_(
                    "Transcript purged after the %s-day retention window "
                    "(the AI summary is kept). It will be re-fetched from "
                    "Fireflies if this interview is re-analyzed.", days))
            purged += len(stale)
        if purged:
            _logger.info("Fireflies retention: purged %s transcript(s).", purged)
        return purged

    def _start_analysis(self, force_refresh=False):
        """Validate inputs, mark processing and enqueue the background analysis.

        Only contacts Fireflies when the transcript is missing, the link changed,
        or a refresh was explicitly requested; otherwise the saved transcript is
        re-analyzed locally (no Fireflies quota spent).
        """
        for rec in self:
            if not rec.fireflies_link:
                raise UserError(_("Please paste a Fireflies link first."))
            need_fetch = rec._needs_fetch(force_refresh)
            if need_fetch:
                # Surface missing keys early, before queueing (only when we will call Fireflies).
                self.env['fireflies.client']._get_api_key(company=rec.company_id or self.env.company)
            rec.write({
                'state': 'processing',
                'state_message': (_("Fetching the Fireflies transcript...") if need_fetch
                                  else _("Re-analyzing the saved transcript...")),
            })
            rec.message_post(body=(
                _("Analysis started — fetching a fresh transcript from Fireflies.") if need_fetch
                else _("Re-analysis started on the saved transcript.")
            ))
            rec.with_delay()._run_interview_analysis_job(self.env.user.id, force_refresh=force_refresh)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Analysis started'),
                'message': _('The interview is being analyzed in the background.'),
                'type': 'info',
            },
        }

    def action_analyze(self):
        """Analyze the interview, reusing the saved transcript when possible."""
        return self._start_analysis(force_refresh=False)

    def action_refresh_transcript(self):
        """Force a fresh transcript pull from Fireflies, then re-analyze."""
        return self._start_analysis(force_refresh=True)

    def action_open_form(self):
        """Open this interview as a full page (breadcrumb navigation, not a modal)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name or _("Interview"),
            'res_model': 'hr.applicant.interview',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(self.env.ref(
                'hr_recruitment_fireflies.hr_applicant_interview_view_form').id, 'form')],
            'target': 'current',
        }

    def action_open_fireflies(self):
        """Open the original Fireflies recording/transcript in a new browser tab."""
        self.ensure_one()
        if not self.fireflies_link:
            raise UserError(_("No Fireflies link is set for this interview."))
        return {
            'type': 'ir.actions.act_url',
            'url': self.fireflies_link,
            'target': 'new',
        }

    def action_delete_interview(self):
        """Delete this interview (and its analysis) from the candidate's card.

        Used by the Delete button on the inline Fireflies Summary card. The record
        is a real DB row, so we unlink it. Returning a truthy non-action value lets
        the web client soft-reload only the current applicant form (model.load()),
        so the removed card disappears without a full browser page reload.
        """
        self.ensure_one()
        self.unlink()
        return True

    def action_answer_custom_questions(self):
        """Answer the recruiter's own questions from the saved transcript only.

        Reuses the stored transcript (no Fireflies quota) and only fills the answer
        of the existing question rows — the client-facing summary, strengths,
        concerns and highlights are left completely untouched.
        """
        self.ensure_one()
        if not self.transcript_text:
            raise UserError(_(
                "There is no saved transcript yet. Analyze the interview first, "
                "then ask questions."))
        rows = self.custom_qa_line_ids.filtered(lambda r: r.question and r.question.strip())
        if not rows:
            raise UserError(_("Please add at least one question."))
        self.write({
            'custom_state': 'processing',
            'custom_message': _("Answering your questions..."),
        })
        self.message_post(body=_(
            "Answering %s question(s) from the saved transcript.", len(rows)))
        self.with_delay()._run_custom_questions_job(self.env.user.id)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Answering questions'),
                'message': _('Your questions are being answered in the background.'),
                'type': 'info',
            },
        }

    # --- Background job ---
    def _run_interview_analysis_job(self, user_id, force_refresh=False):
        """Analyze the interview: (re)fetch the transcript only when needed, run the
        quality gate, call OpenAI, store the summary.

        The transcript is pulled from Fireflies only on the first analysis, when the
        link changed, or when a refresh is forced. Otherwise the saved transcript is
        reused, so re-analyzing spends no Fireflies quota.
        """
        self.ensure_one()
        try:
            company = self.company_id or self.env.company
            fireflies_title = None

            if self._needs_fetch(force_refresh):
                # 1. Fetch transcript from Fireflies (spends the daily quota)
                result = self.env['fireflies.client'].fetch_transcript(
                    self.fireflies_link, company=company,
                )
                transcript = result['text']
                sentences = result['sentences']
                fireflies_title = result.get('title')

                # 2. Quality gate (only meaningful on a fresh pull)
                if len(sentences) < MIN_SENTENCES:
                    self.write({
                        'state': 'error',
                        'state_message': _(
                            "Transcript is too short to summarize (%s lines). "
                            "Check the Fireflies link.", len(sentences)
                        ),
                        'meeting_id': result['meeting_id'],
                        'transcript_text': transcript,
                        'fetched_link': self.fireflies_link,
                    })
                    self.message_post(body=_(
                        "Analysis stopped: transcript is too short to summarize (%s lines).",
                        len(sentences)))
                    self._notify(user_id, _('Interview not analyzed'),
                                 _('The transcript is too short to summarize.'),
                                 'warning', sticky=True)
                    return

                self.write({
                    'meeting_id': result['meeting_id'],
                    'transcript_text': transcript,
                    'fetched_link': self.fireflies_link,
                })
            else:
                # Reuse the transcript already stored on this interview — no Fireflies call.
                transcript = self.transcript_text

            # 3. Build the role context (from the JD) + cost guard hash
            role_items, role_kind = self._get_role_context()
            new_hash = self._compute_input_hash(transcript, role_items)
            if self.input_hash == new_hash and self.executive_summary:
                self.write({
                    'state': 'done',
                    'state_message': _("No changes since last analysis; summary kept as is."),
                })
                self.message_post(body=_(
                    "Re-analysis skipped: nothing changed since the last analysis, "
                    "summary kept as is."))
                self._notify(user_id, _('No changes'),
                             _('Nothing changed since the last analysis; summary kept as is.'), 'info')
                return

            self.write({'state_message': _("Analyzing the transcript with AI...")})

            # 4. Call OpenAI (reuse the shared client from hr_recruitment_extract_openai)
            text_content = self._build_model_input(
                transcript, role_items, role_kind, fireflies_title)
            model_name = (company.openai_model or 'gpt-4o').strip()
            parsed = self.env['hr.applicant']._openai_call(
                attachment=None,
                prompt=INTERVIEW_SUMMARY_PROMPT,
                text_format=InterviewSummarySchema,
                text_content=text_content,
                company=company,
                # Low temperature: the summary must be grounded and repeatable across
                # re-analyses of the same transcript, not creatively re-worded.
                temperature=0.2,
            )

            # 5. Persist
            self._apply_summary(parsed.model_dump())
            self.write({
                'state': 'done',
                'state_message': _("Summary generated successfully."),
                'input_hash': new_hash,
                'last_generated': fields.Datetime.now(),
                'model_used': model_name,
            })
            self.message_post(body=_(
                "Interview analyzed — AI summary generated with %s.", model_name))
            self._notify(user_id, _('Interview summary ready'),
                         _('The AI summary for "%s" is ready.', self._notify_label()), 'success')

            # Autopilot: chain the recruiter's questions right after the summary,
            # so a single pasted link produces summary + answers hands-free.
            if company.fireflies_autopilot and self.custom_qa_line_ids.filtered(
                    lambda r: r.question and r.question.strip()):
                self.write({
                    'custom_state': 'processing',
                    'custom_message': _("Answering your questions..."),
                })
                self.message_post(body=_(
                    "Autopilot: answering %s question(s) from the transcript.",
                    len(self.custom_qa_line_ids.filtered(lambda r: r.question))))
                self.with_delay()._run_custom_questions_job(user_id)

        except Exception as e:
            _logger.error("Interview analysis failed for %s: %s", self.id, e, exc_info=True)
            self.write({
                'state': 'error',
                'state_message': _("Error: %s", str(e)),
            })
            self.message_post(body=_("Interview analysis failed: %s", str(e)))
            self._notify(user_id, _('Interview analysis failed'),
                         str(e), 'warning', sticky=True)

    def _run_custom_questions_job(self, user_id):
        """Answer the recruiter's questions from the saved transcript, in place."""
        self.ensure_one()
        try:
            if not self.transcript_text:
                raise UserError(_("No saved transcript to answer questions from."))
            rows = self.custom_qa_line_ids.filtered(lambda r: r.question and r.question.strip())
            if not rows:
                raise UserError(_("No questions to answer."))
            questions = [r.question.strip() for r in rows]
            company = self.company_id or self.env.company
            text_content = self._build_custom_input(self.transcript_text, questions)
            parsed = self.env['hr.applicant']._openai_call(
                attachment=None,
                prompt=CUSTOM_QUESTIONS_PROMPT,
                text_format=CustomQASchema,
                text_content=text_content,
                company=company,
                temperature=0.2,
            )
            ai_qa = parsed.model_dump().get('qa') or []
            if not ai_qa:
                # The model returned nothing usable. Do NOT clobber previously
                # answered rows with blanks — surface an error and keep them as-is.
                raise UserError(_(
                    "The AI returned no answers for your questions. Your existing "
                    "answers were kept; please try again."))
            self._write_custom_answers(rows, ai_qa)
            self.write({
                'custom_state': 'done',
                'custom_message': _("Answered %s question(s).", len(rows)),
            })
            self.message_post(body=_(
                "Questions answered — %s question(s) mapped onto the transcript.",
                len(rows)))
            self._notify(user_id, _('Questions answered'),
                         _('Your questions for "%s" were answered.', self._notify_label()), 'success')
        except Exception as e:
            _logger.error("Custom questions failed for %s: %s", self.id, e, exc_info=True)
            self.write({
                'custom_state': 'error',
                'custom_message': _("Error: %s", str(e)),
            })
            self.message_post(body=_("Answering questions failed: %s", str(e)))
            self._notify(user_id, _('Answering questions failed'),
                         str(e), 'warning', sticky=True)

    # --- Helpers ---
    def _get_role_context(self):
        """Return (items, kind) role context for the AI, taken from the job.

        Prefers the structured Job Requirements extracted from the JD file
        (kind='requirements'); falls back to the plain-text Job Description
        (kind='description'). Returns ([], 'none') when the job has neither.
        """
        self.ensure_one()
        job = self.applicant_id.job_id
        if not job:
            return ([], 'none')
        reqs = job.requirement_statement_ids.sorted(lambda r: (r.sequence, r.id))
        names = [r.name.strip() for r in reqs if r.name and r.name.strip()]
        if names:
            return (names, 'requirements')
        if job.description:
            text = html2plaintext(job.description).strip()
            if text:
                return ([text[:MAX_DESCRIPTION_CHARS]], 'description')
        return ([], 'none')

    def _build_model_input(self, transcript, role_items, role_kind, fireflies_title=None):
        """Compose the user message: context block + role context + transcript."""
        self.ensure_one()
        lines = ["### CONTEXT"]
        candidate = self.applicant_id.partner_name or self.applicant_id.display_name
        if candidate:
            lines.append("Candidate: %s" % candidate)
        if self.applicant_id.job_id:
            lines.append("Job title: %s" % self.applicant_id.job_id.name)
        if fireflies_title:
            lines.append("Meeting title: %s" % fireflies_title)
        if role_items and role_kind == 'requirements':
            lines.append("\n### ROLE REQUIREMENTS (from the job description)")
            lines.append("Use these only to judge relevance for strengths/concerns; "
                         "do not score them item by item or invent facts.")
            for i, q in enumerate(role_items, start=1):
                lines.append("%d. %s" % (i, q))
        elif role_items and role_kind == 'description':
            lines.append("\n### ROLE CONTEXT (job description)")
            lines.append("Use this only to judge relevance for strengths/concerns; "
                         "do not invent facts.")
            lines.append(role_items[0])
        lines.append("\n### TRANSCRIPT")
        lines.append(transcript)
        return "\n".join(lines)

    def _build_custom_input(self, transcript, questions):
        """Compose the user message for the recruiter's own questions run."""
        self.ensure_one()
        lines = ["### CONTEXT"]
        candidate = self.applicant_id.partner_name or self.applicant_id.display_name
        if candidate:
            lines.append("Candidate: %s" % candidate)
        if self.applicant_id.job_id:
            lines.append("Job title: %s" % self.applicant_id.job_id.name)
        # Add the short structured role requirements (not the full JD) only to help
        # the model interpret what each question is really asking. Never used as facts.
        role_items, role_kind = self._get_role_context()
        if role_items and role_kind == 'requirements':
            lines.append("\n### ROLE REQUIREMENTS (from the job description)")
            lines.append("Use these only to interpret the questions; do not answer them "
                         "instead of the questions and do not treat them as candidate facts.")
            for i, q in enumerate(role_items, start=1):
                lines.append("%d. %s" % (i, q))
        lines.append("\nQuestions to answer from the transcript:")
        for i, q in enumerate(questions, start=1):
            lines.append("%d. %s" % (i, q))
        lines.append("\n### TRANSCRIPT")
        lines.append(transcript)
        return "\n".join(lines)

    def _compute_input_hash(self, transcript, role_items):
        payload = (transcript or '') + '||' + '|'.join(role_items or [])
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    @staticmethod
    def _norm_question(question):
        """Normalize a question for matching AI answers back to their row."""
        return ' '.join((question or '').lower().split())

    @staticmethod
    def _bullets_to_html(items):
        """Build a sanitized <ul> from a list of strings."""
        items = [str(i).strip() for i in (items or []) if str(i).strip()]
        if not items:
            return False
        lis = Markup('').join(Markup("<li>%s</li>") % escape(i) for i in items)
        return Markup("<ul>%s</ul>") % lis

    def _write_custom_answers(self, rows, ai_qa):
        """Write the AI answers back onto the existing question rows, in place.

        Match by question text first (robust to reordering); fall back to position
        for anything left unmatched. Never creates or deletes question rows, so the
        recruiter's questions stay exactly as typed — one answer per question.
        """
        self.ensure_one()
        by_text = {}
        for item in ai_qa:
            key = self._norm_question(item.get('question'))
            if key and key not in by_text:
                by_text[key] = item
        for idx, row in enumerate(rows):
            item = by_text.pop(self._norm_question(row.question), None)
            if item is None and idx < len(ai_qa):
                item = ai_qa[idx]
            if not item:
                row.write({'answer': '', 'coverage': 'not_asked'})
                continue
            coverage = (item.get('coverage') or 'not_asked').strip().lower()
            if coverage not in _COVERAGE_VALUES:
                coverage = 'not_asked'
            row.write({
                'answer': (item.get('answer') or '').strip(),
                'coverage': coverage,
            })

    def _apply_summary(self, data):
        """Write the AI output to the client-facing summary fields."""
        self.ensure_one()
        self.write({
            'executive_summary': escape(data.get('executive_summary') or '') or False,
            'candidate_location': (data.get('candidate_location') or '').strip() or False,
            'availability': (data.get('availability') or '').strip() or False,
            'salary_expectation': (data.get('salary_expectation') or '').strip() or False,
            'strengths': self._bullets_to_html(data.get('strengths')),
            'concerns': self._bullets_to_html(data.get('concerns')),
        })

    def _notify_label(self):
        """Human-friendly label for notifications when the interview Title is empty.

        The Title (``name``) is optional and usually blank, in which case a bare
        ``self.name`` renders as the literal ``False`` inside a ``"%s"`` message.
        Fall back to the candidate name so the notification reads sensibly."""
        self.ensure_one()
        return (self.name or self.applicant_id.partner_name
                or self.applicant_id.display_name or _("interview"))

    def _notify(self, user_id, title, message, ntype, sticky=False):
        self.env['hr.applicant']._notify_user(user_id, {
            'title': title,
            'message': message,
            'type': ntype,
            'sticky': sticky,
        })
