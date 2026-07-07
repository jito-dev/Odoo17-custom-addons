# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

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

    @api.depends('interview_ids.state')
    def _compute_interview_count(self):
        for applicant in self:
            interviews = applicant.interview_ids
            applicant.interview_count = len(interviews)
            applicant.interview_analyzed_count = len(
                interviews.filtered(lambda i: i.state == 'done')
            )

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
