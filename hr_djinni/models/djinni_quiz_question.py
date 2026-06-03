# Copyright © 2024 Garazd Creation (https://garazd.biz)
# @author: Yurii Razumovskyi (support@garazd.biz)
# @author: Iryna Razumovska (support@garazd.biz)
# License OPL-1 (https://www.odoo.com/documentation/17.0/legal/licenses.html).

from odoo import fields, models


class DjinniQuestion(models.Model):
    _name = "djinni.quiz.question"
    _description = 'Djinni Questions'
    _order = 'sequence'

    name = fields.Char(required=True, size=256)
    ref = fields.Char(readonly=True)
    type_id = fields.Many2one(comodel_name='djinni.quiz.question.type')
    expected_answer = fields.Char(size=32)
    sequence = fields.Integer(default=0)
    quiz_id = fields.Many2one(comodel_name='djinni.quiz')

    def prepare_json(self):
        self.ensure_one()
        return {
            'visual_order': self.sequence,
            'text': self.name,
            'answer_type': self.type_id.ref,
            'expected_answer': self.expected_answer or '',
        }
