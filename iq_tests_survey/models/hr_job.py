from odoo import models, fields, api

class HrJob(models.Model):
    _inherit = 'hr.job'

    add_iq_test = fields.Boolean("Add Cognitive Assessment", help="If checked, a Cognitive Assessment will be generated.")
    iq_survey_id = fields.Many2one('iq.survey', string="Cognitive Assessment", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        jobs = super().create(vals_list)
        for job in jobs:
            if job.add_iq_test:
                job._create_iq_test_infrastructure()
        return jobs

    def write(self, vals):
        res = super().write(vals)
        if 'add_iq_test' in vals and vals['add_iq_test']:
            for job in self:
                if not job.iq_survey_id:
                    job._create_iq_test_infrastructure()
        return res

    def _create_iq_test_infrastructure(self):
        """ Generates Survey and Two Stages """
        self.ensure_one()
        all_questions = self.env['iq.question'].search([])
        if not all_questions:
            from ..hooks import create_questions
            create_questions(self.env)
            all_questions = self.env['iq.question'].search([])

        # Create Survey
        survey = self.env['iq.survey'].create({
            'title': f"{self.name} - Cognitive Assessment",
            'job_id': self.id,
            'access_mode': 'token',
            'question_ids': [(6, 0, all_questions.ids)],
            'email_template_id': self.env.ref('iq_tests_survey.mail_template_iq_invite', raise_if_not_found=False).id
        })
        self.iq_survey_id = survey

        # Requirement 4: Create Two Stages
        Stage = self.env['hr.recruitment.stage']
        
        # 1. Cognitive Assessment Assigned
        stage_assigned = Stage.search([('name', '=', 'Cognitive Assessment Assigned')], limit=1)
        if stage_assigned:
            stage_assigned.write({'job_ids': [(4, self.id)]})
            if stage_assigned.template_id != self.env.ref('iq_tests_survey.mail_template_iq_invite', raise_if_not_found=False).id:
                stage_assigned.write({'template_id': self.env.ref('iq_tests_survey.mail_template_iq_invite', raise_if_not_found=False).id})
        else:
            Stage.create({
                'name': 'Cognitive Assessment Assigned',
                'sequence': 2,
                'job_ids': [(4, self.id)],
                'fold': False,
                'template_id': self.env.ref('iq_tests_survey.mail_template_iq_invite', raise_if_not_found=False).id,
            })

        # 2. Cognitive Assessment Completed
        stage_completed = Stage.search([('name', '=', 'Cognitive Assessment Completed')], limit=1)
        if stage_completed:
            stage_completed.write({'job_ids': [(4, self.id)]})
        else:
            Stage.create({
                'name': 'Cognitive Assessment Completed',
                'sequence': 3,
                'job_ids': [(4, self.id)],
                'fold': False,
            })