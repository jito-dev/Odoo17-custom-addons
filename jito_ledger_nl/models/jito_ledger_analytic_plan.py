# -*- coding: utf-8 -*-

"""ML Analytic Plan (17.0.9.0.0).

Parallel to stock ``account.analytic.plan`` but standalone — the
Management Ledger keeps its analytic dimension fully separate from
stock Accounting. Hierarchical via ``_parent_store``. ``get_relevant_plans``
feeds the forked ``jito_analytic_distribution`` OWL widget.
"""

from random import randint

from odoo import api, fields, models


class JitoLedgerAnalyticPlan(models.Model):
    _name = 'jito.ledger.analytic.plan'
    _description = 'ML Analytic Plan'
    _parent_store = True
    _rec_name = 'complete_name'
    _order = 'complete_name asc'

    def _default_color(self):
        return randint(1, 11)

    name = fields.Char(required=True, translate=True)
    description = fields.Text(string='Description')
    complete_name = fields.Char(
        string='Complete Name',
        compute='_compute_complete_name', recursive=True, store=True,
    )
    parent_id = fields.Many2one(
        'jito.ledger.analytic.plan',
        string='Parent', ondelete='cascade', index=True,
    )
    parent_path = fields.Char(index=True, unaccent=False)
    children_ids = fields.One2many(
        'jito.ledger.analytic.plan', 'parent_id', string='Childrens',
    )
    root_plan_id = fields.Many2one(
        'jito.ledger.analytic.plan',
        string='Root Plan', compute='_compute_root_plan_id', store=True,
    )
    account_ids = fields.One2many(
        'jito.ledger.analytic.account', 'plan_id', string='Analytic Accounts',
    )
    account_count = fields.Integer(
        string='Analytic Accounts Count', compute='_compute_account_count',
    )
    color = fields.Integer(default=_default_color)
    sequence = fields.Integer(default=10)
    default_applicability = fields.Selection(
        selection=[
            ('optional', 'Optional'),
            ('mandatory', 'Mandatory'),
            ('unavailable', 'Unavailable'),
        ],
        string='Default Applicability',
        default='optional', required=True,
        help="Mandatory plans require a 100% distribution on every ML line "
             "they apply to. Optional plans never block posting.",
    )
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company,
    )
    active = fields.Boolean(default=True)

    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for plan in self:
            if plan.parent_id:
                plan.complete_name = f'{plan.parent_id.complete_name} / {plan.name}'
            else:
                plan.complete_name = plan.name

    @api.depends('parent_id', 'parent_id.root_plan_id')
    def _compute_root_plan_id(self):
        for plan in self:
            plan.root_plan_id = plan.parent_id.root_plan_id or plan.parent_id or plan

    def _compute_account_count(self):
        for plan in self:
            plan.account_count = len(plan.account_ids)

    @api.model
    def get_relevant_plans(self, **kwargs):
        """Return the plans the analytic-distribution widget should show.

        Simplified vs. stock (no product/account applicability sub-rules):
        every active root plan for the company, with applicability taken
        from ``default_applicability``. ``force_applicability`` (passed by
        the widget) overrides. Shape matches what the OWL widget expects:
        ``[{id, name, color, applicability, all_account_count}]``.
        """
        company_id = kwargs.get('company_id') or self.env.company.id
        force = kwargs.get('applicability')
        domain = [
            ('parent_id', '=', False),
            ('company_id', 'in', [company_id, False]),
        ]
        plans = self.search(domain)
        result = []
        for plan in plans:
            applicability = force or plan.default_applicability
            if applicability == 'unavailable':
                continue
            all_account_count = self.env['jito.ledger.analytic.account'].search_count([
                ('root_plan_id', '=', plan.id),
                ('company_id', 'in', [company_id, False]),
            ])
            result.append({
                'id': plan.id,
                'name': plan.name,
                'color': plan.color,
                'applicability': applicability,
                'all_account_count': all_account_count,
            })
        return result

    def action_view_accounts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'jito.ledger.analytic.account',
            'view_mode': 'tree,form',
            'domain': [('plan_id', 'child_of', self.id)],
            'context': {'default_plan_id': self.id},
        }
