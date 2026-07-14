# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import html_escape

_logger = logging.getLogger(__name__)


class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    interview_ids = fields.One2many(
        'hr.applicant.interview',
        'applicant_id',
        string="Interviews",
    )
    fireflies_quick_link = fields.Char(
        string="Fireflies link",
        copy=False,
        help="Paste a Fireflies interview link and click Analyze: the interview "
             "(with the stage's questions) is analyzed in the background and the "
             "result appears below. The box clears afterwards.")
    interview_count = fields.Integer(
        string="Interview Count",
        compute='_compute_interview_count',
    )
    interview_analyzed_count = fields.Integer(
        compute='_compute_interview_count',
    )
    # Number of interviews that carry a Fireflies link (any state) — i.e. the
    # records rendered in the "Result" kanban. Drives the Result section header
    # and its empty-state placeholder.
    fireflies_result_count = fields.Integer(
        compute='_compute_interview_count',
    )
    # The "Result" kanban is bound to THIS computed subset, not to interview_ids.
    # A view-level `domain` on a one2many does NOT filter the already-linked
    # sub-records it displays (it only limits what is selectable to add), so the
    # link-less draft would otherwise render in the Result kanban AND in the
    # Source composer above — the exact duplication we are removing. Filtering
    # here guarantees only link-bearing (result) interviews reach the kanban.
    fireflies_result_interview_ids = fields.One2many(
        'hr.applicant.interview',
        compute='_compute_fireflies_result_interviews',
        string="Analyzed interviews",
    )
    # --- "Add interview" inline form (bottom of the Fireflies Summary tab) ---
    fireflies_extra_link = fields.Char(
        string="Fireflies link (extra)", copy=False,
        help="Fireflies link for the extra interview added via '+ Add interview'.")
    fireflies_extra_name = fields.Char(
        string="Interview name (extra)", copy=False,
        help="Optional name for the extra interview; defaults to the chosen stage.")
    fireflies_extra_stage_id = fields.Many2one(
        'hr.recruitment.stage', string="Stage (extra)", copy=False,
        help="Whose question template seeds the extra interview. Left empty means "
             "the next stage in the pipeline is used.")

    # --- Draft card (shown at the top of the Fireflies Summary tab) ---
    fireflies_draft_id = fields.Many2one(
        'hr.applicant.interview',
        string="Pending draft interview",
        compute='_compute_fireflies_composer',
        help="The seeded, not-yet-analyzed interview waiting for a Fireflies link.")
    fireflies_composer_question_count = fields.Integer(
        string="Draft question count",
        compute='_compute_fireflies_composer',
    )
    fireflies_composer_stage_name = fields.Char(
        string="Draft stage label",
        compute='_compute_fireflies_composer',
    )
    fireflies_show_draft_composer = fields.Boolean(
        compute='_compute_fireflies_composer',
    )
    fireflies_draft_questions_html = fields.Html(
        string="Draft questions",
        compute='_compute_fireflies_draft_questions_html',
        sanitize=False,
        help="Read-only preview of the draft's questions (collapsed by default).",
    )

    @api.depends('interview_ids.state', 'interview_ids.fireflies_link')
    def _compute_interview_count(self):
        for applicant in self:
            interviews = applicant.interview_ids
            applicant.interview_count = len(interviews)
            applicant.interview_analyzed_count = len(
                interviews.filtered(lambda i: i.state == 'done')
            )
            applicant.fireflies_result_count = len(
                interviews.filtered(lambda i: i.fireflies_link)
            )

    @api.depends('interview_ids', 'interview_ids.fireflies_link')
    def _compute_fireflies_result_interviews(self):
        """Only interviews that carry a Fireflies link belong in the 'Result'
        kanban. The link-less draft lives in the Source composer above and must
        never leak here (see the field's comment on one2many domain behaviour)."""
        for applicant in self:
            applicant.fireflies_result_interview_ids = \
                applicant.interview_ids.filtered(lambda i: i.fireflies_link)

    @api.depends('interview_ids', 'interview_ids.fireflies_link',
                 'interview_ids.state', 'interview_ids.custom_qa_line_ids',
                 'stage_id', 'job_id')
    def _compute_fireflies_composer(self):
        """Drive the bright 'draft' composer at the top of the Fireflies Summary
        tab: the pending (seeded, link-less) interview, its question count and the
        stage it came from. Falls back to the stage's question template when no
        draft exists yet, so the composer + counter still show (and 'Analyze' will
        create the draft on the fly). Shown whenever there is something to seed."""
        for applicant in self:
            draft = applicant.interview_ids.filtered(
                lambda i: not i.fireflies_link and i.state in ('idle', 'error'))[:1]
            applicant.fireflies_draft_id = draft
            if draft:
                count = len(draft.custom_qa_line_ids)
                label = draft.name or ''
                show = True
            else:
                lines, source = applicant._fireflies_resolve_stage_questions()
                count = len(lines)
                label = source.name if source else ''
                # Root-cause dedupe: when a link-bearing interview is already
                # waiting to be analyzed (idle/processing/error), it IS the
                # paste-link + Analyze entry point — shown in the "Result"
                # kanban below. Don't also raise a phantom stage-template
                # composer that duplicates it (same stage name, same "Draft"
                # badge, second Analyze button).
                pending_linked = applicant.interview_ids.filtered(
                    lambda i: i.fireflies_link and i.state != 'done')
                show = count > 0 and not pending_linked
            applicant.fireflies_composer_question_count = count
            applicant.fireflies_composer_stage_name = label
            applicant.fireflies_show_draft_composer = show

    @api.depends('fireflies_draft_id', 'fireflies_draft_id.custom_qa_line_ids.question',
                 'stage_id', 'job_id')
    def _compute_fireflies_draft_questions_html(self):
        """Render the draft's questions (or the stage template when no draft exists
        yet) as a plain read-only <ul> for the collapsible list on the draft card."""
        for applicant in self:
            draft = applicant.fireflies_draft_id
            if draft:
                questions = [q.question for q in draft.custom_qa_line_ids]
            else:
                questions, _src = applicant._fireflies_resolve_stage_questions()
            if questions:
                items = ''.join('<li>%s</li>' % html_escape(q or '') for q in questions)
                applicant.fireflies_draft_questions_html = (
                    '<ul class="mb-0 ps-3 small">%s</ul>' % items)
            else:
                applicant.fireflies_draft_questions_html = (
                    '<span class="text-muted small">No questions for this stage.</span>')

    def _fireflies_next_stage(self):
        """The stage right after the candidate's current one (by sequence), scoped
        to this job's pipeline. Falls back to the current stage when it is last."""
        self.ensure_one()
        Stage = self.env['hr.recruitment.stage']
        if not self.stage_id:
            return Stage
        stages = Stage.search(
            ['|', ('job_ids', '=', False), ('job_ids', 'in', self.job_id.ids)],
            order='sequence, id')
        ids = stages.ids
        if self.stage_id.id in ids:
            i = ids.index(self.stage_id.id)
            if i + 1 < len(ids):
                return stages[i + 1]
        return self.stage_id

    # --- Fireflies stage questions / autopilot ---
    def _fireflies_resolve_stage_questions(self):
        """Return (question_lines, source_stage) for this candidate's current
        (job, stage): the stage's own template, or — when the candidate sits on a
        Call Booked companion — the paired Call Stage's template. Returns
        ([], empty recordset) when nothing is configured. The Call Stage lookup is
        feature-detected, so there is no hard dependency on hr_recruitment_call_stage.
        """
        self.ensure_one()
        empty = self.env['hr.recruitment.stage']
        if not self.job_id or not self.stage_id:
            return ([], empty)
        Config = self.env['hr.job.stage.config'].sudo()
        stage = self.stage_id
        config = Config.search(
            [('job_id', '=', self.job_id.id), ('stage_id', '=', stage.id)], limit=1)
        lines = config._fireflies_question_lines() if config else []
        if lines:
            return (lines, stage)
        if 'call_booked_stage_id' in Config._fields:
            call_cfg = Config.search([
                ('job_id', '=', self.job_id.id),
                ('call_booked_stage_id', '=', stage.id),
                ('is_call_stage', '=', True),
            ], limit=1)
            if call_cfg and call_cfg._fireflies_question_lines():
                return (call_cfg._fireflies_question_lines(), call_cfg.stage_id)
        return ([], empty)

    def _fireflies_autocreate_draft_interview(self):
        """Autopilot only: ensure a draft interview exists when the candidate is on
        a stage that has interview questions, so the recruiter just pastes the link.

        Idempotent — never creates a second draft while an unused one (no link) is
        already waiting. Never raises: a failure here must not block a stage move.
        """
        self.ensure_one()
        if self.env.context.get('fireflies_no_autodraft'):
            return
        company = self.company_id or self.env.company
        if not company.fireflies_autopilot:
            return
        try:
            lines, _src = self._fireflies_resolve_stage_questions()
            if not lines:
                return
            pending = self.interview_ids.filtered(
                lambda i: not i.fireflies_link and i.state in ('idle', 'processing', 'error'))
            if pending:
                return
            self.env['hr.applicant.interview'].with_context(
                fireflies_no_autodraft=True).create({'applicant_id': self.id})
        except Exception as e:  # noqa: BLE001 - never break the stage move
            _logger.warning(
                "Fireflies autopilot: could not auto-create draft for applicant %s: %s",
                self.id, e)

    @api.model_create_multi
    def create(self, vals_list):
        applicants = super().create(vals_list)
        for applicant in applicants:
            applicant._fireflies_autocreate_draft_interview()
        return applicants

    def write(self, vals):
        res = super().write(vals)
        if 'stage_id' in vals:
            for applicant in self:
                applicant._fireflies_autocreate_draft_interview()
        return res

    def action_fireflies_analyze_quick_link(self):
        """Paste-a-link entry point: route the link to a Fireflies interview and
        analyze it, so the recruiter never has to see or open an empty draft.

        Uses the draft auto-created on the call stage (kept out of sight until it
        has a link) when one is pending, otherwise creates a fresh interview
        (which seeds the stage's questions), then starts the analysis. Works with
        or without the autopilot toggle — the button is an explicit 'analyze'."""
        self.ensure_one()
        link = (self.fireflies_quick_link or '').strip()
        if not link:
            raise UserError(_("Paste a Fireflies link first."))
        draft = self.interview_ids.filtered(
            lambda i: not i.fireflies_link and i.state in ('idle', 'error'))[:1]
        if not draft:
            draft = self.env['hr.applicant.interview'].with_context(
                fireflies_no_autostart=True).create({'applicant_id': self.id})
        self.fireflies_quick_link = False
        # Setting the link may already auto-start the analysis under autopilot;
        # otherwise start it explicitly so the button always analyzes.
        draft.write({'fireflies_link': link})
        if draft.state != 'processing':
            draft._start_analysis(force_refresh=False)
        return True

    def _fireflies_get_or_create_draft(self):
        """Return the pending (link-less, not-analyzed) draft, creating a seeded one
        if none exists yet — so Edit/Analyze on the draft card always have a record."""
        self.ensure_one()
        draft = self.interview_ids.filtered(
            lambda i: not i.fireflies_link and i.state in ('idle', 'error'))[:1]
        if not draft:
            draft = self.env['hr.applicant.interview'].with_context(
                fireflies_no_autostart=True).create({'applicant_id': self.id})
        return draft

    def action_fireflies_edit_draft(self):
        """'Edit' on the draft card: open the draft interview in a dialog (same
        screen) to rename it or edit its questions. Creates the seeded draft on the
        fly if one does not exist yet."""
        self.ensure_one()
        draft = self._fireflies_get_or_create_draft()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Edit draft interview"),
            'res_model': 'hr.applicant.interview',
            'res_id': draft.id,
            'view_mode': 'form',
            'views': [(self.env.ref(
                'hr_recruitment_fireflies.hr_applicant_interview_view_form').id, 'form')],
            'target': 'new',
        }

    def action_fireflies_delete_draft(self):
        """'Delete' on the draft card: discard the pending draft interview."""
        self.ensure_one()
        if self.fireflies_draft_id:
            self.fireflies_draft_id.unlink()
        return True

    # --- "+ Add interview" inline form ---
    def _fireflies_stage_question_lines(self, stage):
        """Question-template lines configured for (this job, the given stage)."""
        self.ensure_one()
        if not stage or not self.job_id:
            return []
        config = self.env['hr.job.stage.config'].sudo().search(
            [('job_id', '=', self.job_id.id), ('stage_id', '=', stage.id)], limit=1)
        return config._fireflies_question_lines() if config else []

    def _fireflies_create_extra_interview(self, analyze):
        """Create a new interview from the '+ Add interview' form, seeded with the
        chosen stage's questions. Optionally start the analysis. Clears the form."""
        self.ensure_one()
        # Empty stage picker means "use the next stage in the pipeline".
        stage = self.fireflies_extra_stage_id or self._fireflies_next_stage()
        link = (self.fireflies_extra_link or '').strip()
        if analyze and not link:
            raise UserError(_("Paste a Fireflies link to analyze, or use 'Save only'."))
        vals = {'applicant_id': self.id}
        if self.fireflies_extra_name:
            vals['name'] = self.fireflies_extra_name.strip()
        elif stage:
            vals['name'] = stage.name
        # Seed from the CHOSEN stage explicitly, not the candidate's current stage.
        interview = self.env['hr.applicant.interview'].with_context(
            fireflies_no_seed_questions=True, fireflies_no_autostart=True).create(vals)
        lines = self._fireflies_stage_question_lines(stage)
        if lines:
            interview.custom_qa_line_ids = [
                (0, 0, {'question': q, 'is_custom': True, 'sequence': (i + 1) * 10})
                for i, q in enumerate(lines)]
        if link:
            interview.write({'fireflies_link': link})
        # Reset the form (stage recomputes back to the next stage).
        self.write({'fireflies_extra_name': False, 'fireflies_extra_link': False,
                    'fireflies_extra_stage_id': False})
        if analyze and interview.state != 'processing':
            interview._start_analysis(force_refresh=False)
        return True

    def action_fireflies_add_create_analyze(self):
        """'Create & analyze' — create the extra interview and start analysis."""
        return self._fireflies_create_extra_interview(analyze=True)

    def action_fireflies_add_save_only(self):
        """'Save only' — create the extra interview without analyzing it."""
        return self._fireflies_create_extra_interview(analyze=False)

    def action_open_interviews(self):
        """Smart-button action: open this candidate's Fireflies interviews."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Interviews'),
            'res_model': 'hr.applicant.interview',
            'view_mode': 'tree,form',
            'domain': [('applicant_id', '=', self.id)],
            'context': {'default_applicant_id': self.id},
            'help': _(
                '<p class="o_view_nocontent_smiling_face">No interviews yet</p>'
                '<p>Paste a Fireflies call link to generate a client-ready AI '
                'summary of the interview.</p>'
            ),
        }
