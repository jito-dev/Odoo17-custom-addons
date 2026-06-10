import re

from odoo import fields, models


class DjinniSetRef(models.TransientModel):
    _name = "djinni.set_ref"
    _description = 'Wizard to set the Djinni ID for Jobs'

    job_id = fields.Many2one(
        comodel_name='hr.job',
        string='Vacancy',
        required=True,
    )
    djinni_account_id = fields.Many2one(
        comodel_name='djinni.account',
        string='Account',
        required=True,
    )
    url = fields.Char(
        string='Vacancy URL',
        required=True,
    )

    def action_set(self):
        self.ensure_one()
        self.job_id.write({
            'djinni_account_id': self.djinni_account_id.id,
            'djinni_ref': ''.join(re.findall(r'\d+', self.url)),
        })

    def action_set_and_sync(self):
        self.ensure_one()
        self.action_set()
        # Sync all vacancies
        self.djinni_account_id.sync_job_list()
