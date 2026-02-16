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
        """ 
        Adds or removes this job from the specific Test Task stages.
        Creates stages dynamically if they don't exist to prevent them from being global.
        """
        self.ensure_one()
        
        # Configuration for the required stages
        stages_config = [
            {
                'name': 'Test Task Given',
                'sequence': 10,
                'template_xml_id': 'hr_recruitment_test_task.mail_template_test_task_invite',
                'fold': False
            },
            {
                'name': 'Test Task Submitted',
                'sequence': 11,
                'template_xml_id': False, # No automated email on submission receipt
                'fold': False
            },
            {
                'name': 'Test Task ChatGPT Analyzed',
                'sequence': 12,
                'template_xml_id': False,
                'fold': True
            }
        ]
        
        Stage = self.env['hr.recruitment.stage']
        
        for config in stages_config:
            # 1. Search for the stage by exact name
            stage = Stage.search([('name', '=', config['name'])], limit=1)
            
            if enable:
                if stage:
                    # If stage exists, add this job to it if not already added
                    if self.id not in stage.job_ids.ids:
                        stage.write({'job_ids': [(4, self.id)]})
                else:
                    # Create new stage specific to this job
                    # CRITICAL: Setting job_ids=[(4, self.id)] ensures it is NOT created as a global stage
                    vals = {
                        'name': config['name'],
                        'sequence': config['sequence'],
                        'job_ids': [(4, self.id)],
                        'fold': config['fold'],
                    }
                    
                    # Resolve Email Template ID if configured
                    if config['template_xml_id']:
                        template = self.env.ref(config['template_xml_id'], raise_if_not_found=False)
                        if template:
                            vals['template_id'] = template.id
                    
                    Stage.create(vals)
            else:
                # If disabling, remove this specific job from the stage
                if stage:
                    stage.write({'job_ids': [(3, self.id)]})