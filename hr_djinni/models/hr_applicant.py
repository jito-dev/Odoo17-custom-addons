# Copyright © 2024 Garazd Creation (<https://garazd.biz>)
# @author: Yurii Razumovskyi (<support@garazd.biz>)
# @author: Iryna Razumovska (<support@garazd.biz>)
# License OPL-1 (https://www.odoo.com/documentation/15.0/legal/licenses.html).

from odoo import fields, models


class HrApplicant(models.Model):
    _inherit = "hr.applicant"

    djinni_ref = fields.Char(string='Djinni ID', readonly=True)
    djinni_date = fields.Datetime(readonly=True)
    djinni_candidate_url = fields.Char()
    djinni_candidate_cv_url = fields.Char()

    def action_open_on_djinni(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': self.djinni_candidate_url,
            'target': 'new',
        }
