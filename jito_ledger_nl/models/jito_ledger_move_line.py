# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class JitoLedgerMoveLine(models.Model):
    """Line under a jito.ledger.move.

    Per HLD Decision #8: stores **transaction currency only**
    (`currency_id` + signed `amount_currency`). There are no
    `debit/credit/balance` company-currency columns. Sign on
    amount_currency indicates side: positive = debit-side,
    negative = credit-side. Reports translate to company currency at
    render time using `res.currency._get_query_currency_table()`
    (Phase 5).

    Reserves `amount_residual_currency` and `reconciled` per HLD
    Decision #11 — the schema is in place so the v1.x reconciliation
    feature can ship as 'add behaviour, not alter table'.
    """

    _name = 'jito.ledger.move.line'
    _description = 'Management-Ledger Line'
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
        comodel_name='account.journal',
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

    # Reserved for v1.x reconciliation (HLD Decision #11). Not populated
    # by any code in v1; reconciliation logic + wizard ship later.
    amount_residual_currency = fields.Monetary(
        string='Residual (Currency)',
        currency_field='currency_id',
        help="Reserved for v1.x reconciliation. Not used in v1.",
        readonly=True,
    )
    reconciled = fields.Boolean(
        string='Reconciled',
        help="Reserved for v1.x reconciliation. Not used in v1.",
        readonly=True,
        index=True,
    )

    # ---- Invoicing fields (17.0.2.0.0) ----------------------------------

    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Product',
        ondelete='restrict',
        help="Optional. Picking a product on an invoice-style line "
             "auto-fills the label, unit price, and a sensible default "
             "management account (MGT.SALES for customer-side, "
             "MGT.EXPENSE for vendor-side).",
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
        jito.ledger.journal.rel.default_account_id when creating a new
        line via the move form.

        The form view passes the move's journal_id via the
        ``jito_journal_id`` context key on the One2many widget. We read
        it here and look up the rel.
        """
        res = super().default_get(fields_list)
        if 'account_id' not in fields_list or res.get('account_id'):
            return res
        journal_id = self.env.context.get('jito_journal_id')
        if not journal_id:
            return res
        rel = self.env['jito.ledger.journal.rel'].search([
            ('journal_id', '=', journal_id),
        ], limit=1)
        if rel.default_account_id:
            res['account_id'] = rel.default_account_id.id
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

    # ---- constraints -----------------------------------------------------

    @api.constrains('account_id', 'move_id')
    def _check_account_semantic_rules(self):
        """Per HLD §4.4:

        - GRP.* accounts are non-posting; reject any line targeting one.
        - CLR.* accounts are transit-only; allowed only on entries with
          entry_type='mgt_bridge' (Phase 4 territory). The constraint is
          enforced now so the schema is consistent when Phase 4 lands.

        FAAP.* and MGT.* accept all entry_types.
        """
        for line in self:
            family = line.account_id.semantic_family
            entry_type = line.move_id.entry_type
            if family == 'grp':
                raise ValidationError(_(
                    "Account '%s' is a GRP.* (grouping) account and is "
                    "non-posting. Pick a FAAP.*, MGT.*, or CLR.* account.",
                    line.account_id.code,
                ))
            if family == 'clr' and entry_type not in ('mgt_bridge', 'mgt_restate'):
                raise ValidationError(_(
                    "Account '%s' is a CLR.* (clearing) account and is only "
                    "allowed on Management Bridging or Management Restatement "
                    "entries (entry_type in ('mgt_bridge', 'mgt_restate')). "
                    "This entry is type '%s'.",
                    line.account_id.code, entry_type,
                ))

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
