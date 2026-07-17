# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class JitoLedgerMoveLine(models.Model):
    """Line under a jito.ledger.move.

    Per HLD Decision #8: stores **transaction currency only**
    (`currency_id` + signed `amount_currency`). There are no
    `debit/credit/balance` company-currency columns. Sign on
    amount_currency indicates side: positive = debit-side,
    negative = credit-side. Reports translate to company currency at
    render time using `res.currency._get_query_currency_table()`
    (Phase 5).

    Implements v1.x reconciliation per HLD Decision #11 (since
    jito_ledger_nl 17.0.7.0.0): `amount_residual_currency` and
    `reconciled` are now stored computed fields driven by partial
    reconcile rows on `jito.ledger.partial.reconcile`. The
    `matched_debit_ids` / `matched_credit_ids` O2Ms expose the
    partner side of every match.
    """

    _name = 'jito.ledger.move.line'
    _description = 'Management-Ledger Line'
    _inherit = ['jito.analytic.mixin']
    _order = 'move_id, id'
    _check_company_auto = True

    move_id = fields.Many2one(
        comodel_name='jito.ledger.move',
        string='Move',
        required=True,
        ondelete='cascade',
        index=True,
    )

    # Related/stored mirror of the parent move's ledger_id so that
    # ledger isolation (HLD §8.3) is structural — a line cannot drift
    # to a different ledger from its move's.
    ledger_id = fields.Many2one(
        comodel_name='jito.ledger',
        related='move_id.ledger_id',
        store=True,
        readonly=True,
        index=True,
    )
    company_id = fields.Many2one(
        related='move_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )
    move_state = fields.Selection(
        related='move_id.state',
        store=True,
        readonly=True,
    )
    entry_type = fields.Selection(
        related='move_id.entry_type',
        store=True,
        readonly=True,
    )
    # Stored-related convenience fields: let the standalone Journal Items
    # tree + search filter / group at the line level without joining on
    # every query.
    date = fields.Date(
        related='move_id.date',
        store=True,
        readonly=True,
        index=True,
    )
    journal_id = fields.Many2one(
        comodel_name='jito.ledger.journal',
        related='move_id.journal_id',
        store=True,
        readonly=True,
        index=True,
    )
    move_name = fields.Char(
        related='move_id.name',
        store=True,
        readonly=True,
    )
    move_ref = fields.Char(
        related='move_id.ref',
        store=True,
        readonly=True,
    )

    # Account from the management-layer chart (HLD Decision #13). NOT
    # stock account.account.
    account_id = fields.Many2one(
        comodel_name='jito.ledger.account',
        string='Account',
        required=True,
        ondelete='restrict',
        index=True,
        check_company=True,
        domain="[('company_id', '=', company_id), ('active', '=', True)]",
    )
    account_semantic_family = fields.Selection(
        related='account_id.semantic_family',
        store=True,
        readonly=True,
    )

    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Partner',
    )
    name = fields.Char(string='Label')

    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        required=True,
        ondelete='restrict',
        compute='_compute_currency_id',
        store=True,
        readonly=False,
        precompute=True,
    )
    amount_currency = fields.Monetary(
        string='Amount',
        required=True,
        currency_field='currency_id',
        help="Signed amount in the line's transaction currency. Positive "
             "means debit-side; negative means credit-side. Per-currency "
             "balancing on the parent move requires this column to net to "
             "zero per currency_id.",
    )

    # Editable accountant-friendly columns: split the signed
    # amount_currency into debit/credit. Both are in **transaction
    # currency** (HLD Decision #8 forbids storing a company-currency
    # snapshot — we are NOT storing company currency here, only
    # tx-currency split for UX).
    #
    # Pattern mirrors stock account.move.line.debit/credit
    # (account_move_line.py:103-118): stored compute fields with
    # separate inverse methods for each side. Each inverse zeros the
    # opposite side via the compute round-trip, so a user typing into
    # one column clears the other automatically.
    debit_amount_currency = fields.Monetary(
        string='Debit',
        compute='_compute_debit_credit_currency',
        inverse='_inverse_debit_amount_currency',
        store=True,
        readonly=False,
        precompute=True,
        currency_field='currency_id',
    )
    credit_amount_currency = fields.Monetary(
        string='Credit',
        compute='_compute_debit_credit_currency',
        inverse='_inverse_credit_amount_currency',
        store=True,
        readonly=False,
        precompute=True,
        currency_field='currency_id',
    )

    # ---- Company-currency snapshot (17.0.10.0.0 — ADR reverses HLD #8) ----
    #
    # HLD Decision #8 originally chose tx-currency-only storage with
    # report-time FX translation. That works for single-currency moves
    # but breaks for multi-currency moves (Restatement, Bridging,
    # Regrouping) where two currencies in one move were calibrated
    # against each other at a specific posting-time rate: at report
    # time the framework translates each currency independently via
    # res.currency.rate, so the CLR pair that was balanced at posting
    # drifts apart and shows a residual that's a pure rate-mismatch
    # artifact.
    #
    # 17.0.10.0.0 mirrors stock account.move.line:
    #   - amount_currency stays the tx-currency authority.
    #   - balance is its company-currency twin, frozen at line creation
    #     (precompute=True with explicit value support). Reports read
    #     balance / debit / credit directly — no more FX translation
    #     at report time for posted lines.
    #   - debit / credit are the +/- split of balance for UI parity
    #     with stock journal items.
    #
    # Programmatic creators (Restatement, Bridging, Regrouping) may
    # pass an explicit `balance` in create vals to override the
    # default market-rate computation — that's how calibrated
    # multi-currency moves balance cleanly in company currency.
    company_currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Company Currency',
        related='move_id.company_id.currency_id',
        store=True,
        readonly=True,
        precompute=True,
    )
    balance = fields.Monetary(
        string='Balance',
        compute='_compute_balance',
        store=True,
        readonly=False,
        precompute=True,
        currency_field='company_currency_id',
        tracking=True,
        help="Company-currency value, frozen at line creation. Equals "
             "``amount_currency`` translated via ``res.currency._convert`` "
             "at ``line.date``, unless the creator passed an explicit "
             "balance (used by Restatement / Bridging / Regrouping to "
             "calibrate multi-currency moves).",
    )
    debit = fields.Monetary(
        string='Debit (company)',
        compute='_compute_debit_credit',
        inverse='_inverse_debit',
        store=True,
        readonly=False,
        precompute=True,
        currency_field='company_currency_id',
    )
    credit = fields.Monetary(
        string='Credit (company)',
        compute='_compute_debit_credit',
        inverse='_inverse_credit',
        store=True,
        readonly=False,
        precompute=True,
        currency_field='company_currency_id',
    )

    # ---- Reconciliation (HLD Decision #11; v1.x active in 17.0.7.0.0) -----
    #
    # `matched_debit_ids` lists partials where THIS line is the credit
    # side — the partner debit is reached via
    # `matched_debit_ids.debit_line_id`. Symmetrically
    # `matched_credit_ids` lists partials where THIS line is the debit
    # side. Naming follows stock account.move.line for consistency.
    matched_debit_ids = fields.One2many(
        comodel_name='jito.ledger.partial.reconcile',
        inverse_name='credit_line_id',
        string='Matched Debits',
        readonly=True,
        help="Partial reconciliations where this (credit) line is "
             "matched against a debit line.",
    )
    matched_credit_ids = fields.One2many(
        comodel_name='jito.ledger.partial.reconcile',
        inverse_name='debit_line_id',
        string='Matched Credits',
        readonly=True,
        help="Partial reconciliations where this (debit) line is "
             "matched against a credit line.",
    )
    amount_residual_currency = fields.Monetary(
        string='Residual',
        currency_field='currency_id',
        compute='_compute_residual',
        store=True,
        readonly=True,
        help="Open amount on this line: amount_currency minus the sum "
             "of matched partial-reconcile amounts. Reaches zero "
             "(within currency precision) when the line is fully "
             "matched. For non-posted or non-reconcilable lines, "
             "equals amount_currency.",
    )
    reconciled = fields.Boolean(
        string='Reconciled',
        compute='_compute_residual',
        store=True,
        readonly=True,
        index=True,
        help="True when amount_residual_currency rounds to zero in "
             "the line's currency.",
    )
    # 17.0.8.6.0 — for a bank/wallet line settled via the bank-rec
    # widget's bridging path (Patch 3), the line itself stays open
    # (residual != 0) because the bridge nets the open AR/AP side, not
    # the wallet asset. `bank_rec_done` is the user-visible "this line
    # has been processed in bank-rec" flag — True for *either* direct
    # reconciliation OR at least one bridging move pointing here via
    # `bank_rec_source_line_id`. Drives the kanban green check + the
    # "Reconciled" column on the Journal Items list.
    bank_rec_done = fields.Boolean(
        string='Reconciled',
        compute='_compute_bank_rec_done',
        search='_search_bank_rec_done',
        readonly=True,
        help="True when this line has been processed in the bank "
             "reconciliation widget — either directly (residual is "
             "zero) or via an auto-spawned bridging journal entry "
             "that closed the related AR/AP side.",
    )

    # ---- Invoicing fields (17.0.2.0.0) ----------------------------------

    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Product',
        ondelete='restrict',
        help="Optional. Picking a product on an invoice-style line "
             "auto-fills the label, unit price, and a sensible default "
             "management account (MGT.400500 for customer-side, "
             "MGT.600500 for vendor-side).",
    )
    quantity = fields.Float(
        string='Quantity',
        default=1.0,
        digits=(16, 4),
    )
    price_unit = fields.Float(
        string='Unit Price',
        default=0.0,
        digits=(16, 4),
    )
    price_subtotal = fields.Monetary(
        string='Subtotal',
        compute='_compute_price_subtotal',
        store=True,
        currency_field='currency_id',
        help="Quantity × Unit Price, rounded to the line's currency "
             "precision. NL is no-tax (FR-15) so subtotal == total.",
    )
    move_type = fields.Selection(
        related='move_id.move_type',
        store=True,
        readonly=True,
        index=True,
    )

    # 17.0.3.1.0 — discriminator that separates user-edited product
    # lines from the auto-generated AR/AP balancing line. Drives the
    # split between the Customer Invoice form's "Invoice Lines" tab
    # (display_type != 'payment_term') and "Journal Items" tab (all).
    # Pattern mirrors stock account.move.line.display_type.
    display_type = fields.Selection(
        selection=[
            ('product', 'Product'),
            ('payment_term', 'Payment Term'),
        ],
        string='Line Type',
        index=True,
        copy=True,
    )

    @api.depends('quantity', 'price_unit', 'currency_id')
    def _compute_price_subtotal(self):
        for line in self:
            qty = line.quantity or 0.0
            price = line.price_unit or 0.0
            raw = qty * price
            line.price_subtotal = (
                line.currency_id.round(raw) if line.currency_id else raw
            )

    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Auto-fill name, price_unit and account from the product."""
        if not self.product_id:
            return
        product = self.product_id
        move_type = self.move_id.move_type
        if move_type in ('out_invoice', 'out_refund'):
            self.price_unit = product.lst_price
            if not self.account_id:
                self.account_id = self.move_id._get_default_income_account()
        elif move_type in ('in_invoice', 'in_refund'):
            self.price_unit = product.standard_price
            if not self.account_id:
                self.account_id = self.move_id._get_default_expense_account()
        if not self.name:
            self.name = product.display_name

    @api.onchange('quantity', 'price_unit', 'price_subtotal', 'move_type')
    def _onchange_invoice_amount(self):
        """For invoice-style lines, derive amount_currency from
        price_subtotal × side-sign-of-move-type.

        Sign convention:
          out_invoice → revenue is credit-side (negative amount_currency)
          out_refund  → reverses revenue (positive)
          in_invoice  → expense is debit-side (positive)
          in_refund   → reverses expense (negative)

        For move_type='entry' (raw journal entries) this onchange is a
        no-op — user types into amount_currency directly via the
        debit_amount_currency / credit_amount_currency UI.
        """
        if self.move_type not in ('out_invoice', 'out_refund', 'in_invoice', 'in_refund'):
            return
        sign_map = {
            'out_invoice': -1,
            'out_refund': 1,
            'in_invoice': 1,
            'in_refund': -1,
        }
        sign = sign_map[self.move_type]
        self.amount_currency = sign * (self.price_subtotal or 0.0)

    # ---- defaults --------------------------------------------------------

    @api.model
    def default_get(self, fields_list):
        """Pre-fill `account_id` from the parent move's journal's
        own ``default_account_id`` (17.0.6.0.0 — direct read on
        jito.ledger.journal; was via the retired rel model).

        The form view passes the move's journal_id via the
        ``jito_journal_id`` context key on the One2many widget.
        """
        res = super().default_get(fields_list)
        if 'account_id' not in fields_list or res.get('account_id'):
            return res
        journal_id = self.env.context.get('jito_journal_id')
        if not journal_id:
            return res
        journal = self.env['jito.ledger.journal'].browse(journal_id)
        if journal.default_account_id:
            res['account_id'] = journal.default_account_id.id
        return res

    # ---- computed --------------------------------------------------------

    @api.depends('move_id.currency_id')
    def _compute_currency_id(self):
        """Fallback fill: when a line is created without an explicit
        currency_id (and the form's `default_currency_id` context was
        also empty because the parent move had no currency yet),
        inherit from the parent move's currency.

        Guarded so an existing user-picked currency is preserved when
        the move's currency later changes — per HLD Decision #10 each
        line may use a different currency, balancing is per-currency.
        """
        for line in self:
            if not line.currency_id and line.move_id.currency_id:
                line.currency_id = line.move_id.currency_id

    @api.depends('amount_currency')
    def _compute_debit_credit_currency(self):
        for line in self:
            amt = line.amount_currency or 0.0
            line.debit_amount_currency = amt if amt > 0 else 0.0
            line.credit_amount_currency = -amt if amt < 0 else 0.0

    def _inverse_debit_amount_currency(self):
        """Called only when the user modifies debit_amount_currency.
        Writes the signed value back to amount_currency. The compute
        round-trip then zeros credit_amount_currency.
        """
        for line in self:
            if line.debit_amount_currency:
                line.amount_currency = line.debit_amount_currency
            else:
                # User cleared debit — amount_currency should reflect credit
                line.amount_currency = -line.credit_amount_currency

    def _inverse_credit_amount_currency(self):
        """Called only when the user modifies credit_amount_currency.
        Writes the signed value back to amount_currency. The compute
        round-trip then zeros debit_amount_currency.
        """
        for line in self:
            if line.credit_amount_currency:
                line.amount_currency = -line.credit_amount_currency
            else:
                line.amount_currency = line.debit_amount_currency

    # ---- Company-currency balance (17.0.10.0.0) -------------------------

    @api.depends('amount_currency', 'currency_id', 'date',
                 'company_currency_id')
    def _compute_balance(self):
        """Translate ``amount_currency`` to company currency at
        ``line.date`` using ``res.currency._convert``.

        If a creator passed an explicit ``balance`` in create vals,
        ``precompute=True`` stores that value directly and this
        compute is skipped for that record (standard Odoo precompute
        behavior). The depends list excludes ``balance`` itself so a
        manually-set value isn't immediately overwritten.

        Restatement / Bridging / Regrouping rely on this to pass
        calibrated company-currency values that make multi-currency
        moves balance cleanly.
        """
        for line in self:
            if not line.currency_id or not line.amount_currency:
                line.balance = 0.0
                continue
            company_currency = line.company_currency_id
            if not company_currency or line.currency_id == company_currency:
                line.balance = line.amount_currency
                continue
            line.balance = line.currency_id._convert(
                line.amount_currency, company_currency,
                line.company_id, line.date or fields.Date.context_today(line),
            )

    @api.depends('balance')
    def _compute_debit_credit(self):
        for line in self:
            bal = line.balance or 0.0
            line.debit = bal if bal > 0 else 0.0
            line.credit = -bal if bal < 0 else 0.0

    def _inverse_debit(self):
        """User edits ``debit`` → recompute ``balance`` (= debit - credit).
        ``_compute_debit_credit`` then zeros the opposite column.
        """
        for line in self:
            line.balance = (line.debit or 0.0) - (line.credit or 0.0)

    def _inverse_credit(self):
        """User edits ``credit`` → recompute ``balance``."""
        for line in self:
            line.balance = (line.debit or 0.0) - (line.credit or 0.0)

    # ---- reconciliation -------------------------------------------------

    @api.depends(
        'amount_currency', 'currency_id', 'move_state',
        'account_id.reconcile',
        'matched_debit_ids.amount', 'matched_credit_ids.amount',
    )
    def _compute_residual(self):
        """Compute open residual + reconciled flag from partial reconciles.

        Sign convention follows ``amount_currency``: debit-side lines
        have positive amount and positive residual (decreasing toward
        zero as matches accumulate); credit-side lines have negative
        amount and negative residual (increasing toward zero).

        Lines that are not posted, or whose account isn't reconcilable,
        skip the partial-reconcile math — residual = amount_currency,
        reconciled = False. This keeps drafts editable without
        triggering misleading "reconciled" flags.
        """
        for line in self:
            if line.move_state != 'posted' or not line.account_id.reconcile:
                line.amount_residual_currency = line.amount_currency
                line.reconciled = False
                continue
            if line.amount_currency > 0:
                matched = sum(line.matched_credit_ids.mapped('amount'))
                residual = line.amount_currency - matched
            elif line.amount_currency < 0:
                matched = sum(line.matched_debit_ids.mapped('amount'))
                # amount_currency is negative; adding the matched (positive)
                # amount moves it toward zero.
                residual = line.amount_currency + matched
            else:
                residual = 0.0
            line.amount_residual_currency = residual
            line.reconciled = bool(
                line.currency_id and line.currency_id.is_zero(residual)
            )

    def action_open_analytic_picker(self):
        """Open the analytic-distribution grid dialog for this line
        (17.0.9.0.4). Returns the `jito_open_analytic_dialog` client
        action; the OWL dialog edits the distribution as a per-plan grid
        and writes it back via ORM. Triggered by the pie-chart button in
        the Analytic Distribution column / form.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'jito_open_analytic_dialog',
            'params': {
                'res_model': 'jito.ledger.move.line',
                'res_id': self.id,
                'amount': self.amount_currency,
                'currency_id': self.currency_id.id,
            },
        }

    # Financial fields that are frozen at posting (17.0.10.0.0 ADR).
    # Edits to these on posted lines are rejected by write() below.
    # ``analytic_distribution`` is deliberately NOT in this set — it's
    # a management dimension that may be re-tagged after posting and
    # triggers analytic-line regeneration (see 17.0.9.0.1 below).
    _POSTED_PROTECTED_FIELDS = frozenset({
        'amount_currency', 'balance', 'debit', 'credit',
        'currency_id', 'account_id', 'partner_id',
        'debit_amount_currency', 'credit_amount_currency',
    })

    def write(self, vals):
        """Two responsibilities:

        1. **Posted-line immutability (17.0.10.0.0)** — reject writes
           to any field in ``_POSTED_PROTECTED_FIELDS`` for lines whose
           parent move is already posted. Catches the symmetric
           two-line attack that the company-currency balance
           constraint alone would miss (writing equal-and-opposite
           balance edits to two lines keeps the move sum at zero but
           silently changes account balances). Bypassed under sudo()
           so migrations and admin tooling can still backfill data.

        2. **Analytic sync (17.0.9.0.1)** — keep generated
           ``jito.ledger.analytic.line`` rows in step when
           ``analytic_distribution`` is re-tagged on a posted line
           (analytic distribution is a non-financial dimension and
           stays editable after posting).
        """
        protected = self._POSTED_PROTECTED_FIELDS & set(vals.keys())
        if protected and not self.env.su:
            posted = self.filtered(lambda l: l.move_state == 'posted')
            if posted:
                raise UserError(_(
                    "Cannot edit %s on posted line(s) — these fields "
                    "are frozen at posting per the 17.0.10.0.0 ADR. "
                    "Reverse the move and create a new one if the "
                    "values need to change.",
                    ', '.join(sorted(protected)),
                ))
        res = super().write(vals)
        if 'analytic_distribution' in vals:
            posted_moves = self.move_id.filtered(lambda m: m.state == 'posted')
            if posted_moves:
                posted_moves._create_analytic_lines()
        return res

    @api.model
    def get_bank_rec_account_summary(self, journal_id):
        """Return the bank-rec kanban header payload for a journal.

        Called from the OWL KanbanController setup. Returns
        `{'account_name', 'balance', 'balance_formatted',
        'currency_symbol', 'unreconciled_count', 'total_count'}` or
        an empty dict if the journal has no bank account.

        17.0.8.8.0 — drives the "balance of current account" pill on
        top of the bank-rec kanban.
        """
        from odoo.tools.misc import formatLang
        Journal = self.env['jito.ledger.journal'].sudo()
        journal = Journal.browse(int(journal_id)).exists()
        account = journal.bank_account_id if journal else False
        if not account:
            return {}
        lines = self.sudo().search([
            ('account_id', '=', account.id),
            ('move_state', '=', 'posted'),
            ('company_id', '=', journal.company_id.id),
        ])
        balance = sum(lines.mapped('amount_currency'))
        unreconciled = lines.filtered(lambda l: not l.bank_rec_done)
        currency = (
            journal.currency_id
            or account.currency_id
            or journal.company_id.currency_id
        )
        return {
            'account_name': account.display_name,
            'balance': balance,
            'balance_formatted': formatLang(
                self.env, balance, currency_obj=currency,
            ),
            'currency_symbol': currency.symbol or currency.name or '',
            'unreconciled_count': len(unreconciled),
            'total_count': len(lines),
        }

    @api.depends('reconciled')
    def _compute_bank_rec_done(self):
        Move = self.env['jito.ledger.move'].sudo()
        bridged_source_ids = set(
            Move.search([
                ('bank_rec_source_line_id', 'in', self.ids),
            ]).mapped('bank_rec_source_line_id').ids
        )
        for line in self:
            line.bank_rec_done = (
                line.reconciled or line.id in bridged_source_ids
            )

    def _search_bank_rec_done(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            return [('id', '=', False)]
        Move = self.env['jito.ledger.move'].sudo()
        bridged_ids = Move.search([
            ('bank_rec_source_line_id', '!=', False),
        ]).mapped('bank_rec_source_line_id').ids
        positive_domain = ['|',
                           ('reconciled', '=', True),
                           ('id', 'in', bridged_ids)]
        wants_true = (operator == '=' and value) or (operator == '!=' and not value)
        if wants_true:
            return positive_domain
        return ['&',
                ('reconciled', '=', False),
                ('id', 'not in', bridged_ids)]

    def _update_reconcile_state(self):
        """Re-trigger residual + reconciled compute on these lines.

        Called from jito.ledger.partial.reconcile create / write /
        unlink hooks. The @api.depends already covers the round-trip
        in normal flow, but this explicit invalidate guards against
        edge cases where the dependency graph misses an update (mass
        creates, raw SQL, etc.).
        """
        if not self:
            return True
        self.invalidate_recordset(['amount_residual_currency', 'reconciled'])
        self._compute_residual()
        # Cascade to the parent move so its `payment_state` recomputes.
        self.mapped('move_id').invalidate_recordset(['payment_state'])
        return True

    def _reconcile(self):
        """Greedily match selected lines into jito.ledger.partial.reconcile
        records.

        Algorithm:
          1. Validate same currency + reconcilable + posted across the
             whole selection. Cross-account matching is supported as of
             17.0.8.3.0 (mirrors stock account.partial.reconcile).
          2. Partition into debits (residual > 0) and credits
             (residual < 0), sorted by date (oldest first).
          3. Iterate two pointers; each step creates one partial
             reconcile for ``min(debit_residual, |credit_residual|)``
             and advances whichever side fully closed.

        Returns the created partial-reconcile recordset (may be empty
        if the selection had no debit/credit pair to match).
        """
        if not self:
            return self.env['jito.ledger.partial.reconcile']
        accounts = self.mapped('account_id')
        currencies = self.mapped('currency_id')
        if len(currencies) != 1:
            raise UserError(_(
                "All selected lines must be in the same currency "
                "(found: %s).",
                ', '.join(sorted(currencies.mapped('name'))),
            ))
        bad_accounts = [a for a in accounts if not a.reconcile]
        if bad_accounts:
            raise UserError(_(
                "These accounts are not marked reconcilable: %s. "
                "Enable 'Allow Reconciliation' on each first.",
                ', '.join(sorted(a.code for a in bad_accounts)),
            ))
        not_posted = self.filtered(lambda l: l.move_state != 'posted')
        if not_posted:
            raise UserError(_(
                "All selected lines must be on posted moves; "
                "%d of %d are not.",
                len(not_posted), len(self),
            ))
        # Refresh in case caller passed stale records.
        self._compute_residual()
        debits = self.filtered(
            lambda l: l.amount_residual_currency > 0
        ).sorted('date')
        credits = self.filtered(
            lambda l: l.amount_residual_currency < 0
        ).sorted('date')
        if not debits or not credits:
            raise UserError(_(
                "Need at least one debit and one credit line with a "
                "non-zero residual to reconcile (got %d debit / %d "
                "credit lines with open balance).",
                len(debits), len(credits),
            ))
        currency = currencies
        Partial = self.env['jito.ledger.partial.reconcile']
        debit_list = list(debits)
        credit_list = list(credits)
        debit_residuals = [d.amount_residual_currency for d in debit_list]
        credit_residuals = [-c.amount_residual_currency for c in credit_list]
        created = Partial
        di = ci = 0
        while di < len(debit_list) and ci < len(credit_list):
            d_res = debit_residuals[di]
            c_res = credit_residuals[ci]
            if currency.is_zero(d_res):
                di += 1
                continue
            if currency.is_zero(c_res):
                ci += 1
                continue
            match_amt = min(d_res, c_res)
            created |= Partial.create({
                'debit_line_id': debit_list[di].id,
                'credit_line_id': credit_list[ci].id,
                'amount': match_amt,
            })
            debit_residuals[di] -= match_amt
            credit_residuals[ci] -= match_amt
        return created

    def remove_reconcile(self):
        """Unlink every partial reconcile touching these lines. Useful
        to reopen a fully-paid invoice.
        """
        Partial = self.env['jito.ledger.partial.reconcile']
        partials = Partial.search([
            '|',
            ('debit_line_id', 'in', self.ids),
            ('credit_line_id', 'in', self.ids),
        ])
        partials.unlink()
        return True

    def action_open_reconcile_wizard(self):
        """Server-action callback: open the reconcile wizard preloaded
        with the selected lines.
        """
        if not self:
            raise UserError(_("Select at least two lines to reconcile."))
        return {
            'name': _('Reconcile ML Lines'),
            'type': 'ir.actions.act_window',
            'res_model': 'jito.ledger.reconcile.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_line_ids': [(6, 0, self.ids)],
            },
        }

    # ---- constraints -----------------------------------------------------

    # NOTE (17.0.13.2.0): the former ``_check_account_semantic_rules`` guard
    # that restricted clearing accounts (``is_clearing``) to Management
    # Bridging / Restatement entries was removed. A clearing / suspense
    # account is legitimately posted to by every controlled flow that uses
    # a transit balance — bank-reconciliation auto-balance (nl_doc), crypto
    # injection (ext_adjustment), regrouping targets (mgt_regroup) — not just
    # the adjustment wizards. The entry-type whitelist was therefore a
    # false-positive that blocked those flows, so it no longer exists. The
    # ``is_clearing`` flag still drives the journal suspense pointer, the
    # bank-rec auto-balance target, the adjustment clearing pickers and the
    # reconcile default.

    @api.constrains('account_id', 'company_id')
    def _check_account_company(self):
        for line in self:
            if line.account_id.company_id != line.company_id:
                raise ValidationError(_(
                    "Account '%s' belongs to company '%s'; line is in '%s'.",
                    line.account_id.code,
                    line.account_id.company_id.display_name,
                    line.company_id.display_name,
                ))

    @api.constrains('amount_currency', 'move_state')
    def _check_nonzero_amount(self):
        """Reject zero-amount lines on posted moves only.

        Drafts may transiently hold zero-amount lines while the user is
        still editing (e.g., line just added, debit/credit not yet
        typed). The move-level balance check + this constraint together
        catch unfinished work at post time.
        """
        for line in self:
            if line.move_state == 'draft':
                continue
            if line.currency_id and line.currency_id.is_zero(line.amount_currency):
                raise ValidationError(_(
                    "Line on account '%s' has zero amount_currency; posted "
                    "lines must move a non-zero value.",
                    line.account_id.code if line.account_id else '?',
                ))
