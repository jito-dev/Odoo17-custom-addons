# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class JitoLedger(models.Model):
    _name = 'jito.ledger'
    _description = 'Management Ledger (Leading / Non-Leading)'
    _inherit = ['mail.thread']
    _order = 'company_id, kind, code, id'
    _check_company_auto = True

    name = fields.Char(
        string='Name',
        required=True,
        tracking=True,
    )
    code = fields.Char(
        string='Code',
        required=True,
        tracking=True,
        help="Short identifier used in reports and on journal entries.",
    )
    kind = fields.Selection(
        selection=[
            ('leading', 'Leading Ledger'),
            ('non_leading', 'Non-Leading (Parallel) Ledger'),
        ],
        string='Kind',
        required=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        tracking=True,
    )
    # 17.0.2.0.0 — journals are now ML-owned via jito.ledger.journal
    # (Option C). The old jito.ledger.journal.rel rel model is retired
    # as a code dependency; its DB table is kept for migration safety
    # but no field reads it after the upgrade.
    journal_ids = fields.One2many(
        comodel_name='jito.ledger.journal',
        inverse_name='ledger_id',
        string='Journals',
        help="ML-owned journals belonging to this ledger.",
    )
    # Legacy O2M to the rel table — preserved as a hidden field on the
    # model so migrations can still query it. Not surfaced in views
    # from 17.0.2.0.0 onward.
    journal_rel_ids = fields.One2many(
        comodel_name='jito.ledger.journal.rel',
        inverse_name='ledger_id',
        string='Journal Associations (legacy)',
    )
    active = fields.Boolean(default=True, tracking=True)

    _sql_constraints = [
        (
            'jito_ledger_code_company_uniq',
            'UNIQUE(code, company_id)',
            'A ledger code must be unique within a company.',
        ),
    ]

    # _compute_journal_ids was retired in 17.0.2.0.0; journal_ids is
    # now a plain O2M to jito.ledger.journal (no compute needed).

    @api.constrains('kind', 'company_id')
    def _check_single_leading(self):
        # FR-01: exactly one leading ledger per company.
        for ledger in self:
            if ledger.kind != 'leading':
                continue
            other = self.search([
                ('kind', '=', 'leading'),
                ('company_id', '=', ledger.company_id.id),
                ('id', '!=', ledger.id),
            ], limit=1)
            if other:
                raise ValidationError(_(
                    "Company '%s' already has a leading ledger ('%s'). "
                    "Only one leading ledger is allowed per company.",
                    ledger.company_id.display_name, other.display_name,
                ))

    @api.constrains('kind', 'company_id')
    def _check_single_non_leading(self):
        # FR-03: zero or one non-leading ledger per company in v1.
        for ledger in self:
            if ledger.kind != 'non_leading':
                continue
            other = self.search([
                ('kind', '=', 'non_leading'),
                ('company_id', '=', ledger.company_id.id),
                ('id', '!=', ledger.id),
            ], limit=1)
            if other:
                raise ValidationError(_(
                    "Company '%s' already has a non-leading ledger ('%s'). "
                    "v1 allows at most one non-leading ledger per company.",
                    ledger.company_id.display_name, other.display_name,
                ))

    # ---- singleton-form action (17.0.1.4.0) ------------------------------

    @api.model
    def action_open_singleton(self, kind):
        """Return an act_window opening THE singleton ledger of the given
        ``kind`` (one of: ``leading``, ``non_leading``)
        for the user's current company.

        Self-heals: if the singleton is missing (e.g., admin deleted it
        in Developer Mode), the relevant ensure_*_for_company helper is
        invoked to recreate it before opening. Means the menu always
        leads somewhere useful.
        """
        company = self.env.company
        record = self.search([
            ('company_id', '=', company.id),
            ('kind', '=', kind),
        ], limit=1)
        if not record:
            from odoo.addons.jito_ledger_core.hooks import (
                _ensure_leading_ledger_for_company,
                _ensure_non_leading_ledger_for_company,
            )
            ensure_fn = {
                'leading': _ensure_leading_ledger_for_company,
                'non_leading': _ensure_non_leading_ledger_for_company,
            }.get(kind)
            if not ensure_fn:
                raise ValueError("Unknown ledger kind: %r" % (kind,))
            record = ensure_fn(self.env, company)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'jito.ledger',
            'view_mode': 'form',
            'res_id': record.id,
            'target': 'current',
        }
