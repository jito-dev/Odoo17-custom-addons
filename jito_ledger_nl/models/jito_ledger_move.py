# -*- coding: utf-8 -*-

from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import format_date


class JitoLedgerMove(models.Model):
    """Parallel-ledger journal entry.

    The single shared table hosting NL documents, extension adjustments,
    and the four management-adjustment outputs (HLD §4.3 + Decision #4).
    `entry_type` discriminates them; downstream phases create rows here
    with their own discriminator value.

    Per FR-02 / FR-13, this table holds **no FK** into stock Odoo's
    `account.move*`. Posting an NL document never writes a row in
    `account_move` — that physical isolation is the strongest-form
    enforcement of Leading-Ledger immutability.
    """

    _name = 'jito.ledger.move'
    _description = 'Management-Ledger Journal Entry'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Number',
        required=True,
        copy=False,
        default=lambda self: _('New'),
        tracking=True,
        index=True,
    )
    ref = fields.Char(string='Reference', tracking=True)

    # Ledger is the primary selection. Domain restricts to non-leading and
    # extension; the auto-seeded Leading Ledger is hidden because LL postings
    # go through stock account.move, not this table.
    ledger_id = fields.Many2one(
        comodel_name='jito.ledger',
        string='Ledger',
        ondelete='restrict',
        tracking=True,
        index=True,
        domain="[('kind', 'in', ['non_leading', 'extension'])]",
        help="Pick the Non-Leading or Extension ledger this entry belongs to. "
             "The Journal field below will be filtered to journals associated "
             "with the chosen ledger (configured in Management Ledger → "
             "Ledgers → <ledger> → Journals tab).",
    )

    # Operational journal. Domain is dynamic via allowed_journal_ids
    # (computed from ledger_id); the form's domain references it.
    journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='Journal',
        ondelete='restrict',
        tracking=True,
        index=True,
        help="Operational journal this entry posts to. Must be associated "
             "with the chosen ledger via jito.ledger.journal.rel.",
    )

    # Computed list of journals available for the chosen ledger. Used as a
    # domain filter on the journal_id picker. Non-stored — recomputed each
    # time the ledger changes in the form.
    allowed_journal_ids = fields.Many2many(
        comodel_name='account.journal',
        compute='_compute_allowed_journal_ids',
        help="Journals associated with the chosen ledger via "
             "jito.ledger.journal.rel; used to filter the Journal picker.",
    )

    # company_id derives from the ledger so it's available the moment the
    # user picks a ledger (before the journal is set).
    company_id = fields.Many2one(
        comodel_name='res.company',
        related='ledger_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )

    # Discriminator. NL docs are nl_doc; extension adjustments come in
    # Phase 3 (ext_adjustment); the four mgt_* values are reserved for
    # Phase 4 outputs.
    entry_type = fields.Selection(
        selection=[
            ('nl_doc', 'NL Document'),
            ('ext_adjustment', 'Extension Adjustment'),
            ('mgt_restate', 'Management Restatement'),
            ('mgt_bridge', 'Management Bridging'),
            ('mgt_regroup', 'Management Regrouping'),
            ('mgt_adj_je', 'Management Adjustment JE'),
        ],
        string='Entry Type',
        required=True,
        default='nl_doc',
        tracking=True,
        index=True,
    )

    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('posted', 'Posted'),
            ('reversed', 'Reversed'),
        ],
        string='Status',
        required=True,
        default='draft',
        tracking=True,
        index=True,
        copy=False,
    )

    date = fields.Date(
        string='Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
        index=True,
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Partner',
        tracking=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Document Currency',
        tracking=True,
        help="Optional document-level currency. Lines may use other currencies; "
             "balancing is enforced per-line-currency (HLD Decision #10).",
    )

    line_ids = fields.One2many(
        comodel_name='jito.ledger.move.line',
        inverse_name='move_id',
        string='Lines',
        copy=True,
    )

    # 17.0.3.1.0 — invoice-side view of line_ids that hides the auto-
    # generated AR/AP balancing line. The Customer Invoice form's
    # "Invoice Lines" tab binds to this; the "Journal Items" tab keeps
    # using line_ids (so admins still see the full double-entry).
    invoice_line_ids = fields.One2many(
        comodel_name='jito.ledger.move.line',
        inverse_name='move_id',
        string='Invoice Lines',
        domain=[('display_type', '!=', 'payment_term')],
        copy=False,
    )

    # ---- Invoicing layer (17.0.2.0.0) -----------------------------------

    move_type = fields.Selection(
        selection=[
            ('entry', 'Journal Entry'),
            ('out_invoice', 'Customer Invoice'),
            ('out_refund', 'Customer Credit Note'),
            ('in_invoice', 'Vendor Bill'),
            ('in_refund', 'Vendor Refund'),
        ],
        string='Type',
        required=True,
        default='entry',
        copy=False,
        tracking=True,
        index=True,
        help="Document type. 'Journal Entry' is the raw two-sided manual "
             "entry. The other four are partner-bound documents that "
             "auto-generate the AR/AP balancing line on Post.",
    )

    invoice_date = fields.Date(
        string='Invoice Date',
        copy=False,
        tracking=True,
        help="The date appearing on the document (independent of `date`, "
             "which controls posting period).",
    )
    invoice_date_due = fields.Date(
        string='Due Date',
        copy=False,
        tracking=True,
    )

    amount_untaxed = fields.Monetary(
        string='Untaxed Amount',
        compute='_compute_amount_totals',
        store=True,
        currency_field='currency_id',
    )
    amount_total = fields.Monetary(
        string='Total',
        compute='_compute_amount_totals',
        store=True,
        currency_field='currency_id',
        help="For invoice-style documents, the total amount the partner "
             "owes / is owed. NL is out of scope for tax (FR-15) so "
             "amount_total == amount_untaxed.",
    )

    @api.depends('line_ids.price_subtotal', 'move_type')
    def _compute_amount_totals(self):
        for move in self:
            if move.move_type in ('entry', False):
                move.amount_untaxed = 0.0
                move.amount_total = 0.0
                continue
            product_lines = move.line_ids.filtered(
                lambda l: l.product_id or (l.price_unit or 0.0)
            )
            untaxed = sum(line.price_subtotal for line in product_lines)
            move.amount_untaxed = untaxed
            move.amount_total = untaxed  # FR-15: NL is no-tax

    # Soft FK: if this entry derives from an LL move, point at it for
    # traceability. Never written into. ondelete='set null' so the LL
    # side stays free.
    source_move_id = fields.Many2one(
        comodel_name='account.move',
        string='Statutory Source',
        ondelete='set null',
        readonly=True,
        copy=False,
        index=True,
        help="If this entry derives from a Leading-Ledger entry "
             "(e.g., via Bridging or Restatement in Phase 4), the source "
             "is referenced here. Read-only.",
    )

    # Reversal linkage (additive: both rows visible).
    reversed_entry_id = fields.Many2one(
        comodel_name='jito.ledger.move',
        string='Reversed Entry',
        readonly=True,
        copy=False,
        index=True,
        help="If set, this move is the additive counter-entry of the move "
             "it points to. The original keeps state='reversed'; the "
             "counter has state='posted'.",
    )
    reversal_move_ids = fields.One2many(
        comodel_name='jito.ledger.move',
        inverse_name='reversed_entry_id',
        string='Reversals',
        readonly=True,
    )

    # ---- computed helpers -------------------------------------------------

    @api.depends('ledger_id')
    def _compute_allowed_journal_ids(self):
        """The set of journals the user may pick once a ledger is chosen.

        Empty if no ledger is selected (the journal picker becomes empty,
        nudging the user toward the ledger field first).
        """
        Rel = self.env['jito.ledger.journal.rel']
        for move in self:
            if not move.ledger_id:
                move.allowed_journal_ids = self.env['account.journal']
                continue
            rels = Rel.search([('ledger_id', '=', move.ledger_id.id)])
            move.allowed_journal_ids = rels.mapped('journal_id')

    @api.onchange('journal_id')
    def _onchange_journal_id(self):
        """If the user picks a journal directly (e.g., via name search),
        sync the ledger from the journal's rel.
        """
        if not self.journal_id:
            return
        rel = self.env['jito.ledger.journal.rel'].search([
            ('journal_id', '=', self.journal_id.id),
        ], limit=1)
        if rel and rel.ledger_id != self.ledger_id:
            self.ledger_id = rel.ledger_id

    @api.onchange('ledger_id')
    def _onchange_ledger_id(self):
        """When the ledger changes, clear the journal if it no longer
        belongs to the new ledger.
        """
        if self.journal_id and self.ledger_id:
            rel = self.env['jito.ledger.journal.rel'].search([
                ('journal_id', '=', self.journal_id.id),
            ], limit=1)
            if rel.ledger_id != self.ledger_id:
                self.journal_id = False

    def _compute_display_name(self):
        for move in self:
            base = move.name if move.name and move.name != _('New') else (
                move.ref or _('Draft Entry #%s', move.id)
            )
            if move.state == 'reversed':
                base = '%s (reversed)' % base
            move.display_name = base

    # ---- constraints ------------------------------------------------------

    @api.constrains('line_ids', 'state')
    def _check_balanced_per_currency(self):
        """Per HLD Decision #10: for each currency present in the move's
        lines, sum of amount_currency must be zero (debit-side positive,
        credit-side negative; total nets to zero).

        Only enforced for posted moves — drafts may be transiently
        unbalanced while the user edits. action_post() runs the
        constraint chain explicitly.
        """
        for move in self:
            if move.state == 'draft':
                continue
            if not move.line_ids:
                raise ValidationError(_(
                    "Move '%s' has no lines.", move.display_name,
                ))
            sums = defaultdict(float)
            for line in move.line_ids:
                if not line.currency_id:
                    raise ValidationError(_(
                        "Line '%s' on move '%s' has no currency_id set.",
                        line.name or '?', move.display_name,
                    ))
                sums[line.currency_id.id] += line.amount_currency
            unbalanced = []
            for currency_id, total in sums.items():
                currency = self.env['res.currency'].browse(currency_id)
                if not currency.is_zero(total):
                    unbalanced.append((currency.name, total))
            if unbalanced:
                rows = '\n'.join(
                    '  %s: %s (must be 0)' % (name, total)
                    for name, total in unbalanced
                )
                raise ValidationError(_(
                    "Move '%s' is not balanced per currency:\n%s",
                    move.display_name, rows,
                ))

    @api.constrains('ledger_id', 'company_id')
    def _check_ledger_company(self):
        for move in self:
            if move.ledger_id and move.ledger_id.company_id != move.company_id:
                raise ValidationError(_(
                    "Move '%s' is in company '%s' but ledger '%s' belongs to '%s'.",
                    move.display_name,
                    move.company_id.display_name,
                    move.ledger_id.display_name,
                    move.ledger_id.company_id.display_name,
                ))

    @api.constrains('journal_id')
    def _check_journal_in_managed_ledger(self):
        """The chosen journal must be associated with a Non-Leading or
        Extension ledger via jito.ledger.journal.rel. Journals not in
        any rel, or in a rel pointing at a Leading ledger, are rejected.
        """
        Rel = self.env['jito.ledger.journal.rel']
        for move in self:
            if not move.journal_id:
                continue
            rel = Rel.search([('journal_id', '=', move.journal_id.id)], limit=1)
            if not rel:
                raise ValidationError(_(
                    "Journal '%s' is not associated with any management ledger. "
                    "Configure it in Management Ledger → Ledgers → <ledger> → "
                    "Journals tab before posting entries through it.",
                    move.journal_id.display_name,
                ))
            if rel.ledger_id.kind == 'leading':
                raise ValidationError(_(
                    "Journal '%s' is associated with the Leading Ledger ('%s'). "
                    "Management-ledger journal entries cannot be posted to the "
                    "Leading Ledger — those go through stock Odoo Accounting. "
                    "Re-associate the journal with a Non-Leading or Extension "
                    "ledger.",
                    move.journal_id.display_name,
                    rel.ledger_id.display_name,
                ))

    @api.constrains('journal_id', 'state')
    def _check_journal_id_required_when_posted(self):
        """journal_id is soft-required: drafts may exist without a journal
        (so existing rows from earlier 17.0.1.0.x versions remain editable),
        but posting requires it.
        """
        for move in self:
            if move.state == 'draft':
                continue
            if not move.journal_id:
                raise ValidationError(_(
                    "Move '%s' cannot be posted without a journal.",
                    move.display_name,
                ))

    @api.constrains('reversed_entry_id', 'state')
    def _check_reversal_link(self):
        for move in self:
            if move.reversed_entry_id and move.reversed_entry_id.id == move.id:
                raise ValidationError(_(
                    "A move cannot be its own reversal (move '%s').",
                    move.display_name,
                ))

    # ---- period-lock inheritance (HLD Decision #12) ----------------------

    def _check_fiscalyear_lock_date(self):
        """Mirror of stock account.move._check_fiscalyear_lock_date()
        (account_move.py:1956-1965).

        Calls company._get_user_fiscal_lock_date() to honour the user's
        group-aware lock policy: managers (account.group_account_manager,
        which our group_mgmt_ledger_senior_accountant + finance_manager
        + admin all imply) are bound by `fiscalyear_lock_date` only;
        plain accountants are bound by max(period_lock_date,
        fiscalyear_lock_date).

        Tax-lock dates are not enforced here (NL is out of scope for tax
        per FR-15).
        """
        for move in self:
            lock_date = move.company_id._get_user_fiscal_lock_date()
            if move.date and move.date <= lock_date:
                if self.user_has_groups('account.group_account_manager'):
                    message = _(
                        "You cannot post NL Ledger entries on or before the "
                        "fiscal-year lock date %s.",
                        format_date(self.env, lock_date),
                    )
                else:
                    message = _(
                        "You cannot post NL Ledger entries on or before the "
                        "lock date %s. Check the company settings or ask "
                        "someone with the 'Adviser' role.",
                        format_date(self.env, lock_date),
                    )
                raise UserError(message)
        return True

    # ---- create ----------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """Auto-resolve ``ledger_id`` from ``journal_id`` when programmatic
        callers (Phase 4 wizards: bridging, restatement, regrouping,
        adjustment JE) pass only the journal.

        Without this, the stored related ``company_id`` ends up False and
        the multi-company record rule rejects with a "no create access"
        error. The form-driven path is unaffected — it sets ledger_id
        first, then journal_id is filtered to that ledger's allowed list.
        """
        Rel = self.env['jito.ledger.journal.rel']
        for vals in vals_list:
            if vals.get('journal_id') and not vals.get('ledger_id'):
                rel = Rel.search([('journal_id', '=', vals['journal_id'])], limit=1)
                if rel:
                    vals['ledger_id'] = rel.ledger_id.id
        return super().create(vals_list)

    # ---- workflow ---------------------------------------------------------

    def action_post(self):
        """Transition draft → posted.

        Runs the full constraint chain explicitly:
          1. journal_id is set (UserError if missing)
          2. partner_id is set when move_type is invoice-style (UserError if missing)
          3. invoice-style moves get the AR/AP balancing line auto-added
          4. period-lock check (UserError if violated)
          5. each line passes its own constraints (semantic-account rules)
          6. per-currency balance (re-checked at write time via @constrains)
          7. assigns sequence number based on move_type
        """
        for move in self:
            if move.state != 'draft':
                raise UserError(_(
                    "Only draft moves can be posted (move '%s' is %s).",
                    move.display_name, move.state,
                ))
            if not move.journal_id:
                raise UserError(_(
                    "Cannot post move '%s' without a journal. Pick a journal "
                    "associated with a Non-Leading or Extension ledger.",
                    move.display_name,
                ))
            if move.move_type and move.move_type != 'entry':
                if not move.partner_id:
                    raise UserError(_(
                        "Cannot post a %s without a partner.",
                        dict(self._fields['move_type']._description_selection(self.env))[move.move_type],
                    ))
                # Auto-generate the AR/AP balancing line idempotently.
                move._sync_partner_balancing_line()
            if not move.line_ids:
                raise UserError(_(
                    "Cannot post move '%s' with no lines.", move.display_name,
                ))
            move._check_fiscalyear_lock_date()
            if move.name == _('New') or not move.name:
                seq_code = move._get_sequence_code()
                seq = self.env['ir.sequence'].with_company(move.company_id).next_by_code(seq_code)
                move.name = seq or _('New')
        # Bulk write triggers the per-currency balance constraint.
        self.write({'state': 'posted'})
        return True

    # ---- Invoicing helpers (17.0.2.0.0) ----------------------------------

    def _get_sequence_code(self):
        """Pick the ir.sequence code based on move_type.

        Per-doc-type sequences match stock Odoo conventions: invoices
        get INV/yyyy, credit notes CN/yyyy, bills BILL/yyyy, refunds
        REF/yyyy. Plain entries fall back to the generic
        jito.ledger.move sequence (JLM/yyyy).
        """
        self.ensure_one()
        return {
            'out_invoice': 'jito.ledger.invoice',
            'out_refund': 'jito.ledger.credit_note',
            'in_invoice': 'jito.ledger.bill',
            'in_refund': 'jito.ledger.refund',
        }.get(self.move_type, 'jito.ledger.move')

    def _get_partner_balancing_account(self):
        """Find this move's AR/AP balancing account.

        17.0.3.0.0: customer-side moves consult
        ``company.jito_default_invoice_receivable_account_id`` first;
        fall back to MGT.RECEIVABLE by code if unset. Vendor-side moves
        still resolve via MGT.PAYABLE (vendor-side config is a
        future-pass improvement).
        """
        self.ensure_one()
        if self.move_type in ('out_invoice', 'out_refund'):
            configured = self.company_id.jito_default_invoice_receivable_account_id
            if configured:
                return configured
            code = 'MGT.RECEIVABLE'
        elif self.move_type in ('in_invoice', 'in_refund'):
            configured = self.company_id.jito_default_bill_payable_account_id
            if configured:
                return configured
            code = 'MGT.PAYABLE'
        else:
            return self.env['jito.ledger.account']
        return self.env['jito.ledger.account'].search([
            ('code', '=', code),
            ('company_id', '=', self.company_id.id),
        ], limit=1)

    def _get_default_income_account(self):
        """Default income account for product lines on customer-side moves.

        17.0.3.0.0: consults ``company.jito_default_invoice_income_account_id``
        first; falls back to MGT.SALES by code.
        """
        self.ensure_one()
        configured = self.company_id.jito_default_invoice_income_account_id
        if configured:
            return configured
        return self.env['jito.ledger.account'].search([
            ('code', '=', 'MGT.SALES'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)

    def _get_default_expense_account(self):
        """Default expense account for product lines on vendor-side moves.

        17.0.4.0.0: consults ``company.jito_default_bill_expense_account_id``
        first; falls back to MGT.EXPENSE by code.
        """
        self.ensure_one()
        configured = self.company_id.jito_default_bill_expense_account_id
        if configured:
            return configured
        return self.env['jito.ledger.account'].search([
            ('code', '=', 'MGT.EXPENSE'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)

    @api.model
    def default_get(self, fields_list):
        """Pre-fill ledger / journal / currency / entry_type when creating
        an invoice-style document (17.0.3.0.0 + 17.0.4.0.0 + 17.0.5.3.0).

        The simplified Customer Invoice and Vendor Bill forms hide ledger
        and journal. The actions pass ``default_move_type='out_invoice'``
        / ``='in_invoice'`` / refund variants so we can recognise the
        doc-type context here and seed sensible values.

        For all four invoice-style types we also default ``currency_id``
        to the company currency — lines pick it up via the form's
        ``default_currency_id: currency_id`` context, and the line's
        precompute uses it as a fallback. Plain Journal Entries keep the
        generic UX (user picks ledger, journal, currency manually).
        """
        res = super().default_get(fields_list)
        ctx_type = self.env.context.get('default_move_type')
        invoice_types = ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')
        if ctx_type not in invoice_types:
            return res
        company = self.env.company
        if 'currency_id' in fields_list and not res.get('currency_id'):
            if company.currency_id:
                res['currency_id'] = company.currency_id.id
        # ledger / journal pre-fill only for the two simplified-form
        # doc-types (Customer Invoice + Vendor Bill). Refund / credit-
        # note flows still go through the generic form where the user
        # picks them explicitly.
        journal_config = {
            'out_invoice': ('jito_default_invoice_journal_id', 'CINV'),
            'in_invoice':  ('jito_default_bill_journal_id',    'CBILL'),
        }
        if ctx_type in journal_config:
            if 'ledger_id' in fields_list and not res.get('ledger_id'):
                nl = self.env['jito.ledger'].search([
                    ('company_id', '=', company.id),
                    ('kind', '=', 'non_leading'),
                ], limit=1)
                if nl:
                    res['ledger_id'] = nl.id
            if 'journal_id' in fields_list and not res.get('journal_id'):
                field_name, fallback_code = journal_config[ctx_type]
                journal = company[field_name]
                if not journal:
                    journal = self.env['account.journal'].search([
                        ('code', '=', fallback_code),
                        ('company_id', '=', company.id),
                    ], limit=1)
                if journal:
                    res['journal_id'] = journal.id
        if 'entry_type' in fields_list:
            res.setdefault('entry_type', 'nl_doc')
        return res

    def _sync_partner_balancing_line(self):
        """Idempotently create / update the AR/AP balancing line for an
        invoice-style move.

        17.0.3.1.0: identifies the balancing line by
        `display_type='payment_term'` (was: account match). The Customer
        Invoice form's Invoice Lines tab filters out payment_term lines,
        so they never pollute the user's lines tab even if the user
        re-bound the receivable account.
        """
        self.ensure_one()
        partner_account = self._get_partner_balancing_account()
        if not partner_account:
            raise UserError(_(
                "Cannot find the default management account "
                "(MGT.RECEIVABLE / MGT.PAYABLE) for company '%s'. Run "
                "Configuration → Chart of Accounts and ensure the "
                "MGT-bucket seeds were created on install.",
                self.company_id.display_name,
            ))
        Line = self.env['jito.ledger.move.line']
        product_lines = self.line_ids.filtered(
            lambda l: l.display_type != 'payment_term'
        )
        if not product_lines:
            return
        from collections import defaultdict
        sums = defaultdict(float)
        for line in product_lines:
            currency = line.currency_id or self.currency_id
            if not currency:
                continue
            sums[currency.id] += line.amount_currency
        existing = self.line_ids.filtered(
            lambda l: l.display_type == 'payment_term'
        )
        if existing:
            existing.unlink()
        for currency_id, total in sums.items():
            if not total:
                continue
            Line.create({
                'move_id': self.id,
                'account_id': partner_account.id,
                'partner_id': self.partner_id.id,
                'name': self.partner_id.name or self.ref or self.name,
                'currency_id': currency_id,
                'amount_currency': -total,
                'display_type': 'payment_term',
            })

    @api.onchange(
        'invoice_line_ids',
        'partner_id',
        'currency_id',
    )
    def _onchange_recompute_payment_term_lines(self):
        """Live-preview the AR/AP balancing line in the Journal Items
        tab while in draft. Without this the tab only shows the user's
        product lines until Post.

        Pattern: drop the existing in-memory payment_term lines, then
        compute fresh ones from the product-line totals and add them
        via NewId records. Recordset arithmetic (`-=`, `+`) is the
        in-memory equivalent of unlink / link in onchange context.
        """
        if self.move_type not in ('out_invoice', 'out_refund', 'in_invoice', 'in_refund'):
            return
        existing_pt = self.line_ids.filtered(
            lambda l: l.display_type == 'payment_term'
        )
        if existing_pt:
            self.line_ids -= existing_pt
        if not self.partner_id or not self.invoice_line_ids:
            return
        partner_account = self._get_partner_balancing_account()
        if not partner_account:
            return
        sums = defaultdict(float)
        for line in self.invoice_line_ids:
            currency = line.currency_id or self.currency_id
            if not currency:
                continue
            sums[currency.id] += line.amount_currency
        Line = self.env['jito.ledger.move.line']
        for currency_id, total in sums.items():
            if not total:
                continue
            new_line = Line.new({
                'account_id': partner_account.id,
                'partner_id': self.partner_id.id,
                'name': self.partner_id.name or self.ref or self.name or '',
                'currency_id': currency_id,
                'amount_currency': -total,
                'display_type': 'payment_term',
            })
            self.line_ids += new_line

    def action_draft(self):
        """Transition posted → draft. Allowed only for moves that have
        not been reversed and are not the counter-entry of a reversal.
        """
        for move in self:
            if move.state == 'reversed':
                raise UserError(_(
                    "Move '%s' has been reversed; reset to draft is not allowed. "
                    "Reverse the counter-entry instead.",
                    move.display_name,
                ))
            if move.reversed_entry_id:
                raise UserError(_(
                    "Move '%s' is the counter-entry of a reversal; reset to "
                    "draft would orphan the original.",
                    move.display_name,
                ))
        self.write({'state': 'draft'})
        return True

    def action_view_as_invoice(self):
        """Re-open the same record using the invoice-flavoured action /
        form for its move_type.

        17.0.3.1.1: surfaces from the generic Journal Entry form's header
        when move_type is invoice-style, so the user can jump to the
        proper Customer Invoice / Credit Note / Vendor Bill / Refund view
        without going back to the Customers/Vendors menu.
        """
        self.ensure_one()
        action_xmlid_map = {
            'out_invoice': 'jito_ledger_nl.action_jito_ledger_customer_invoices',
            'out_refund':  'jito_ledger_nl.action_jito_ledger_customer_credit_notes',
            'in_invoice':  'jito_ledger_nl.action_jito_ledger_vendor_bills',
            'in_refund':   'jito_ledger_nl.action_jito_ledger_vendor_refunds',
        }
        xmlid = action_xmlid_map.get(self.move_type)
        if not xmlid:
            raise UserError(_(
                "Move '%s' is not an invoice-style document.",
                self.display_name,
            ))
        action = self.env['ir.actions.act_window']._for_xml_id(xmlid)
        action['res_id'] = self.id
        action['view_mode'] = 'form'
        action['views'] = [(v_id, mode) for v_id, mode in action.get('views', []) if mode == 'form']
        return action

    def action_view_reversals(self):
        """Open an act_window listing the counter-entries that reversed this move."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reversals'),
            'res_model': 'jito.ledger.move',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.reversal_move_ids.ids)],
            'context': {'create': False},
        }

    def action_reverse(self):
        """Create an additive reversal: a counter-move with negated
        amount_currency lines. The original is flagged 'reversed'; the
        counter is auto-posted.
        """
        for move in self:
            if move.state != 'posted':
                raise UserError(_(
                    "Only posted moves can be reversed (move '%s' is %s).",
                    move.display_name, move.state,
                ))
            if move.reversal_move_ids:
                raise UserError(_(
                    "Move '%s' has already been reversed.",
                    move.display_name,
                ))
            counter_vals = {
                'journal_id': move.journal_id.id,
                # ledger_id and company_id derive from journal_id
                'entry_type': move.entry_type,
                'date': fields.Date.context_today(self),
                'partner_id': move.partner_id.id,
                'currency_id': move.currency_id.id,
                'ref': _("Reversal of %s") % (move.name or move.ref or move.id),
                'reversed_entry_id': move.id,
                'state': 'draft',
                'name': _('New'),
                'line_ids': [
                    (0, 0, {
                        'account_id': line.account_id.id,
                        'partner_id': line.partner_id.id,
                        'name': line.name,
                        'currency_id': line.currency_id.id,
                        'amount_currency': -line.amount_currency,
                    })
                    for line in move.line_ids
                ],
            }
            counter = self.create(counter_vals)
            counter.action_post()
            move.write({'state': 'reversed'})
            move.message_post(body=_(
                "Reversed by %s.", counter.display_name,
            ))
            counter.message_post(body=_(
                "Counter-entry of %s.", move.display_name,
            ))
        return True

    # ---- guards ----------------------------------------------------------

    @api.ondelete(at_uninstall=False)
    def _unlink_only_drafts(self):
        for move in self:
            if move.state != 'draft':
                raise UserError(_(
                    "Only draft moves can be deleted (move '%s' is %s). "
                    "Reverse the move instead.",
                    move.display_name, move.state,
                ))
