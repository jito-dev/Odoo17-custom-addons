import re

from odoo import _, fields, models
from odoo.exceptions import UserError


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
    vacancy_line_ids = fields.One2many(
        comodel_name='djinni.set_ref.line',
        inverse_name='wizard_id',
        string='Available Vacancies',
    )
    vacancy_line_id = fields.Many2one(
        comodel_name='djinni.set_ref.line',
        string='Djinni Vacancy',
        domain="[('id', 'in', vacancy_line_ids)]",
        help='Pick the exact Djinni vacancy to connect to this Odoo job.',
    )
    vacancies_loaded = fields.Boolean(default=False)
    url = fields.Char(
        string='Vacancy URL',
        help='Optional fallback: paste the Djinni vacancy URL instead of '
             'loading the list. The numeric ID is extracted automatically.',
    )

    def action_load_vacancies(self):
        """Fetch the account's vacancies from Djinni into the picker."""
        self.ensure_one()
        self.vacancy_line_ids.unlink()
        Line = self.env['djinni.set_ref.line']
        for item in self.djinni_account_id.list_djinni_vacancies():
            Line.create({
                'wizard_id': self.id,
                'ref': str(item['id']),
                'name': item.get('position') or _('Djinni #%s', item['id']),
                'public_url': item.get('public_url'),
                'is_online': item.get('new_is_online', False),
            })
        self.vacancies_loaded = True
        # Re-open the same transient so the freshly created lines show up in the
        # picker (a transient One2many is only selectable once persisted).
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'djinni.set_ref',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _resolve_ref(self):
        self.ensure_one()
        if self.vacancy_line_id:
            return self.vacancy_line_id.ref
        if self.url:
            return ''.join(re.findall(r'\d+', self.url))
        raise UserError(_('Select a vacancy from the list or paste its URL.'))

    def action_set(self):
        self.ensure_one()
        self.job_id.write({
            'djinni_account_id': self.djinni_account_id.id,
            'djinni_ref': self._resolve_ref(),
        })

    def action_set_and_sync(self):
        self.ensure_one()
        self.action_set()
        # Pull ONLY the freshly linked vacancy's data — never all jobs.
        self.djinni_account_id.sync_job_list(jobs=self.job_id)
