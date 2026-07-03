# -*- coding: utf-8 -*-
import hashlib
import logging
from typing import List

from markupsafe import Markup, escape
from pydantic import BaseModel, Field

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .openai_prompts import INTERVIEW_SUMMARY_PROMPT, CUSTOM_QUESTIONS_PROMPT

_logger = logging.getLogger(__name__)

# Minimum number of transcript sentences before we bother calling the model.
# Guards against hallucinating a summary from an empty/too-short transcript and
# against wasting an OpenAI call.
MIN_SENTENCES = 4

_COVERAGE_VALUES = {'covered', 'partial', 'missed', 'not_asked'}


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
    strengths: List[str] = Field(default_factory=list)
    concerns: List[str] = Field(default_factory=list)
    highlights: List[str] = Field(default_factory=list)
    qa: List[QAItem] = Field(default_factory=list)


class CustomQASchema(BaseModel):
    """Structured output for the ad-hoc custom-questions run (Q&A only)."""
    qa: List[QAItem] = Field(default_factory=list)


class HrApplicantInterview(models.Model):
    """A single Fireflies interview attached to a candidate, plus its AI summary."""
    _name = 'hr.applicant.interview'
    _description = 'Candidate Interview (Fireflies)'
    _inherit = ['mail.thread']
    _order = 'sequence, id'

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
        compute='_compute_name',
        store=True,
        readonly=False,
        help="Short label for this interview (auto-filled, editable).",
    )
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
        required=True,
        help="Paste the Fireflies meeting link (or transcript id) for this interview.",
    )
    meeting_id = fields.Char(string="Meeting ID", readonly=True, copy=False)
    fetched_link = fields.Char(
        readonly=True,
        copy=False,
        help="The Fireflies link that produced the stored transcript. Used to "
             "reuse the saved transcript instead of re-fetching from Fireflies.",
    )

    question_template_id = fields.Many2one(
        'hr.form.template',
        string="Question Template",
        compute='_compute_question_template_id',
        store=True,
        readonly=False,
        help="Optional lens for the Q&A breakdown: the AI maps the transcript onto "
             "these questions. Defaults to the template set on the candidate's job "
             "(Job → Form Template); you can override or clear it per interview.",
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
    highlights = fields.Html(string="Highlights", readonly=True, copy=False, sanitize=True)
    qa_line_ids = fields.One2many(
        'hr.applicant.interview.qa', 'interview_id', string="Q&A", copy=False,
        domain=[('is_custom', '=', False)],
    )

    # --- Ad-hoc custom questions (answered from the saved transcript only) ---
    custom_questions = fields.Text(
        string="Custom Questions",
        help="Ask your own questions about this candidate, one per line. Click "
             "'Answer these questions' to have the AI answer them from the saved "
             "transcript only — this does not change the client summary above.",
    )
    custom_qa_line_ids = fields.One2many(
        'hr.applicant.interview.qa', 'interview_id', string="Custom Q&A", copy=False,
        domain=[('is_custom', '=', True)],
    )
    custom_state = fields.Selection(
        selection=[
            ('idle', 'Idle'),
            ('processing', 'Processing'),
            ('done', 'Done'),
            ('error', 'Error'),
        ],
        string="Custom Q&A Status",
        default='idle',
        copy=False,
    )
    custom_message = fields.Text(string="Custom Q&A Message", readonly=True, copy=False)

    transcript_text = fields.Text(string="Transcript", readonly=True, copy=False)

    # Recruiter's own note. Supplements the AI summary; the AI never reads or
    # overwrites it, and editing it does not trigger a re-analysis.
    recruiter_note = fields.Html(
        string="Recruiter Note",
        sanitize=True,
        help="Your own notes on this interview. Shown alongside the AI summary; "
             "the AI does not read or change this.",
    )
    # UI-only toggle to expand the heavier Highlights / Q&A sections. Not stored.
    show_details = fields.Boolean(
        string="Show details",
        store=False,
        default=False,
        help="Expand the Highlights and Q&A sections.",
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

    @api.depends('interview_type', 'applicant_id.partner_name')
    def _compute_name(self):
        type_labels = dict(self._fields['interview_type'].selection)
        for rec in self:
            if rec.name:
                continue
            label = type_labels.get(rec.interview_type, _("Interview"))
            candidate = rec.applicant_id.partner_name or rec.applicant_id.display_name
            rec.name = "%s - %s" % (label, candidate) if candidate else label

    @api.depends('applicant_id.job_id')
    def _compute_question_template_id(self):
        """Default the Q&A lens from the candidate's job; never overwrite a manual choice.

        Set the job's Form Template once and every interview inherits it, so recruiters
        don't have to pick a template on each stage. Editable/clearable per interview.
        """
        for rec in self:
            if rec.question_template_id:
                continue
            rec.question_template_id = rec.applicant_id.job_id.form_template_id

    @api.depends('state', 'executive_summary')
    def _compute_has_summary(self):
        for rec in self:
            rec.has_summary = rec.state == 'done' and bool(rec.executive_summary)

    @api.depends('transcript_text')
    def _compute_has_transcript(self):
        for rec in self:
            rec.has_transcript = bool(rec.transcript_text)

    # --- Actions ---
    def _needs_fetch(self, force_refresh=False):
        """Whether we must pull the transcript from Fireflies (vs. reuse the saved one)."""
        self.ensure_one()
        return force_refresh or not self.transcript_text or self.fetched_link != self.fireflies_link

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

    def action_view_transcript(self):
        """Open the raw transcript in a modal dialog."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Transcript — %s", self.name or ''),
            'res_model': 'hr.applicant.interview',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(self.env.ref(
                'hr_recruitment_fireflies.hr_applicant_interview_transcript_view_form').id, 'form')],
            'target': 'new',
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

    def action_answer_custom_questions(self):
        """Answer the ad-hoc custom questions from the saved transcript only.

        Reuses the stored transcript (no Fireflies quota) and only rebuilds the
        separate custom Q&A table — the client-facing summary, strengths, concerns
        and highlights are left completely untouched.
        """
        self.ensure_one()
        if not self.transcript_text:
            raise UserError(_(
                "There is no saved transcript yet. Analyze the interview first, "
                "then ask custom questions."))
        questions = [q.strip() for q in (self.custom_questions or '').splitlines() if q.strip()]
        if not questions:
            raise UserError(_("Please enter at least one custom question (one per line)."))
        self.write({
            'custom_state': 'processing',
            'custom_message': _("Answering your custom questions from the saved transcript..."),
        })
        self.message_post(body=_(
            "Answering %s custom question(s) from the saved transcript.", len(questions)))
        self.with_delay()._run_custom_questions_job(self.env.user.id, questions)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Answering questions'),
                'message': _('Your custom questions are being answered in the background.'),
                'type': 'info',
            },
        }

    # --- Background job ---
    def _run_interview_analysis_job(self, user_id, force_refresh=False):
        """Analyze the interview: (re)fetch the transcript only when needed, run the
        quality gate, call OpenAI, store the summary.

        The transcript is pulled from Fireflies only on the first analysis, when the
        link changed, or when a refresh is forced. Otherwise the saved transcript is
        reused, so re-analyzing (e.g. after adding questions) spends no Fireflies quota.
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

            # 3. Build the lens questions + cost guard hash
            lens_questions = self._get_lens_questions()
            new_hash = self._compute_input_hash(transcript, lens_questions)
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
            text_content = self._build_model_input(transcript, lens_questions, fireflies_title)
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
                         _('The AI summary for "%s" is ready.', self.name), 'success')

        except Exception as e:
            _logger.error("Interview analysis failed for %s: %s", self.id, e, exc_info=True)
            self.write({
                'state': 'error',
                'state_message': _("Error: %s", str(e)),
            })
            self.message_post(body=_("Interview analysis failed: %s", str(e)))
            self._notify(user_id, _('Interview analysis failed'),
                         str(e), 'warning', sticky=True)

    def _run_custom_questions_job(self, user_id, questions):
        """Answer ad-hoc questions from the saved transcript; touches only custom Q&A."""
        self.ensure_one()
        try:
            if not self.transcript_text:
                raise UserError(_("No saved transcript to answer questions from."))
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
            self._apply_custom_qa(parsed.model_dump())
            self.write({
                'custom_state': 'done',
                'custom_message': _("Answered %s custom question(s).", len(questions)),
            })
            self.message_post(body=_(
                "Custom questions answered — %s question(s) mapped onto the transcript.",
                len(questions)))
            self._notify(user_id, _('Custom questions answered'),
                         _('Your custom questions for "%s" were answered.', self.name), 'success')
        except Exception as e:
            _logger.error("Custom questions failed for %s: %s", self.id, e, exc_info=True)
            self.write({
                'custom_state': 'error',
                'custom_message': _("Error: %s", str(e)),
            })
            self.message_post(body=_("Custom questions failed: %s", str(e)))
            self._notify(user_id, _('Custom questions failed'),
                         str(e), 'warning', sticky=True)

    # --- Helpers ---
    def _get_lens_questions(self):
        """Return the ordered list of question titles from the chosen template."""
        self.ensure_one()
        template = self.question_template_id
        if not template:
            return []
        questions = template.question_ids.filtered(lambda q: not q.is_section)
        return [q.title for q in questions.sorted(lambda q: (q.sequence, q.id)) if q.title]

    def _build_model_input(self, transcript, lens_questions, fireflies_title=None):
        """Compose the user message: context block + transcript."""
        self.ensure_one()
        lines = ["### CONTEXT"]
        candidate = self.applicant_id.partner_name or self.applicant_id.display_name
        if candidate:
            lines.append("Candidate: %s" % candidate)
        if self.applicant_id.job_id:
            lines.append("Job title: %s" % self.applicant_id.job_id.name)
        if self.interview_type:
            lines.append("Interview type: %s" % dict(
                self._fields['interview_type'].selection).get(self.interview_type, ''))
        if fireflies_title:
            lines.append("Meeting title: %s" % fireflies_title)
        if lens_questions:
            lines.append("\nInterview questions to map in the Q&A section:")
            for i, q in enumerate(lens_questions, start=1):
                lines.append("%d. %s" % (i, q))
        else:
            lines.append("\nNo interview questions provided: return an empty qa list.")
        lines.append("\n### TRANSCRIPT")
        lines.append(transcript)
        return "\n".join(lines)

    def _build_custom_input(self, transcript, questions):
        """Compose the user message for the custom-questions run."""
        self.ensure_one()
        lines = ["### CONTEXT"]
        candidate = self.applicant_id.partner_name or self.applicant_id.display_name
        if candidate:
            lines.append("Candidate: %s" % candidate)
        if self.applicant_id.job_id:
            lines.append("Job title: %s" % self.applicant_id.job_id.name)
        lines.append("\nQuestions to answer from the transcript:")
        for i, q in enumerate(questions, start=1):
            lines.append("%d. %s" % (i, q))
        lines.append("\n### TRANSCRIPT")
        lines.append(transcript)
        return "\n".join(lines)

    def _compute_input_hash(self, transcript, lens_questions):
        payload = (transcript or '') + '||' + '|'.join(lens_questions or [])
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    @staticmethod
    def _bullets_to_html(items):
        """Build a sanitized <ul> from a list of strings."""
        items = [str(i).strip() for i in (items or []) if str(i).strip()]
        if not items:
            return False
        lis = Markup('').join(Markup("<li>%s</li>") % escape(i) for i in items)
        return Markup("<ul>%s</ul>") % lis

    def _qa_commands(self, data, is_custom):
        """Build (0,0,vals) create commands for Q&A lines from the AI output."""
        commands = []
        for seq, item in enumerate(data.get('qa') or [], start=1):
            coverage = (item.get('coverage') or 'not_asked').strip().lower()
            if coverage not in _COVERAGE_VALUES:
                coverage = 'not_asked'
            commands.append((0, 0, {
                'sequence': seq * 10,
                'question': (item.get('question') or '').strip() or _("(question)"),
                'answer': (item.get('answer') or '').strip(),
                'coverage': coverage,
                'is_custom': is_custom,
            }))
        return commands

    def _apply_summary(self, data):
        """Write the AI output to the summary fields and rebuild the template Q&A lines.

        Only the template-driven (non-custom) Q&A is rebuilt; ad-hoc custom Q&A lines
        are kept intact so a full re-analysis never wipes the recruiter's own questions.
        """
        self.ensure_one()
        # qa_line_ids is domained to is_custom=False, so this touches only template lines.
        self.qa_line_ids.unlink()
        self.write({
            'executive_summary': escape(data.get('executive_summary') or '') or False,
            'strengths': self._bullets_to_html(data.get('strengths')),
            'concerns': self._bullets_to_html(data.get('concerns')),
            'highlights': self._bullets_to_html(data.get('highlights')),
            'qa_line_ids': self._qa_commands(data, is_custom=False),
        })

    def _apply_custom_qa(self, data):
        """Rebuild only the custom Q&A table from the ad-hoc questions run."""
        self.ensure_one()
        # custom_qa_line_ids is domained to is_custom=True, so template Q&A is untouched.
        self.custom_qa_line_ids.unlink()
        self.write({'custom_qa_line_ids': self._qa_commands(data, is_custom=True)})

    def _notify(self, user_id, title, message, ntype, sticky=False):
        self.env['hr.applicant']._notify_user(user_id, {
            'title': title,
            'message': message,
            'type': ntype,
            'sticky': sticky,
        })
