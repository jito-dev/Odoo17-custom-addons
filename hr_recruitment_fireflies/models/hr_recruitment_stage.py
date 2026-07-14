# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import UserError


class HrRecruitmentStage(models.Model):
    """Adds the "Interview Questions" entry to the stage form.

    Fireflies owns the per-(job, stage) interview questions
    (``hr.job.stage.config.interview_question_ids``). This sibling button —
    next to hr_recruitment_call_stage's "Configure Call Stage" button, in the
    shared ``<header>`` anchor from hr_recruitment_job_stage_config — opens a
    focused questions-only dialog so a recruiter can set the questions for ANY
    stage (call or not) without going through the call config.
    """
    _inherit = 'hr.recruitment.stage'

    def action_open_interview_questions_for_job(self):
        """Open the per-(job, stage) interview questions for the job currently
        in context, find-or-creating the config row.

        Bound to the "Interview Questions" button on the stage form (stage gear
        → Edit). ``default_job_id`` comes from the kanban action context the
        stage form was opened with; the button is hidden when it is absent, so
        the UserError below is only a programmatic-call safeguard.
        """
        self.ensure_one()
        job_id = self.env.context.get('default_job_id')
        try:
            job_id = int(job_id) if job_id else False
        except (TypeError, ValueError):
            job_id = False
        if not job_id:
            raise UserError(_(
                "Open this stage from a specific vacancy's Applications kanban "
                "(Recruitment → Vacancies → [job] → Applications) to edit its "
                "interview questions."))
        Config = self.env['hr.job.stage.config'].sudo()
        config = Config.search([
            ('job_id', '=', job_id),
            ('stage_id', '=', self.id),
        ], limit=1)
        if not config:
            config = Config.create({
                'job_id': job_id,
                'stage_id': self.id,
            })
        job = self.env['hr.job'].browse(job_id)
        view = self.env.ref(
            'hr_recruitment_fireflies.view_hr_job_stage_config_form_questions_only')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Interview questions — %(job)s · %(stage)s',
                      job=job.display_name, stage=self.name),
            'res_model': 'hr.job.stage.config',
            # Explicit ``views`` (not just view_mode): this dict goes straight to
            # the JS action service from the button, which never runs the action
            # loader that would otherwise populate it.
            'views': [[view.id, 'form']],
            'view_mode': 'form',
            'res_id': config.id,
            'target': 'new',
            'context': {
                'default_job_id': job_id,
                'default_stage_id': self.id,
            },
        }
