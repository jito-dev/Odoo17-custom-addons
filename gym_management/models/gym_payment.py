from odoo import models, fields


class Payment(models.Model):
    _name = "gym.payment"
    _description = "Payment"

    student_id = fields.Many2one('res.partner')