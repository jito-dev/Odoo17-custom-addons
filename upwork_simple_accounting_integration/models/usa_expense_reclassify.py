import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class UsaSettingsExpenseReclassify(models.Model):
    """One-shot remediation: move existing Upwork Service-Fee / Membership
    vendor-bill expenses off the generic expense account onto the dedicated
    mapped accounts (600500 / 600510).

    Background: vendor bills are built by the AI extraction pipeline, which
    defaults the expense line to the company's generic expense account. The
    forward fix (`usa.transaction._apply_mapped_expense_account`) corrects new
    bills; this action repairs the historical ones.
    """

    _inherit = 'usa.settings'

    def action_reclassify_upwork_expense_accounts(self):
        self.ensure_one()
        company = self.journal_id.company_id or self.env.company
        Tx = self.env['usa.transaction'].sudo()
        txs = Tx.search([
            ('vendor_bill_id', '!=', False),
            ('accounting_subtype', 'in', ('Service Fee', 'Membership Fee')),
        ])

        drafts_fixed = 0
        posted_bills = 0
        already_ok = 0
        totals = {}  # (target_account_id, source_account_id) -> amount

        for tx in txs:
            bill = tx.vendor_bill_id.sudo()
            if not bill or bill.usa_reclassified:
                continue
            if bill.company_id.id != company.id:
                continue  # mapped account is company-specific
            target = self._get_account_for_transaction(tx)
            if not target:
                continue

            wrong = bill.line_ids.filtered(
                lambda l: l.account_id.account_type == 'expense'
                and l.account_id.id != target.id
                and l.debit > 0
            )
            if not wrong:
                bill.usa_reclassified = True  # already on the right account
                already_ok += 1
                continue

            if bill.state == 'draft':
                inv_wrong = bill.invoice_line_ids.filtered(
                    lambda l: l.display_type not in ('line_section', 'line_note')
                    and l.account_id.account_type == 'expense'
                    and l.account_id.id != target.id
                )
                if inv_wrong:
                    inv_wrong.write({'account_id': target.id})
                    drafts_fixed += 1
            else:
                for wl in wrong:
                    key = (target.id, wl.account_id.id)
                    totals[key] = totals.get(key, 0.0) + wl.debit
                posted_bills += 1

            bill.usa_reclassified = True

        move = self.env['account.move']
        if totals:
            journal = self.env['account.journal'].search([
                ('type', '=', 'general'),
                ('company_id', '=', company.id),
            ], limit=1)
            if not journal:
                raise UserError(_(
                    'No miscellaneous (general) journal found for %s.'
                ) % company.display_name)

            line_ids = []
            for (target_id, source_id), amount in totals.items():
                amount = round(amount, 2)
                label = _('Upwork expense reclassification')
                line_ids.append((0, 0, {
                    'account_id': target_id, 'name': label,
                    'debit': amount, 'credit': 0.0,
                }))
                line_ids.append((0, 0, {
                    'account_id': source_id, 'name': label,
                    'debit': 0.0, 'credit': amount,
                }))

            move = self.env['account.move'].sudo().create({
                'move_type': 'entry',
                'journal_id': journal.id,
                'date': fields.Date.context_today(self),
                'ref': _('Upwork Service-Fee / Membership expense reclassification'),
                'line_ids': line_ids,
            })
            _logger.info(
                'Upwork reclassification: %d posted bill(s) → draft JE %s (%d line pair(s)).',
                posted_bills, move.id, len(totals),
            )

        msg = _(
            '%(d)d draft bill(s) re-pointed; %(p)d posted bill(s) reclassified; '
            '%(o)d already correct.',
            d=drafts_fixed, p=posted_bills, o=already_ok,
        )

        if move:
            # Open the draft reclassification entry for review & posting.
            return {
                'type': 'ir.actions.act_window',
                'name': _('Reclassification Journal Entry'),
                'res_model': 'account.move',
                'res_id': move.id,
                'view_mode': 'form',
                'views': [[False, 'form']],
                'target': 'current',
            }

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Upwork Expense Reclassification'),
                'message': msg,
                'type': 'success',
                'sticky': False,
            },
        }
