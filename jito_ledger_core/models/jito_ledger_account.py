# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


# Allowed semantic-prefix families per Specification §Management Account
# Semantic Layers and HLD §4.4. A code that starts with one of these
# prefixes (case-sensitive, followed by a dot) is considered a management
# account; the body after the dot must be non-empty and free of
# whitespace.
SEMANTIC_PREFIXES = ('FAAP.', 'MGT.', 'CLR.', 'GRP.')


def _split_prefix(code):
    """Return the prefix family ('FAAP.' / 'MGT.' / 'CLR.' / 'GRP.') for
    a code, or None if the code does not start with any of them."""
    if not code:
        return None
    for prefix in SEMANTIC_PREFIXES:
        if code.startswith(prefix):
            return prefix
    return None


class JitoLedgerAccount(models.Model):
    """Management-layer chart of accounts.

    Per HLD Decision #13, the management layer keeps its own chart in
    this model. Stock Odoo's `account.account` is **not** extended,
    seeded, or constrained — it stays exactly as Odoo ships.

    `jito.ledger.move.line` (Phase 2) references this model for its
    `account_id` field. FAAP.* records may carry a soft pointer to a
    statutory `account.account` via `statutory_account_id` for
    cross-reference and combined-view reporting.
    """

    _name = 'jito.ledger.account'
    _description = 'Management-Layer Account'
    _inherit = ['mail.thread']
    _order = 'company_id, code, id'
    _check_company_auto = True
    _rec_names_search = ['code', 'name']

    name = fields.Char(
        string='Account Name',
        required=True,
        tracking=True,
        translate=True,
    )
    code = fields.Char(
        string='Code',
        size=64,
        required=True,
        index=True,
        tracking=True,
        help="Semantic-prefixed code: FAAP.<sub>, MGT.<sub>, CLR.<sub>, or GRP.<sub>.",
    )
    # Reuse stock Odoo's account_type selection so reports (Phase 5) can
    # leverage the same grouping conventions as `account.account`.
    account_type = fields.Selection(
        selection=[
            ('asset_receivable', 'Receivable'),
            ('asset_cash', 'Bank and Cash'),
            ('asset_current', 'Current Assets'),
            ('asset_non_current', 'Non-current Assets'),
            ('asset_prepayments', 'Prepayments'),
            ('asset_fixed', 'Fixed Assets'),
            ('liability_payable', 'Payable'),
            ('liability_credit_card', 'Credit Card'),
            ('liability_current', 'Current Liabilities'),
            ('liability_non_current', 'Non-current Liabilities'),
            ('equity', 'Equity'),
            ('equity_unaffected', 'Current Year Earnings'),
            ('income', 'Income'),
            ('income_other', 'Other Income'),
            ('expense', 'Expenses'),
            ('expense_depreciation', 'Depreciation'),
            ('expense_direct_cost', 'Cost of Revenue'),
            ('off_balance', 'Off-Balance Sheet'),
        ],
        string='Type',
        required=True,
        tracking=True,
        help="Mirrors stock Odoo account_type so management reports can group accounts using familiar conventions.",
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        tracking=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Account Currency',
        tracking=True,
        help="Optional. Forces all journal items in this account to use a specific currency.",
    )
    company_currency_id = fields.Many2one(related='company_id.currency_id')
    statutory_account_id = fields.Many2one(
        comodel_name='account.account',
        string='Statutory Account',
        ondelete='set null',
        tracking=True,
        check_company=True,
        help="For FAAP.* mirrors: the stock `account.account` this management-layer "
             "account projects. Used by combined-view reporting in Phase 5. Optional "
             "and never set on MGT/CLR/GRP accounts. Cross-company assignment is "
             "rejected by Odoo's check_company.",
    )
    semantic_family = fields.Selection(
        selection=[
            ('faap', 'FAAP — Default projection'),
            ('mgt', 'MGT — Final managerial meaning'),
            ('clr', 'CLR — Clearing / transit'),
            ('grp', 'GRP — Grouping (non-posting)'),
        ],
        string='Semantic Family',
        compute='_compute_semantic_family',
        store=True,
        index=True,
        help="Derived from the code's prefix. Used by reports to filter by family.",
    )
    active = fields.Boolean(default=True, tracking=True)

    _sql_constraints = [
        (
            'jito_account_code_company_uniq',
            'UNIQUE(code, company_id)',
            'A management-layer account code must be unique within a company.',
        ),
    ]

    @api.depends('code')
    def _compute_semantic_family(self):
        prefix_to_family = {
            'FAAP.': 'faap',
            'MGT.': 'mgt',
            'CLR.': 'clr',
            'GRP.': 'grp',
        }
        for record in self:
            prefix = _split_prefix(record.code or '')
            record.semantic_family = prefix_to_family.get(prefix, False)

    @api.constrains('code')
    def _check_jito_semantic_prefix(self):
        """Reject codes that don't follow the FAAP/MGT/CLR/GRP convention.

        Per HLD §4.4 and Decision #13, every record in this model is a
        management-layer account; the prefix policy is mandatory.
        Statutory accounts live in stock `account.account` and are not
        affected by this constraint.
        """
        for record in self:
            code = record.code or ''
            prefix = _split_prefix(code)
            if not prefix:
                raise ValidationError(_(
                    "Account code '%s' must start with one of: %s.",
                    code, ', '.join(SEMANTIC_PREFIXES),
                ))
            body = code[len(prefix):]
            if not body:
                raise ValidationError(_(
                    "Account code '%s' has an empty body after the '%s' prefix.",
                    code, prefix,
                ))
            if any(ch.isspace() for ch in body):
                raise ValidationError(_(
                    "Account code '%s' must not contain whitespace.",
                    code,
                ))

    @api.constrains('semantic_family', 'statutory_account_id')
    def _check_statutory_only_for_faap(self):
        for record in self:
            if record.statutory_account_id and record.semantic_family != 'faap':
                raise ValidationError(_(
                    "Account '%s' (%s) carries a statutory_account_id but is not a "
                    "FAAP.* mirror. Only FAAP.* accounts may reference a statutory account.",
                    record.code, record.semantic_family,
                ))
