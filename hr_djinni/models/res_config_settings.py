# Copyright © 2024 Garazd Creation (https://garazd.biz)
# @author: Yurii Razumovskyi (support@garazd.biz)
# @author: Iryna Razumovska (support@garazd.biz)
# License OPL-1 (https://www.odoo.com/documentation/17.0/legal/licenses.html).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    djinni_deactivate_vacancy = fields.Boolean(
        string='Deactivate Vacancy on Djinni',
        help='If you want to deactivate the vacancy on Djinni when archiving the vacancy in Odoo, '
             'set this parameter.',
        related='company_id.djinni_deactivate_vacancy',
        readonly=False,
    )
    djinni_delete_vacancy = fields.Boolean(
        string='Delete Vacancy on Djinni',
        help='If you want to delete the vacancy on Djinni when deleting the vacancy in Odoo, '
             'set this parameter.',
        related='company_id.djinni_delete_vacancy',
        readonly=False,
    )
    djinni_upload_active_vacancy = fields.Boolean(
        string='Upload only active vacancies from Djinni',
        related='company_id.djinni_upload_active_vacancy',
        readonly=False,
    )
