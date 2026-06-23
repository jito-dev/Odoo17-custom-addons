# -*- coding: utf-8 -*-

import json

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.misc import formatLang


class JitoLedgerJournal(models.Model):
    """Management-ledger-owned journal (17.0.2.0.0).

    Replaces the previous ``account.journal`` + ``jito.ledger.journal.rel``
    pairing (HLD Decision #9 — schema-light). A real ML-owned model
    cleanly separates ML journals from stock LL journals, removes
    cross-domain leakage in Stock Accounting's journal list, and lets
    the ML constraint (`jito.ledger.move.journal_id` in a managed
    ledger) become structural via FK instead of an `@api.constrains`.

    Each row owns:
      * a name + short code (unique per company);
      * a hard FK to its parent ``ledger_id`` (NL or extension);
      * optional currency for single-currency journals;
      * optional default management account (pre-fills new line rows
        on moves posted through this journal);
      * an immutable ``source_account_journal_id`` breadcrumb set by
        the post-migrate when the row was promoted from a legacy
        ``jito.ledger.journal.rel`` entry — downstream migrations use
        it to translate old account.journal IDs to new ones.
    """

    _name = 'jito.ledger.journal'
    _description = 'Management-Ledger Journal'
    _order = 'sequence, code, id'
    _check_company_auto = True

    name = fields.Char(
        string='Name',
        required=True,
        tracking=True,
        help='e.g. "Customer Invoices", "DeFi: Aave Vault".',
    )
    code = fields.Char(
        string='Short Code',
        required=True,
        tracking=True,
        help='Short identifier — convention: CINV / CBILL / CDEFI-AAVE. '
             'Unique within a company.',
    )
    type = fields.Selection(
        selection=[
            ('sale', 'Sales'),
            ('purchase', 'Purchase'),
            ('cash', 'Cash'),
            ('bank', 'Bank'),
            ('general', 'Miscellaneous'),
        ],
        string='Type',
        required=True,
        default='general',
        tracking=True,
        help='Mirrors stock Odoo account.journal.type so management '
             'ledger journals carry the same categorisation '
             '(17.0.2.2.0). Used by the journal picker UX and future '
             'per-type validations (e.g. invoice moves should use '
             'type=sale). Defaults to Miscellaneous when creating a '
             'new journal from inside an NL ledger.',
    )
    ledger_id = fields.Many2one(
        comodel_name='jito.ledger',
        string='Ledger',
        required=True,
        ondelete='restrict',
        index=True,
        tracking=True,
        domain="[('kind', 'in', ['non_leading', 'extension'])]",
        help='Management ledger this journal belongs to. A journal is '
             'owned by exactly one ledger (no rel table needed).',
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        related='ledger_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        tracking=True,
        help='Optional. When set, every move posted through this '
             'journal must use this currency. Leave blank for '
             'multi-currency journals (e.g. a crypto treasury that '
             'receives both USDT and TRX).',
    )
    default_account_id = fields.Many2one(
        comodel_name='jito.ledger.account',
        string='Default Management Account',
        ondelete='restrict',
        tracking=True,
        help='Pre-fills the account_id of new lines on '
             'jito.ledger.move records posted through this journal.',
    )
    active = fields.Boolean(default=True, tracking=True)
    sequence = fields.Integer(default=10)

    # ---- Bank / Cash specific config (17.0.2.2.0 / 17.0.2.2.1) ---------
    # Bank-journal block of stock account.journal, but BOTH the bank
    # account and the suspense account select from the ML chart
    # (jito.ledger.account) — no stock-LL coupling. Visible on the
    # form only when type is bank or cash.

    bank_account_id = fields.Many2one(
        comodel_name='jito.ledger.account',
        string='Bank Account',
        ondelete='restrict',
        copy=False,
        domain="[('company_id', '=', company_id), "
               "('semantic_family', 'in', ['mgt', 'faap'])]",
        help='The ML account that holds this journal\'s balance — '
             'e.g. MGT.CRYPTO.USDT for a TRON treasury wallet, or '
             'FAAP.BANK.EUR for a fiat mirror. Same idea as stock '
             '`account.journal.default_account_id` for bank journals, '
             'but resolved against the management chart of accounts.',
    )
    suspense_account_id = fields.Many2one(
        comodel_name='jito.ledger.account',
        string='Suspense Account',
        ondelete='restrict',
        domain="[('company_id', '=', company_id), "
               "('semantic_family', 'in', ['clr', 'mgt', 'faap'])]",
        help='Where unmatched payments land until reconciliation '
             'classifies them. Mirrors stock '
             '`account.journal.suspense_account_id`. Typically a '
             'CLR.* clearing account. Visible only for Bank/Cash '
             'journals.',
    )

    source_account_journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='Source Stock Journal (legacy)',
        ondelete='set null',
        readonly=True,
        copy=False,
        help='Breadcrumb set by the 17.0.2.0.0 post-migrate when this '
             'row was promoted from a legacy '
             'jito.ledger.journal.rel entry. Downstream module '
             'migrations join on this column to translate old '
             'account.journal FKs to new jito.ledger.journal FKs. '
             'Never written by user.',
    )

    # ---- Dashboard (17.0.2.4.0) ----------------------------------------
    # Mirrors stock account.journal's kanban dashboard. Two persistent
    # fields drive per-user display config; one Text/JSON computed
    # field carries the live metrics consumed by the kanban template.
    show_on_dashboard = fields.Boolean(
        string='Show on Dashboard',
        default=True,
        help='Uncheck via the kanban card menu to hide this journal '
             'from the Management Ledger dashboard. The journal still '
             'exists in Configuration → Journals.',
    )
    color = fields.Integer(
        string='Color Index',
        default=0,
        help='Kanban card border color (0 = default).',
    )
    kanban_dashboard = fields.Text(
        compute='_compute_kanban_dashboard',
        help='JSON blob read by the kanban template — contains all '
             'card metrics (balance, counts, captions). Recomputed on '
             'every kanban load; do not store.',
    )

    _sql_constraints = [
        (
            'code_company_uniq',
            'UNIQUE(code, company_id)',
            'A management-ledger journal code must be unique within a company.',
        ),
    ]

    @api.constrains('default_account_id', 'ledger_id')
    def _check_default_account(self):
        for rec in self:
            if not rec.default_account_id:
                continue
            if rec.default_account_id.company_id != rec.ledger_id.company_id:
                raise ValidationError(_(
                    "Default account '%s' belongs to company '%s', but "
                    "ledger '%s' belongs to company '%s'.",
                    rec.default_account_id.code,
                    rec.default_account_id.company_id.display_name,
                    rec.ledger_id.display_name,
                    rec.ledger_id.company_id.display_name,
                ))
            if rec.default_account_id.semantic_family == 'grp':
                raise ValidationError(_(
                    "Default account '%s' is a GRP.* (grouping) account "
                    "and is non-posting; it cannot be used as a default "
                    "for journal '%s'.",
                    rec.default_account_id.code,
                    rec.display_name,
                ))

    @api.depends('name', 'code')
    def _compute_display_name(self):
        for rec in self:
            if rec.name and rec.code:
                rec.display_name = '%s (%s)' % (rec.name, rec.code)
            else:
                rec.display_name = rec.name or rec.code or ''

    # ==== Dashboard ======================================================

    @api.depends('type', 'bank_account_id', 'ledger_id')
    def _compute_kanban_dashboard(self):
        """One JSON blob per journal, ready for the kanban template.

        The template reads it via ``JSON.parse(record.kanban_dashboard.raw_value)``
        and renders type-specific bodies. All numerics are pre-formatted
        for display; raw values are also included for badge logic.
        """
        data_by_journal = self._get_journal_dashboard_data_batched()
        for rec in self:
            rec.kanban_dashboard = json.dumps(data_by_journal.get(rec.id, {}))

    def _get_journal_dashboard_data_batched(self):
        """Return ``{journal_id: dict}`` with per-card metrics.

        Pattern mirrors stock account.journal._get_journal_dashboard_data_batched
        (account_journal_dashboard.py:312) — split by ``type``, batched
        read_group per slice. Avoids per-card N+1.
        """
        result = {j.id: {'type': j.type} for j in self}
        by_type = {}
        for journal in self:
            by_type.setdefault(journal.type, self.env['jito.ledger.journal'])
            by_type[journal.type] |= journal

        bank_cash = by_type.get('bank', self.env['jito.ledger.journal']) | \
                    by_type.get('cash', self.env['jito.ledger.journal'])
        if bank_cash:
            bank_cash._fill_bank_cash_data(result)

        sale_purchase = by_type.get('sale', self.env['jito.ledger.journal']) | \
                        by_type.get('purchase', self.env['jito.ledger.journal'])
        if sale_purchase:
            sale_purchase._fill_sale_purchase_data(result)

        general = by_type.get('general', self.env['jito.ledger.journal'])
        if general:
            general._fill_general_data(result)
        return result

    def _display_currency(self):
        """Currency used for monetary display on the kanban card.

        Priority: journal.currency_id → bank_account_id.currency_id →
        company.currency_id. Never None for an installed company.
        """
        self.ensure_one()
        return (
            self.currency_id
            or self.bank_account_id.currency_id
            or self.company_id.currency_id
        )

    def _fill_bank_cash_data(self, result):
        """Per-journal: balance + unreconciled count on bank_account_id."""
        Line = self.env['jito.ledger.move.line'].sudo()
        journals_with_account = self.filtered('bank_account_id')
        account_ids = list({j.bank_account_id.id for j in journals_with_account})
        if not account_ids:
            for j in self:
                d = result.setdefault(j.id, {})
                d.update({
                    'title': '',
                    'balance_amount': 0.0,
                    'balance_formatted': '',
                    'number_to_reconcile': 0,
                })
            return
        # Balance: sum of amount_currency for posted lines on the bank account.
        balance_groups = Line._read_group(
            domain=[
                ('account_id', 'in', account_ids),
                ('move_state', '=', 'posted'),
            ],
            groupby=['account_id'],
            aggregates=['amount_currency:sum'],
        )
        balance_map = {acc.id: total for acc, total in balance_groups}
        # Unreconciled count.
        unrec_groups = Line._read_group(
            domain=[
                ('account_id', 'in', account_ids),
                ('move_state', '=', 'posted'),
                ('reconciled', '=', False),
            ],
            groupby=['account_id'],
            aggregates=['__count'],
        )
        unrec_map = {acc.id: count for acc, count in unrec_groups}
        for journal in self:
            bank_acc = journal.bank_account_id
            balance = balance_map.get(bank_acc.id, 0.0) if bank_acc else 0.0
            unrec = unrec_map.get(bank_acc.id, 0) if bank_acc else 0
            display_curr = journal._display_currency()
            d = result.setdefault(journal.id, {})
            d.update({
                'title': bank_acc.code if bank_acc else _('No bank account configured'),
                'balance_amount': balance,
                'balance_formatted': formatLang(
                    self.env, balance, currency_obj=display_curr,
                ) if display_curr else '%.2f' % balance,
                'number_to_reconcile': unrec,
                'currency_name': display_curr.name if display_curr else '',
                'bank_account_configured': bool(bank_acc),
            })

    def _fill_sale_purchase_data(self, result):
        """Per-journal: draft + unpaid invoice counts."""
        Move = self.env['jito.ledger.move'].sudo()
        if not self:
            return
        journal_ids = self.ids
        # Draft invoices on these journals.
        draft_groups = Move._read_group(
            domain=[
                ('journal_id', 'in', journal_ids),
                ('state', '=', 'draft'),
                ('move_type', 'in', ('out_invoice', 'out_refund',
                                     'in_invoice', 'in_refund')),
            ],
            groupby=['journal_id'],
            aggregates=['__count', 'amount_total:sum'],
        )
        draft_map = {j.id: (count, total) for j, count, total in draft_groups}
        # Unpaid posted invoices.
        unpaid_groups = Move._read_group(
            domain=[
                ('journal_id', 'in', journal_ids),
                ('state', '=', 'posted'),
                ('payment_state', 'in', ('not_paid', 'in_payment')),
                ('move_type', 'in', ('out_invoice', 'out_refund',
                                     'in_invoice', 'in_refund')),
            ],
            groupby=['journal_id'],
            aggregates=['__count', 'amount_total:sum'],
        )
        unpaid_map = {j.id: (count, total) for j, count, total in unpaid_groups}
        for journal in self:
            draft_count, draft_sum = draft_map.get(journal.id, (0, 0.0))
            unpaid_count, unpaid_sum = unpaid_map.get(journal.id, (0, 0.0))
            display_curr = journal._display_currency()
            d = result.setdefault(journal.id, {})
            d.update({
                'title': journal.name,
                'number_draft': draft_count,
                'sum_draft': formatLang(
                    self.env, draft_sum, currency_obj=display_curr,
                ) if display_curr else '%.2f' % draft_sum,
                'number_waiting': unpaid_count,
                'sum_waiting': formatLang(
                    self.env, unpaid_sum, currency_obj=display_curr,
                ) if display_curr else '%.2f' % unpaid_sum,
                'currency_name': display_curr.name if display_curr else '',
            })

    def _fill_general_data(self, result):
        """Per-journal: unposted (draft) move count."""
        Move = self.env['jito.ledger.move'].sudo()
        if not self:
            return
        draft_groups = Move._read_group(
            domain=[
                ('journal_id', 'in', self.ids),
                ('state', '=', 'draft'),
            ],
            groupby=['journal_id'],
            aggregates=['__count'],
        )
        draft_map = {j.id: count for j, count in draft_groups}
        for journal in self:
            d = result.setdefault(journal.id, {})
            d.update({
                'title': journal.name,
                'number_draft': draft_map.get(journal.id, 0),
            })

    # ---- Card actions ---------------------------------------------------

    def open_action(self):
        """Header click on a kanban card → list view of that journal's items.

        Routes by ``type`` to the most useful list:
          * sale / purchase → invoice / bill list filtered to this journal
          * bank / cash     → posted move-lines on the bank_account_id
          * general         → journal entries (jito.ledger.move) on this journal
        """
        self.ensure_one()
        if self.type == 'sale':
            xmlid = 'jito_ledger_nl.action_jito_ledger_customer_invoices'
        elif self.type == 'purchase':
            xmlid = 'jito_ledger_nl.action_jito_ledger_vendor_bills'
        elif self.type in ('bank', 'cash'):
            xmlid = 'jito_ledger_nl.action_jito_ledger_move_line'
        else:
            xmlid = 'jito_ledger_nl.action_jito_ledger_move'
        try:
            action = self.env['ir.actions.act_window']._for_xml_id(xmlid)
        except ValueError:
            return False
        ctx = dict(self.env.context, default_journal_id=self.id)
        # Prefer search_default_journal_id when the action's search view
        # exposes it; harmless otherwise.
        ctx['search_default_journal_id'] = self.id
        if self.type in ('bank', 'cash') and self.bank_account_id:
            ctx['search_default_account_id'] = self.bank_account_id.id
        action['context'] = ctx
        action['domain'] = [('journal_id', '=', self.id)] \
            if self.type not in ('bank', 'cash') else action.get('domain', [])
        if self.type in ('bank', 'cash') and self.bank_account_id:
            action['domain'] = [
                ('account_id', '=', self.bank_account_id.id),
                ('move_state', '=', 'posted'),
            ]
        return action

    def action_open_reconcile_wizard_for_journal(self):
        """Bank/cash card → "Reconcile X items" → open the two-pane
        OWL bank-rec widget (17.0.8.0.0). Filters the kanban view of
        jito.ledger.move.line to unreconciled posted lines on this
        journal's bank_account_id.

        The act_window references the action defined in
        ``jito_ledger_nl.action_jito_bank_rec_widget`` whose kanban
        view carries ``js_class='jito_bank_rec_widget_kanban'`` —
        that triggers the custom OWL controller that injects the
        right-pane form.
        """
        self.ensure_one()
        if not self.bank_account_id:
            from odoo.exceptions import UserError
            raise UserError(_(
                "Journal '%s' has no Bank Account configured. Set one "
                "in Configuration → Journals.",
                self.display_name,
            ))
        try:
            action = self.env['ir.actions.act_window']._for_xml_id(
                'jito_ledger_nl.action_jito_bank_rec_widget',
            )
        except ValueError:
            # jito_ledger_nl not yet upgraded to 17.0.8.0.0 — fall
            # back to the wizard (Phase B1 behaviour).
            Wizard = self.env['jito.ledger.reconcile.wizard']
            return Wizard.open_for_journal(self)
        action['name'] = _("Reconcile — %s", self.display_name)
        action['domain'] = [
            ('account_id', '=', self.bank_account_id.id),
            ('move_state', '=', 'posted'),
            ('company_id', '=', self.company_id.id),
        ]
        ctx = dict(self.env.context)
        ctx['search_default_unreconciled'] = 1
        ctx['default_journal_id'] = self.id
        action['context'] = ctx
        return action

    def action_create_new_move(self):
        """Card CTA: open the move form preloaded with this journal +
        the right move_type. Routes by journal.type:
          sale → Customer Invoice, purchase → Vendor Bill, others → generic entry.
        """
        self.ensure_one()
        type_to_action = {
            'sale': ('jito_ledger_nl.action_jito_ledger_customer_invoices', 'out_invoice'),
            'purchase': ('jito_ledger_nl.action_jito_ledger_vendor_bills', 'in_invoice'),
        }
        xmlid, move_type = type_to_action.get(
            self.type, ('jito_ledger_nl.action_jito_ledger_move', 'entry'),
        )
        try:
            action = self.env['ir.actions.act_window']._for_xml_id(xmlid)
        except ValueError:
            return False
        # Force the form view.
        action['views'] = [(v, m) for v, m in action.get('views', []) if m == 'form'] \
            or [(False, 'form')]
        action['view_mode'] = 'form'
        action['target'] = 'current'
        ctx = dict(self.env.context, default_journal_id=self.id)
        ctx['default_ledger_id'] = self.ledger_id.id
        ctx['default_move_type'] = move_type
        action['context'] = ctx
        return action

    def action_toggle_dashboard(self):
        """Kanban menu: toggle show_on_dashboard on this row."""
        for rec in self:
            rec.show_on_dashboard = not rec.show_on_dashboard
        return True
