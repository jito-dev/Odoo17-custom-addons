# Copyright © 2024 Garazd Creation (https://garazd.biz)
# @author: Yurii Razumovskyi (support@garazd.biz)
# @author: Iryna Razumovska (support@garazd.biz)
# License OPL-1 (https://www.odoo.com/documentation/17.0/legal/licenses.html).

from odoo import models


class DjinniEngLevelDeviation(models.Model):
    _name = "djinni.eng.level.deviation"
    _inherit = ['djinni.blank']
    _description = 'Djinni Acceptable English Level Deviations'
