from odoo import models, fields, api

class HrJob(models.Model):
    _inherit = 'hr.job'

    add_test_task = fields.Boolean("Add Trainee Test Task", help="If checked, Test Task stages and tabs will be enabled for this job.")

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
        """ Adds or removes this job from the specific Test Task stages """
        self.ensure_one()
        stage_xml_ids = [
            'hr_recruitment_test_task.stage_test_given',
            'hr_recruitment_test_task.stage_test_submitted',
            'hr_recruitment_test_task.stage_ai_analysis'
        ]
        
        stages = self.env['hr.recruitment.stage']
        for xml_id in stage_xml_ids:
            stage = self.env.ref(xml_id, raise_if_not_found=False)
            if stage:
                stages += stage
        
        if not stages:
            return

        if enable:
            stages.write({'job_ids': [(4, self.id)]})
        else:
            stages.write({'job_ids': [(3, self.id)]})