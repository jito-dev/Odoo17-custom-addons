# -*- coding: utf-8 -*-
import hashlib
import html
import logging
import re
from typing import List

from markupsafe import Markup, escape
from pydantic import BaseModel, Field

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .openai_prompts import INTERVIEW_SUMMARY_PROMPT

_logger = logging.getLogger(__name__)

# Minimum number of transcript sentences before we bother calling the model.
# Guards against hallucinating a summary from an empty/too-short transcript and
# against wasting an OpenAI call.
MIN_SENTENCES = 4

_COVERAGE_VALUES = {'covered', 'partial', 'missed', 'not_asked'}


def _html_to_text(html_val):
    """Crude HTML -> plain text for the clipboard/markdown output."""
    text = str(html_val or '')
    text = text.replace('</li>', '\n').replace('<br>', '\n').replace('<br/>', '\n')
    text = re.sub(r'<li[^>]*>', '- ', text)
    text = re.sub(r'<[^>]+>', '', text)
    return html.unescape(text).strip()


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


class HrApplicantInterview(models.Model):
    """A single Fireflies interview attached to a candidate, plus its AI summary."""
    _name = 'hr.applicant.interview'
    _description = 'Candidate Interview (Fireflies)'
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

    question_template_id = fields.Many2one(
        'hr.form.template',
        string="Question Template",
        help="Optional. Used as the lens for the Q&A breakdown: the AI maps the "
             "transcript onto these questions.",
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
    )

    transcript_text = fields.Text(string="Transcript", readonly=True, copy=False)
    summary_clipboard = fields.Text(
        string="Plain-text Summary",
        compute='_compute_summary_clipboard',
        help="Plain-text version of the summary, for copying to the clipboard.",
    )

    has_summary = fields.Boolean(compute='_compute_has_summary')

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

    @api.depends('state', 'executive_summary')
    def _compute_has_summary(self):
        for rec in self:
            rec.has_summary = rec.state == 'done' and bool(rec.executive_summary)

    @api.depends('executive_summary', 'strengths', 'concerns', 'highlights',
                 'qa_line_ids.question', 'qa_line_ids.answer', 'qa_line_ids.coverage')
    def _compute_summary_clipboard(self):
        coverage_labels = dict(self.env['hr.applicant.interview.qa']._fields['coverage'].selection)
        for rec in self:
            if rec.state != 'done':
                rec.summary_clipboard = ''
                continue
            parts = []
            title = rec.name or _("Interview Summary")
            parts.append(title)
            parts.append("=" * len(title))

            if rec.executive_summary:
                parts.append("\nSUMMARY\n" + _html_to_text(rec.executive_summary))
            if rec.strengths:
                parts.append("\nSTRENGTHS\n" + _html_to_text(rec.strengths))
            if rec.concerns:
                parts.append("\nCONCERNS / RISKS\n" + _html_to_text(rec.concerns))
            if rec.highlights:
                parts.append("\nHIGHLIGHTS\n" + _html_to_text(rec.highlights))
            if rec.qa_line_ids:
                qa_lines = ["\nQ&A"]
                for line in rec.qa_line_ids:
                    cov = coverage_labels.get(line.coverage, '')
                    qa_lines.append("Q: %s [%s]" % (line.question, cov))
                    if line.answer:
                        qa_lines.append("A: %s" % line.answer)
                parts.append("\n".join(qa_lines))
            rec.summary_clipboard = "\n".join(parts).strip()

    # --- Actions ---
    def action_analyze(self):
        """Validate inputs, mark processing and enqueue the background analysis."""
        for rec in self:
            if not rec.fireflies_link:
                raise UserError(_("Please paste a Fireflies link first."))
            # Surface missing keys early, before queueing.
            self.env['fireflies.client']._get_api_key(company=rec.company_id or self.env.company)
            rec.write({
                'state': 'processing',
                'state_message': _("Fetching the Fireflies transcript..."),
            })
            rec.with_delay()._run_interview_analysis_job(self.env.user.id)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Analysis started'),
                'message': _('The interview is being analyzed in the background.'),
                'type': 'info',
            },
        }

    def action_print_summary(self):
        self.ensure_one()
        return self.env.ref(
            'hr_recruitment_fireflies.action_report_interview_summary'
        ).report_action(self)

    # --- Background job ---
    def _run_interview_analysis_job(self, user_id):
        """Fetch transcript, run the quality gate, call OpenAI, store the summary."""
        self.ensure_one()
        try:
            company = self.company_id or self.env.company

            # 1. Fetch transcript
            result = self.env['fireflies.client'].fetch_transcript(
                self.fireflies_link, company=company,
            )
            transcript = result['text']
            sentences = result['sentences']

            # 2. Quality gate
            if len(sentences) < MIN_SENTENCES:
                self.write({
                    'state': 'error',
                    'state_message': _(
                        "Transcript is too short to summarize (%s lines). "
                        "Check the Fireflies link.", len(sentences)
                    ),
                    'meeting_id': result['meeting_id'],
                    'transcript_text': transcript,
                })
                self._notify(user_id, _('Interview not analyzed'),
                             _('The transcript is too short to summarize.'),
                             'warning', sticky=True)
                return

            # 3. Build the lens questions + cost guard hash
            lens_questions = self._get_lens_questions()
            new_hash = self._compute_input_hash(transcript, lens_questions)
            if self.state == 'done' and self.input_hash == new_hash and self.executive_summary:
                self.write({'state_message': _("No transcript change since last analysis.")})
                self._notify(user_id, _('No changes'),
                             _('The transcript is unchanged; summary kept as is.'), 'info')
                return

            self.write({
                'meeting_id': result['meeting_id'],
                'transcript_text': transcript,
                'state_message': _("Analyzing the transcript with AI..."),
            })

            # 4. Call OpenAI (reuse the shared client from hr_recruitment_extract_openai)
            text_content = self._build_model_input(transcript, lens_questions, result.get('title'))
            model_name = (company.openai_model or 'gpt-4o').strip()
            parsed = self.env['hr.applicant']._openai_call(
                attachment=None,
                prompt=INTERVIEW_SUMMARY_PROMPT,
                text_format=InterviewSummarySchema,
                text_content=text_content,
                company=company,
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
            self._notify(user_id, _('Interview summary ready'),
                         _('The AI summary for "%s" is ready.', self.name), 'success')

        except Exception as e:
            _logger.error("Interview analysis failed for %s: %s", self.id, e, exc_info=True)
            self.write({
                'state': 'error',
                'state_message': _("Error: %s", str(e)),
            })
            self._notify(user_id, _('Interview analysis failed'),
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

    def _apply_summary(self, data):
        """Write the AI output to the summary fields and rebuild Q&A lines."""
        self.ensure_one()
        vals = {
            'executive_summary': escape(data.get('executive_summary') or '') or False,
            'strengths': self._bullets_to_html(data.get('strengths')),
            'concerns': self._bullets_to_html(data.get('concerns')),
            'highlights': self._bullets_to_html(data.get('highlights')),
            'qa_line_ids': [(5, 0, 0)],
        }
        qa_commands = []
        for seq, item in enumerate(data.get('qa') or [], start=1):
            coverage = (item.get('coverage') or 'not_asked').strip().lower()
            if coverage not in _COVERAGE_VALUES:
                coverage = 'not_asked'
            qa_commands.append((0, 0, {
                'sequence': seq * 10,
                'question': (item.get('question') or '').strip() or _("(question)"),
                'answer': (item.get('answer') or '').strip(),
                'coverage': coverage,
            }))
        if qa_commands:
            vals['qa_line_ids'] = [(5, 0, 0)] + qa_commands
        self.write(vals)

    def _notify(self, user_id, title, message, ntype, sticky=False):
        self.env['hr.applicant']._notify_user(user_id, {
            'title': title,
            'message': message,
            'type': ntype,
            'sticky': sticky,
        })
