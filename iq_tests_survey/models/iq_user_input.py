from odoo import models, fields, api

class IqUserInput(models.Model):
    _name = 'iq.user_input'
    _description = 'IQ Test Session'
    _rec_name = 'name'
    _order = 'create_date desc'

    survey_id = fields.Many2one('iq.survey', string='Survey', required=True)
    create_date = fields.Datetime('Date', default=fields.Datetime.now)
    
    name = fields.Char('Participant Name', required=True, default="Guest")
    age = fields.Integer('Age', required=True)
    email = fields.Char('Email')
    
    applicant_id = fields.Many2one('hr.applicant', string="Applicant")

    raw_score = fields.Integer('Raw Score', readonly=True)
    iq_score = fields.Integer('Calculated IQ', readonly=True)
    iq_category = fields.Char('Category', compute='_compute_category', store=True)
    
    # Explicit label for UI
    test_duration = fields.Float('Duration (Minutes)', readonly=True)
    
    line_ids = fields.One2many('iq.user_input.line', 'user_input_id', string='Detailed Answers')

    SCORE_TO_IQ_MAP = [None] * 15 + [62, 65, 65, 66, 67, 69, 70, 71, 72, 73, 75,
	76, 77, 79, 80, 82, 83, 84, 86, 87, 88, 90, 91, 92, 94, 95, 96, 98, 99,
	100, 102, 104, 106, 108, 110, 112, 114, 116, 118, 120, 122, 124, 126, 128,
	130, 140]

    @api.depends('iq_score')
    def _compute_category(self):
        for rec in self:
            if not rec.iq_score: rec.iq_category = 'Undetermined'
            elif rec.iq_score >= 130: rec.iq_category = 'Very Superior'
            elif rec.iq_score >= 120: rec.iq_category = 'Superior'
            elif rec.iq_score >= 110: rec.iq_category = 'High Average'
            elif rec.iq_score >= 90: rec.iq_category = 'Average'
            elif rec.iq_score >= 80: rec.iq_category = 'Low Average'
            elif rec.iq_score >= 70: rec.iq_category = 'Borderline'
            else: rec.iq_category = 'Extremely Low'

    def calculate_score(self):
        self.ensure_one()
        correct_count = sum(line.is_correct for line in self.line_ids)
        
        final_iq = 0
        if 0 <= correct_count < len(self.SCORE_TO_IQ_MAP):
            iq_val = self.SCORE_TO_IQ_MAP[correct_count]
            final_iq = iq_val if iq_val is not None else 0
        else:
            final_iq = 135 

        self.write({
            'raw_score': correct_count,
            'iq_score': final_iq
        })
        
        if self.applicant_id:
            self.applicant_id.write({
                'iq_score': final_iq,
                'iq_category': self.iq_category,
                'iq_input_id': self.id
            })
            
            stage_completed = self.env['hr.recruitment.stage'].search(
                [('name', '=', 'IQ Test Completed')], limit=1)
            
            if stage_completed:
                self.applicant_id.stage_id = stage_completed.id
                
                self.applicant_id.message_post(
                    body=f"IQ Test Completed. Score: {final_iq} ({self.iq_category}). Duration: {round(self.test_duration, 1)}m",
                    subtype_id=self.env.ref('mail.mt_note').id
                )
            
        return final_iq

class IqUserInputLine(models.Model):
    _name = 'iq.user_input.line'
    _description = 'IQ User Answer'

    user_input_id = fields.Many2one('iq.user_input', required=True, ondelete='cascade')
    question_id = fields.Many2one('iq.question', required=True)
    selected_option = fields.Integer('Selected Option')
    is_correct = fields.Boolean('Is Correct', compute='_compute_is_correct', store=True)

    @api.depends('selected_option', 'question_id.correct_answer')
    def _compute_is_correct(self):
        for rec in self:
            rec.is_correct = (rec.selected_option == rec.question_id.correct_answer)