from odoo import api, fields, models


class HrJob(models.Model):
    _inherit = 'hr.job'

    add_test_task = fields.Boolean(
        "Add Test Task",
        help="If checked, Test Task stages and tabs will be enabled for this job.")

    test_task_url = fields.Char(
        "Test Task URL",
        help="Link to the test task description (e.g. GitHub repository). "
             "Included in the invitation email sent to candidates.")

    @api.model_create_multi
    def create(self, vals_list):
        jobs = super().create(vals_list)
        for job in jobs:
            if job.add_test_task:
                job._manage_test_task_stages(True)
        return jobs

    def write(self, vals):
        res = super().write(vals)
        if 'add_test_task' in vals:
            for job in self:
                job._manage_test_task_stages(vals['add_test_task'])
        return res

    def _manage_test_task_stages(self, enable):
        """Maintain the three Test Task stages on the recruitment kanban for
        this job. Per-job URL isolation is handled by ``test_task_url``
        directly — the invite template reads ``object.job_id.test_task_url``,
        so each job naturally gets its own link without per-stage overrides.
        """
        self.ensure_one()

        stages_config = [
            {'name': 'Test Task Given', 'sequence': 10, 'fold': False},
            {'name': 'Test Task Submitted', 'sequence': 11, 'fold': False},
            {'name': 'Test Task ChatGPT Analyzed', 'sequence': 12, 'fold': True},
        ]

        Stage = self.env['hr.recruitment.stage']
        # hr_recruitment_job_stage_config gates kanban visibility via
        # hr.job.stage.config rows: a 'specific'-scope stage is only shown for
        # a job that has a config row with visible=True. Linking job_ids alone
        # is not enough — we must materialise the config row too, otherwise
        # the three test task stages stay hidden on the kanban dashboard.
        StageConfig = self.env.get('hr.job.stage.config')

        for config_def in stages_config:
            stage = Stage.search([('name', '=', config_def['name'])], limit=1)
            if enable:
                if not stage:
                    stage = Stage.create({
                        'name': config_def['name'],
                        'sequence': config_def['sequence'],
                        'job_ids': [(4, self.id)],
                        'fold': config_def['fold'],
                    })
                elif self.id not in stage.job_ids.ids:
                    stage.write({'job_ids': [(4, self.id)]})

                if StageConfig is not None:
                    existing = StageConfig.sudo().search([
                        ('job_id', '=', self.id),
                        ('stage_id', '=', stage.id),
                    ], limit=1)
                    if existing:
                        if not existing.visible:
                            existing.write({'visible': True})
                    else:
                        StageConfig.sudo().create({
                            'job_id': self.id,
                            'stage_id': stage.id,
                            'sequence': config_def['sequence'],
                            'visible': True,
                        })
            else:
                if stage and self.id in stage.job_ids.ids:
                    stage.write({'job_ids': [(3, self.id)]})
                if StageConfig is not None and stage:
                    existing = StageConfig.sudo().search([
                        ('job_id', '=', self.id),
                        ('stage_id', '=', stage.id),
                    ], limit=1)
                    if existing and not existing._has_payload():
                        existing.unlink()

    def action_preview_test_task_email(self):
        """Open the Test Task invitation mail.template form. Odoo's built-in
        Preview button on that form lets the recruiter pick an applicant and
        see the rendered email — including the substituted ``test_task_url``.
        """
        self.ensure_one()
        template = self.env.ref(
            'hr_recruitment_test_task.mail_template_test_task_invite',
            raise_if_not_found=False)
        if not template:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': 'Test Task Invitation Email',
            'res_model': 'mail.template',
            'res_id': template.id,
            'view_mode': 'form',
            'target': 'current',
        }
