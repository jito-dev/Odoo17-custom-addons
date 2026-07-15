# -*- coding: utf-8 -*-

from odoo import fields, models


class JitoMgtRegroupingSourceLine(models.Model):
    _name = 'jito.mgt.regrouping.source.line'
    _inherit = 'jito.mgt.source.consume.mixin'
    _description = 'Regrouping Source (partial consume)'

    regrouping_id = fields.Many2one(
        'jito.mgt.regrouping', required=True, ondelete='cascade', index=True,
    )
