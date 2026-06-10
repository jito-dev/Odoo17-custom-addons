# Copyright © 2024 Garazd Creation (https://garazd.biz)
# @author: Yurii Razumovskyi (support@garazd.biz)
# @author: Iryna Razumovska (support@garazd.biz)
# License OPL-1 (https://www.odoo.com/documentation/17.0/legal/licenses.html).

from odoo import fields, models


class DjinniBlank(models.AbstractModel):
    _name = "djinni.blank"
    _description = 'Djinni Mixin'

    name = fields.Char()
    ref = fields.Char(readonly=True)
