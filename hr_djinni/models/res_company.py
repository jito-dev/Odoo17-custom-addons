# Copyright © 2024 Garazd Creation (https://garazd.biz)
# @author: Yurii Razumovskyi (support@garazd.biz)
# @author: Iryna Razumovska (support@garazd.biz)
# License OPL-1 (https://www.odoo.com/documentation/17.0/legal/licenses.html).

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    djinni_deactivate_vacancy = fields.Boolean()
    djinni_delete_vacancy = fields.Boolean()
    djinni_upload_active_vacancy = fields.Boolean(default=True)
