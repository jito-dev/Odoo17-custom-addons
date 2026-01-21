from odoo import models, fields

class IqQuestion(models.Model):
    """
    Simplified version of survey.question.
    Now designed for reusability across multiple surveys.
    """
    _name = 'iq.question'
    _description = 'IQ Question'
    _order = 'sequence, id'

    # Changed from Many2one to Many2many to allow one question to be used in multiple Job Tests
    survey_ids = fields.Many2many('iq.survey', string='Surveys')
    
    sequence = fields.Integer('Sequence', default=10)
    title = fields.Char('Question Code', required=True)  # e.g., A-1, B-5
    image_filename = fields.Char('Image Filename', help="e.g. A-1.png")
    
    correct_answer = fields.Integer('Correct Option', help="1-6 or 1-8", required=True)
    num_options = fields.Integer('Number of Options', default=6)