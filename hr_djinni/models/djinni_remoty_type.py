# Copyright © 2024 Garazd Creation (https://garazd.biz)
# @author: Yurii Razumovskyi (support@garazd.biz)
# @author: Iryna Razumovska (support@garazd.biz)
# License OPL-1 (https://www.odoo.com/documentation/17.0/legal/licenses.html).

from odoo import models


class DjinniRemoteType(models.Model):
    _name = "djinni.remote.type"
    _inherit = ['djinni.blank']
    _description = 'Djinni Remote Types'
