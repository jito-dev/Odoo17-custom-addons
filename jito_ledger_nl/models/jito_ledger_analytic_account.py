# -*- coding: utf-8 -*-

"""ML Analytic Account (17.0.9.0.0).

Parallel to stock ``account.analytic.account``; standalone management
analytic dimension. Hierarchical (`_parent_store`). Display name is
``[code] name`` like stock.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.osv import expression


class JitoLedgerAnalyticAccount(models.Model):
    _name = 'jito.ledger.analytic.account'
    _description = 'ML Analytic Account'
    _inherit = ['mail.thread']
    _parent_store = True
    _rec_names_search = ['name', 'code']
    _order = 'plan_id, code, name'

    name = fields.Char(string='Analytic Account', required=True, tracking=True)
    code = fields.Char(string='Reference', tracking=True)
    active = fields.Boolean(default=True, tracking=True)

    plan_id = fields.Many2one(
        'jito.ledger.analytic.plan',
        string='Plan', required=True, ondelete='cascade', index=True,
        tracking=True,
    )
    root_plan_id = fields.Many2one(
        'jito.ledger.analytic.plan',
        string='Root Plan', related='plan_id.root_plan_id', store=True,
    )
    parent_id = fields.Many2one(
        'jito.ledger.analytic.account',
        string='Parent', ondelete='cascade', index=True,
        domain="[('plan_id', '=', plan_id)]",
    )
    parent_path = fields.Char(index=True, unaccent=False)
    child_ids = fields.One2many(
        'jito.ledger.analytic.account', 'parent_id', string='Children',
    )
    color = fields.Integer(related='root_plan_id.color')
    partner_id = fields.Many2one(
        'res.partner', string='Customer', tracking=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company,
    )

    # ---- Statutory mirror + reporting alignment (17.0.13.0.0) ----------
    # A mirrored account carries a soft pointer to the stock analytic
    # account it mirrors (set by the sync wizard); management-only accounts
    # leave it empty. ``scope`` derives from the pointer. ``base_code`` is
    # the FAAP<->MGT reporting join key (defaults to ``code``, editable to
    # align a mirror with a management account of the same concept). Stock
    # ``account.analytic.account`` is never written to.
    statutory_analytic_account_id = fields.Many2one(
        'account.analytic.account',
        string='Statutory Analytic Account',
        ondelete='set null', index=True,
        help="For mirrored accounts: the stock account.analytic.account this "
             "ML account mirrors. Empty on management-only accounts. Never "
             "written to.",
    )
    base_code = fields.Char(
        string='Base Code', size=64,
        compute='_compute_base_code', store=True, readonly=False, index=True,
        help="Alignment / join key for combined FAAP<->MGT analytic reporting. "
             "Defaults to the account code; override to align a statutory "
             "mirror with a management account representing the same concept.",
    )
    scope = fields.Selection(
        selection=[
            ('statutory', 'Statutory Mirror'),
            ('mgt', 'Management Only'),
        ],
        string='Scope',
        compute='_compute_scope', store=True, index=True,
        help="Statutory = mirrored from stock analytic (carries a pointer); "
             "Management = created directly in the Management Ledger.",
    )

    _sql_constraints = [
        (
            'code_plan_company_uniq',
            'unique(code, plan_id, company_id)',
            'An analytic account code must be unique within a plan per company.',
        ),
    ]

    @api.depends('code')
    def _compute_base_code(self):
        """Default the reporting join key to the account code. Stored +
        editable, so a manual override survives until ``code`` changes."""
        for account in self:
            account.base_code = account.code or False

    @api.depends('statutory_analytic_account_id')
    def _compute_scope(self):
        for account in self:
            account.scope = (
                'statutory' if account.statutory_analytic_account_id else 'mgt'
            )

    @api.constrains('statutory_analytic_account_id', 'company_id')
    def _check_statutory_pointer(self):
        """Mirror pointer must stay company-consistent and 1:1 per company."""
        for account in self:
            stock = account.statutory_analytic_account_id
            if not stock:
                continue
            if stock.company_id and account.company_id \
                    and stock.company_id != account.company_id:
                raise ValidationError(_(
                    "Analytic account '%s' points at stock analytic account "
                    "'%s' which belongs to a different company.",
                    account.display_name, stock.display_name,
                ))
            dup = self.search([
                ('statutory_analytic_account_id', '=', stock.id),
                ('company_id', '=', account.company_id.id),
                ('id', '!=', account.id),
            ], limit=1)
            if dup:
                raise ValidationError(_(
                    "Stock analytic account '%s' is already mirrored by '%s' "
                    "in this company.",
                    stock.display_name, dup.display_name,
                ))

    # ---- Stock -> ML analytic projection helpers (17.0.13.0.0) --------
    # Shared by the read-only ``projected_distribution`` computes on
    # jito.ledger.statutory.analytic and jito.ledger.statutory.view.
    @api.model
    def _stock_mirror_index(self, stock_ids, company_ids):
        """Return ``{(stock analytic id, company id): ML mirror id}`` for the
        given stock analytic ids across the given companies (+ shared)."""
        index = {}
        if not stock_ids:
            return index
        rows = self.with_context(active_test=False).search_read(
            [
                ('statutory_analytic_account_id', 'in', list(stock_ids)),
                ('company_id', 'in', list(company_ids) + [False]),
            ],
            ['statutory_analytic_account_id', 'company_id'],
        )
        for m in rows:
            comp = m['company_id'][0] if m['company_id'] else False
            index[(m['statutory_analytic_account_id'][0], comp)] = m['id']
        return index

    @api.model
    def _project_stock_distribution(self, stock_distribution, company_id, index):
        """Translate a stock ``analytic_distribution`` (keyed by stock analytic
        ids) into ML mirror ids via ``index``. Unmapped ids are dropped;
        percentages are preserved (summed on key collision). Returns the
        translated dict, or ``False`` when nothing maps."""
        projected = {}
        for key, pct in (stock_distribution or {}).items():
            ml_ids = []
            for part in str(key).split(','):
                if not part:
                    continue
                ml_id = index.get((int(part), company_id)) \
                    or index.get((int(part), False))
                if ml_id:
                    ml_ids.append(str(ml_id))
            if not ml_ids:
                continue
            new_key = ','.join(ml_ids)
            projected[new_key] = projected.get(new_key, 0.0) + pct
        return projected or False

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for account in self:
            name = account.name or ''
            if account.code:
                name = f'[{account.code}] {name}'
            account.display_name = name

    @api.model
    def _name_search(self, name, domain=None, operator='ilike', limit=None, order=None):
        domain = domain or []
        if name:
            domain = expression.AND([
                domain,
                ['|', ('code', operator, name), ('name', operator, name)],
            ])
            name = ''
        return super()._name_search(name, domain, operator, limit, order)
