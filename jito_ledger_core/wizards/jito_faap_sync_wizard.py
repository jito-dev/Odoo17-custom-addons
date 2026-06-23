# -*- coding: utf-8 -*-

import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class JitoFaapSyncWizard(models.TransientModel):
    """Sync FAAP.* mirrors in `jito.ledger.account` from stock
    `account.account`.

    Per HLD §4.4 and Decision #13, FAAP.* accounts are management-layer
    mirrors of statutory accounts. The schema supports this via
    `jito.ledger.account.statutory_account_id` (soft FK to `account.account`).
    This wizard provides bulk creation/maintenance:

      1. Walk `account.account` rows in the chosen company.
      2. For each, ensure a `jito.ledger.account` row exists with:
           code = "FAAP.<stock_code>"
           name = stock account name
           account_type = stock account_type (same selection list)
           statutory_account_id = stock account.id
           currency_id = stock currency_id (if any)
      3. Skip-or-update existing mirrors per the `update_existing` toggle.

    Per PRD §Security Matrix, "configure ledgers, FX feeds, semantic
    accounts" is admin-only — the ACL below restricts this wizard to
    `group_mgmt_ledger_admin`.
    """

    _name = 'jito.ledger.faap.sync.wizard'
    _description = 'Sync FAAP Mirrors from Stock Chart of Accounts'

    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    update_existing = fields.Boolean(
        string='Update existing FAAP mirrors',
        default=False,
        help="When set, an existing FAAP.* row whose code matches a stock "
             "account is refreshed (name, account_type, currency, "
             "statutory_account_id). Otherwise it is left untouched.",
    )
    skip_deprecated = fields.Boolean(
        string='Skip deprecated statutory accounts',
        default=True,
        help="Stock accounts marked deprecated are skipped. Recommended.",
    )
    skip_off_balance = fields.Boolean(
        string='Skip off-balance statutory accounts',
        default=False,
        help="Off-balance statutory accounts often have no meaningful "
             "management-layer mirror. Tick to skip them.",
    )
    skip_equity_unaffected = fields.Boolean(
        string='Skip current-year-earnings account',
        default=True,
        help="Stock Odoo's `equity_unaffected` (Current Year Earnings) "
             "is system-managed in statutory accounting; mirroring it "
             "rarely adds value. Recommended to skip.",
    )

    def action_sync(self):
        """Run the bulk sync. Returns a notification with the result."""
        self.ensure_one()
        Account = self.env['jito.ledger.account']
        StockAccount = self.env['account.account']

        domain = [('company_id', '=', self.company_id.id)]
        if self.skip_deprecated:
            domain.append(('deprecated', '=', False))
        if self.skip_off_balance:
            domain.append(('account_type', '!=', 'off_balance'))
        if self.skip_equity_unaffected:
            domain.append(('account_type', '!=', 'equity_unaffected'))

        stock_accounts = StockAccount.search(domain)

        created = 0
        updated = 0
        skipped_existing = 0
        skipped_invalid_code = 0

        for stock in stock_accounts:
            faap_code = self._make_faap_code(stock.code)
            if not faap_code:
                skipped_invalid_code += 1
                _logger.warning(
                    "FAAP sync: stock account %s (code=%r) cannot be "
                    "mirrored — code is empty after sanitisation. Skipped.",
                    stock.display_name, stock.code,
                )
                continue

            existing = Account.search([
                ('code', '=', faap_code),
                ('company_id', '=', self.company_id.id),
            ], limit=1)

            vals = {
                'code': faap_code,
                'name': stock.name,
                'account_type': stock.account_type,
                'company_id': self.company_id.id,
                'currency_id': stock.currency_id.id if stock.currency_id else False,
                'statutory_account_id': stock.id,
            }

            if existing:
                if self.update_existing:
                    existing.write({
                        'name': vals['name'],
                        'account_type': vals['account_type'],
                        'currency_id': vals['currency_id'],
                        'statutory_account_id': vals['statutory_account_id'],
                    })
                    updated += 1
                else:
                    skipped_existing += 1
            else:
                Account.create(vals)
                created += 1

        message_parts = [
            _("Considered %d stock account(s) in '%s'.",
              len(stock_accounts), self.company_id.display_name),
            _("Created: %d") % created,
        ]
        if updated:
            message_parts.append(_("Updated: %d") % updated)
        if skipped_existing:
            message_parts.append(_("Skipped (already exists): %d") % skipped_existing)
        if skipped_invalid_code:
            message_parts.append(_("Skipped (invalid code): %d") % skipped_invalid_code)

        message = "\n".join(message_parts)
        _logger.info("FAAP sync complete: %s", message.replace("\n", " | "))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('FAAP Sync'),
                'message': message,
                'type': 'success',
                'sticky': True,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    @staticmethod
    def _make_faap_code(stock_code):
        """Produce a valid FAAP.* code from a stock account code.

        The semantic-prefix constraint on jito.ledger.account requires
        non-empty body and no whitespace. This sanitiser strips outer
        whitespace and replaces inner whitespace with underscores.
        """
        if not stock_code:
            return ''
        sanitised = '_'.join(stock_code.split())
        if not sanitised:
            return ''
        return f'FAAP.{sanitised}'
