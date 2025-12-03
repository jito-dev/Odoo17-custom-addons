# -*- coding: utf-8 -*-
from odoo import api, fields, models

class HrJobNoteWizard(models.TransientModel):
    _name = 'hr.job.note.wizard'
    _description = 'Job Context Note Wizard'

    job_id = fields.Many2one('hr.job', required=True)
    note_type = fields.Selection([
        ('english', 'English Expectations'),
        ('hiring', 'Why Hiring'),
        ('relocation', 'Relocation'),
        ('commitment', 'Commitment'),
        ('workplace', 'Workplace'),
        ('schedule', 'Schedule'),
        ('salary', 'Salary'),
    ], string="Note Category", required=True)
    
    note_label = fields.Char(readonly=True)
    
    # One2many interface for lines
    line_ids = fields.One2many('hr.job.note.wizard.line', 'wizard_id', string="Notes")

    @api.model
    def default_get(self, fields_list):
        """ Populate wizard lines from existing job lines. """
        res = super().default_get(fields_list)
        job_id = self.env.context.get('default_job_id')
        note_type = self.env.context.get('default_note_type')
        
        if job_id and note_type:
            job = self.env['hr.job'].browse(job_id)
            # Fetch existing lines from the job for this category
            existing_lines = job.job_note_ids.filtered(lambda l: l.note_type == note_type)
            
            # Populate wizard lines
            lines_data = []
            for line in existing_lines:
                lines_data.append((0, 0, {'content': line.content}))
            
            res['line_ids'] = lines_data
            
        return res

    def action_save_note(self):
        """ Save notes from wizard back to job, replacing old ones of the same category. """
        self.ensure_one()
        # 1. Delete old lines for this category
        old_lines = self.job_id.job_note_ids.filtered(lambda l: l.note_type == self.note_type)
        old_lines.unlink()
        
        # 2. Create new lines from wizard
        new_lines = []
        for w_line in self.line_ids:
            if w_line.content:
                new_lines.append({
                    'job_id': self.job_id.id,
                    'note_type': self.note_type,
                    'content': w_line.content
                })
        
        if new_lines:
            self.env['hr.job.note.line'].create(new_lines)
            
        return {'type': 'ir.actions.act_window_close'}


class HrJobNoteWizardLine(models.TransientModel):
    _name = 'hr.job.note.wizard.line'
    _description = 'Job Context Note Wizard Line'

    wizard_id = fields.Many2one('hr.job.note.wizard', required=True)
    content = fields.Char("Note Content", required=True)