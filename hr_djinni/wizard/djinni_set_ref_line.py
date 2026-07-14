# Copyright © 2024 Garazd Creation (https://garazd.biz)
# License OPL-1 (https://www.odoo.com/documentation/17.0/legal/licenses.html).

from odoo import fields, models


class DjinniSetRefLine(models.TransientModel):
    _name = "djinni.set_ref.line"
    _description = 'Djinni vacancy option for the link wizard'
    _order = 'is_online desc, name'

    wizard_id = fields.Many2one(
        comodel_name='djinni.set_ref',
        ondelete='cascade',
        required=True,
    )
    ref = fields.Char(string='Djinni ID', required=True)
    name = fields.Char(string='Vacancy', required=True)
    public_url = fields.Char()
    is_online = fields.Boolean(string='Online on Djinni')
