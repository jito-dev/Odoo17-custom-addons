from odoo import models, fields


class Appointment(models.Model):
    _name = "gym.appointment"
    _description = 'Appointment'

    student_id = fields.Many2one('res.partner')