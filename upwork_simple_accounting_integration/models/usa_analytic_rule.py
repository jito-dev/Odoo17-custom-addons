from odoo import api, fields, models

# Selection key → real usa.transaction field used for matching.
_MATCH_FIELDS = {
    'freelancer': 'assignment_developer_name',
    'client': 'assignment_company_name',
    'agency': 'assignment_agency_name',
    'team': 'assignment_team_reference',
    'subtype': 'accounting_subtype',
    'tx_type': 'transaction_type',
}


class UsaAnalyticRule(models.Model):
    """A simple rule that assigns an analytic account to Upwork moves based on a
    field of the source transaction.

    Example: match_field=freelancer, operator='=', value='Polina Rudenko',
    plan=Department, account=UX/UI Design → every move built from that person's
    transactions (service invoice, service-fee bill, refund credit note, and the
    wallet line) is tagged Department=UX/UI Design.

    Evaluated by account.move._usa_apply_analytics on post and on "Re-apply
    Analytic Tags". First active rule per plan (by sequence) wins. Rows with no
    value for the matched field (e.g. connects/membership/withdrawal fees have no
    freelancer) simply don't match — so they stay un-departmental.
    """

    _name = 'usa.analytic.rule'
    _description = 'Upwork Analytic Tagging Rule'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', string='Company', default=lambda self: self.env.company)

    plan_id = fields.Many2one(
        'account.analytic.plan', string='Analytic Plan', required=True, ondelete='cascade')
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Analytic Account', required=True,
        ondelete='cascade', domain="[('plan_id', '=', plan_id)]")

    match_field = fields.Selection(
        selection=[
            ('freelancer', 'Freelancer'),
            ('client', 'Client Company'),
            ('agency', 'Agency'),
            ('team', 'Team Reference'),
            ('subtype', 'Accounting Subtype'),
            ('tx_type', 'Transaction Type'),
        ],
        string='Match Field', required=True, default='freelancer',
        help='Transaction field this rule matches on.')
    match_operator = fields.Selection(
        selection=[('=', 'equals'), ('ilike', 'contains')],
        string='Operator', required=True, default='=')
    match_value = fields.Char(string='Match Value', required=True)

    display_name = fields.Char(compute='_compute_display_name')

    @api.depends('match_field', 'match_operator', 'match_value', 'plan_id', 'analytic_account_id')
    def _compute_display_name(self):
        labels = dict(self._fields['match_field'].selection)
        for rule in self:
            rule.display_name = '%s %s "%s" → %s / %s' % (
                labels.get(rule.match_field, rule.match_field or ''),
                rule.match_operator or '',
                rule.match_value or '',
                rule.plan_id.name or '',
                rule.analytic_account_id.name or '',
            )

    def _field_name(self):
        """Real usa.transaction field for this rule's match_field."""
        self.ensure_one()
        return _MATCH_FIELDS.get(self.match_field)

    def _matches(self, tx):
        """True if the (single) transaction satisfies this rule."""
        self.ensure_one()
        field = self._field_name()
        if not field or not self.match_value:
            return False
        return bool(tx.filtered_domain([(field, self.match_operator, self.match_value)]))
