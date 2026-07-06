from odoo import api, fields, models

from .revolut_rule_suggest_wizard import rule_matches


class RevolutRuleSuggestLine(models.TransientModel):
    _name = 'revolut.rule.suggest.line'
    _description = 'AI-proposed injection rule (for review)'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'revolut.rule.suggest.wizard', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    match_field = fields.Selection(
        [('merchant', 'Merchant'), ('description', 'Description'), ('both', 'Either')],
        default='merchant', required=True)
    match_type = fields.Selection(
        [('contains', 'contains'), ('regex', 'regex'), ('equals', 'equals')],
        default='contains', required=True)
    pattern = fields.Char(required=True)
    account_id = fields.Many2one('account.account', string='GL Account', required=True)
    reason = fields.Char(string='Why')
    covered = fields.Integer(
        string='Covers', compute='_compute_covered',
        help='How many of the selected transactions this rule matches.')

    @api.depends('match_field', 'match_type', 'pattern',
                 'wizard_id.transaction_ids')
    def _compute_covered(self):
        for line in self:
            txns = line.wizard_id.transaction_ids
            line.covered = sum(
                1 for tx in txns
                if rule_matches(line.match_field, line.match_type, line.pattern,
                                tx.merchant_name, tx.description))
