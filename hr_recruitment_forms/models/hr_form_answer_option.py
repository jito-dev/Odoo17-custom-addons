# -*- coding: utf-8 -*-

from odoo import fields, models


class HrFormAnswerOption(models.Model):
    _name = 'hr.form.answer.option'
    _description = 'HR Form Answer Option'
    _order = 'sequence, id'

    question_id = fields.Many2one(
        comodel_name='hr.form.question',
        string='Question',
        required=True,
        ondelete='cascade',
        index=True,
    )
    value = fields.Char(
        string='Option Value',
        required=True,
        translate=True,
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
    )

    def name_get(self):
        """Display option value as name."""
        return [(option.id, option.value) for option in self]
