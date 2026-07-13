# -*- coding: utf-8 -*-

from odoo import fields, models


class JitoMgtRestatementSourceLine(models.Model):
    _name = 'jito.mgt.restatement.source.line'
    _inherit = 'jito.mgt.source.consume.mixin'
    _description = 'Restatement Source (partial consume)'

    restatement_id = fields.Many2one(
        'jito.mgt.restatement', required=True, ondelete='cascade', index=True,
    )
