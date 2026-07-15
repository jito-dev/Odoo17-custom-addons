import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .revolut_transaction import TRANSACTION_TYPE_SELECTION

_logger = logging.getLogger(__name__)


class RevolutInjectionRule(models.Model):
    _name = 'revolut.injection.rule'
    _description = 'Revolut → GL account injection routing rule'
    _order = 'sequence, id'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company, index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    active = fields.Boolean(default=True)

    match_field = fields.Selection(
        [('merchant', 'Merchant'), ('description', 'Description'), ('both', 'Either')],
        string='Match on', default='both', required=True)
    match_type = fields.Selection(
        [('contains', 'contains'), ('regex', 'regex'), ('equals', 'equals')],
        string='Operator', default='contains', required=True,
        help="contains/equals: case-insensitive; a pipe-separated pattern "
             "(e.g. 'openai|claude|cursor') matches if ANY token matches. "
             "regex: a Python regular expression (re.search, case-insensitive).")
    pattern = fields.Char(required=True)
    transaction_type = fields.Selection(
        TRANSACTION_TYPE_SELECTION, string='Apply to type',
        help="Optional: restrict this rule to a single transaction type. "
             "Leave empty to apply to any type.")
    account_id = fields.Many2one(
        'account.account', string='GL Account', required=True,
        domain="[('deprecated', '=', False), ('company_id', '=', company_id)]")
    match_count = fields.Integer(string='Hits', compute='_compute_match_count')

    @api.constrains('match_type', 'pattern')
    def _check_regex(self):
        for rule in self:
            if rule.match_type == 'regex':
                try:
                    re.compile(rule.pattern or '')
                except re.error as e:
                    raise ValidationError(_("Invalid regular expression: %s", e))

    # ── Matching ─────────────────────────────────────────────────────────────
    def _matches_values(self, merchant, description, ttype):
        """Core matcher against raw values (used for both records and previews)."""
        self.ensure_one()
        if self.transaction_type and ttype != self.transaction_type:
            return False
        if self.match_field == 'merchant':
            hay = merchant or ''
        elif self.match_field == 'description':
            hay = description or ''
        else:
            hay = f"{merchant or ''} {description or ''}"
        hay = hay.lower()
        pat = (self.pattern or '').strip()
        if not pat:
            return False
        if self.match_type == 'regex':
            try:
                return bool(re.search(pat, hay, re.IGNORECASE))
            except re.error:
                return False
        tokens = [t.strip().lower() for t in pat.split('|') if t.strip()]
        if self.match_type == 'equals':
            return hay in tokens
        return any(t in hay for t in tokens)  # contains

    def _matches(self, tx):
        return self._matches_values(tx.merchant_name, tx.description, tx.transaction_type)

    def _matching_transaction_ids(self):
        self.ensure_one()
        rows = self.env['revolut.transaction'].search_read(
            [('company_id', '=', self.company_id.id)],
            ['merchant_name', 'description', 'transaction_type'])
        return [r['id'] for r in rows
                if self._matches_values(r['merchant_name'], r['description'], r['transaction_type'])]

    def _compute_match_count(self):
        # Load each company's transactions once, then count per rule in Python.
        cache = {}
        for cid in set(self.mapped('company_id').ids):
            cache[cid] = self.env['revolut.transaction'].search_read(
                [('company_id', '=', cid)],
                ['merchant_name', 'description', 'transaction_type'])
        for rule in self:
            rows = cache.get(rule.company_id.id, [])
            rule.match_count = sum(
                1 for r in rows
                if rule._matches_values(r['merchant_name'], r['description'], r['transaction_type']))

    def action_preview_matches(self):
        self.ensure_one()
        ids = self._matching_transaction_ids()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Matches — %s', self.name),
            'res_model': 'revolut.transaction',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', ids)],
            'context': {'create': False},
        }
