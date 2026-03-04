import logging

from odoo import models

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    def unlink(self):
        # Find linked salary runs BEFORE deletion (invoice_id still set)
        SalaryRun = self.env['hr.payroll.contractor.salary.run']
        linked_runs = SalaryRun.sudo().search([('invoice_id', 'in', self.ids)])

        result = super().unlink()
        # Odoo ORM auto-nulls invoice_id via SET NULL (bypasses write())
        # Revert state back to approved_and_locked
        if linked_runs:
            try:
                linked_runs.sudo().write({'state': 'approved_and_locked'})
            except Exception as e:
                _logger.error('Failed to revert salary run state after bill deletion: %s', e)
        return result
