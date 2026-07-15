import json
import logging
import re
from typing import List, Optional

from pydantic import BaseModel, Field

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

MAX_SAMPLES = 80


def rule_matches(match_field, match_type, pattern, merchant, description):
    """Shared matcher (mirrors revolut.injection.rule._matches_values) so proposed
    rules preview their coverage before they exist."""
    if match_field == 'merchant':
        hay = merchant or ''
    elif match_field == 'description':
        hay = description or ''
    else:
        hay = f"{merchant or ''} {description or ''}"
    hay = hay.lower()
    pat = (pattern or '').strip()
    if not pat:
        return False
    if match_type == 'regex':
        try:
            return bool(re.search(pat, hay, re.IGNORECASE))
        except re.error:
            return False
    tokens = [t.strip().lower() for t in pat.split('|') if t.strip()]
    if match_type == 'equals':
        return hay in tokens
    return any(t in hay for t in tokens)


# ── Structured AI output ─────────────────────────────────────────────────────
class ProposedRule(BaseModel):
    name: str = Field(description="Short rule name, e.g. 'AI Tools & APIs'.")
    match_field: str = Field(description="One of: merchant, description, both.")
    match_type: str = Field(description="One of: contains, regex, equals.")
    pattern: str = Field(
        description="For contains/equals: lowercase pipe-separated tokens "
                    "(e.g. 'openai|claude'). For regex: a Python regex.")
    reason: Optional[str] = Field(default=None, description="One-line rationale.")


class ProposedRuleSet(BaseModel):
    rules: List[ProposedRule] = Field(default_factory=list)


SYSTEM_PROMPT = """You generate transaction-routing rules for a bookkeeping tool.
You are given bank-transaction descriptors (merchant and/or description) that the
user wants all routed to a SINGLE GL account, plus that account's name.

Produce a SMALL set of rules that match these transactions and likely future
similar ones, WITHOUT being overly broad:
- match_field: 'merchant' when the merchant identifies it (card payments),
  'description' when the description does (e.g. transfers like 'To PE NAME'),
  'both' if unsure.
- match_type: prefer 'contains' with normalized lowercase tokens; use 'regex'
  only when a structural pattern is clearer (e.g. '^to pe ').
- pattern: for contains/equals, a pipe-separated list of distinctive lowercase
  tokens (e.g. 'hetzner|digitalocean'). Group similar merchants into one rule.
  Avoid generic words (payment, ltd, inc, the, transfer).
- Keep rule names short and human. Return as few rules as cover the set well.
Return ONLY the structured rules."""


class RevolutRuleSuggestWizard(models.TransientModel):
    _name = 'revolut.rule.suggest.wizard'
    _description = 'Suggest Injection Rules (AI)'

    state = fields.Selection(
        [('select', 'Select'), ('review', 'Review')], default='select', required=True)
    transaction_ids = fields.Many2many(
        'revolut.transaction', string='Selected Transactions')
    transaction_count = fields.Integer(compute='_compute_transaction_count')
    account_id = fields.Many2one(
        'account.account', string='Route these to GL Account', required=True,
        domain="[('deprecated', '=', False)]",
        help='All proposed rules will route the selected transactions to this account.')
    line_ids = fields.One2many('revolut.rule.suggest.line', 'wizard_id')

    @api.depends('transaction_ids')
    def _compute_transaction_count(self):
        for wiz in self:
            wiz.transaction_count = len(wiz.transaction_ids)

    # ── OpenAI credentials (company key, fall back to this module's config) ──────
    def _get_openai_credentials(self):
        company = self.env.company
        api_key = (company.openai_api_key or '').strip()
        model = (company.openai_model or '').strip()
        if not api_key:
            cfg = self.env['openai.config'].sudo().search(
                [('company_id', '=', company.id)], limit=1)
            if cfg:
                api_key = (cfg.api_key or '').strip()
                model = model or (cfg.model_name or '')
        return api_key, (model or 'gpt-4o')

    # ── Step 1 → 2: propose ─────────────────────────────────────────────────────
    def action_propose_rules(self):
        self.ensure_one()
        if not self.transaction_ids:
            raise UserError(_("No transactions selected."))
        if not self.account_id:
            raise UserError(_("Choose the GL account to route these to."))

        proposals = self._ai_propose_rules()
        self.line_ids.unlink()
        vals = []
        valid_fields = {'merchant', 'description', 'both'}
        valid_types = {'contains', 'regex', 'equals'}
        for i, r in enumerate(proposals):
            mf = (r.get('match_field') or 'merchant').lower()
            mt = (r.get('match_type') or 'contains').lower()
            pattern = (r.get('pattern') or '').strip()
            if not pattern:
                continue
            vals.append((0, 0, {
                'sequence': (i + 1) * 10,
                'name': (r.get('name') or 'Rule')[:64],
                'match_field': mf if mf in valid_fields else 'merchant',
                'match_type': mt if mt in valid_types else 'contains',
                'pattern': pattern,
                'account_id': self.account_id.id,
                'reason': (r.get('reason') or '')[:200],
            }))
        if not vals:
            raise UserError(_("The AI did not return any usable rule. Try selecting "
                              "more representative transactions."))
        self.write({'line_ids': vals, 'state': 'review'})
        return self._reload()

    def _ai_propose_rules(self):
        """Call OpenAI; return a list of plain dicts. Falls back to a single
        deterministic 'merchant contains <distinct merchants>' rule on any failure."""
        descriptors, seen = [], set()
        for tx in self.transaction_ids:
            key = ((tx.merchant_name or '').strip(), (tx.description or '').strip())
            if key in seen:
                continue
            seen.add(key)
            descriptors.append({
                'merchant': key[0], 'description': key[1],
                'type': tx.transaction_type or ''})
            if len(descriptors) >= MAX_SAMPLES:
                break

        api_key, model = self._get_openai_credentials()
        if not api_key:
            raise UserError(_(
                "OpenAI API key is not configured. Set it on the company "
                "(Settings → Accounting) or in this module's OpenAI Config."))
        try:
            import openai
        except ImportError:
            raise UserError(_("The 'openai' Python package is not installed."))

        _logger.warning("OPENAI DIGITIZATION: proposing injection rules for %s txns → %s",
                        len(descriptors), self.account_id.display_name)
        try:
            client = openai.OpenAI(api_key=api_key)
            response = client.responses.parse(
                model=model,
                input=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps({
                        "target_account": self.account_id.display_name,
                        "transactions": descriptors,
                    })},
                ],
                text_format=ProposedRuleSet,
            )
            result = getattr(response, 'output_parsed', None) or getattr(response, 'parsed', None)
            if result and result.rules:
                return [r.model_dump() for r in result.rules]
        except Exception:  # noqa: BLE001
            _logger.exception("Rule suggestion failed; using deterministic fallback")

        # Fallback — one rule from the distinct merchants (or descriptions).
        merchants = sorted({d['merchant'].lower() for d in descriptors if d['merchant']})
        if merchants:
            return [{'name': self.account_id.name or 'Routing rule',
                     'match_field': 'merchant', 'match_type': 'contains',
                     'pattern': '|'.join(merchants[:30]), 'reason': 'Distinct merchants'}]
        descs = sorted({d['description'].lower() for d in descriptors if d['description']})
        return [{'name': self.account_id.name or 'Routing rule',
                 'match_field': 'description', 'match_type': 'contains',
                 'pattern': '|'.join(descs[:30]), 'reason': 'Distinct descriptions'}]

    # ── Step 2: create the real rules ───────────────────────────────────────────
    def action_create_rules(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("No proposed rules to create."))
        Rule = self.env['revolut.injection.rule']
        base = Rule.search([('company_id', '=', self.env.company.id)], order='sequence desc', limit=1)
        seq = (base.sequence + 10) if base else 10
        created = self.env['revolut.injection.rule']
        for line in self.line_ids:
            created |= Rule.create({
                'company_id': self.env.company.id,
                'sequence': seq,
                'name': line.name,
                'match_field': line.match_field,
                'match_type': line.match_type,
                'pattern': line.pattern,
                'account_id': line.account_id.id,
            })
            seq += 10
        return {
            'type': 'ir.actions.act_window',
            'name': _('Injection Rules'),
            'res_model': 'revolut.injection.rule',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', created.ids)],
        }

    def action_back(self):
        self.ensure_one()
        self.state = 'select'
        return self._reload()

    def _reload(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }
