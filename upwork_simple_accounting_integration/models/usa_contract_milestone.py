from odoo import fields, models


class UsaContractMilestone(models.Model):
    """Milestone from a fixed-price Upwork contract (contractDetails.terms.fixedPriceTerms.milestones)."""

    _name = 'usa.contract.milestone'
    _description = 'Upwork Contract Milestone'
    _rec_name = 'description'
    _order = 'sequence_id asc'

    contract_detail_id = fields.Many2one(
        'usa.contract.detail', string='Contract', required=True, ondelete='cascade', index=True)

    # ── Identity ──────────────────────────────────────────────────────────────

    milestone_id = fields.Char(string='Milestone ID', readonly=True)
    sequence_id = fields.Integer(string='Sequence', readonly=True)
    state = fields.Char(string='State', readonly=True)
    description = fields.Text(string='Description', readonly=True)
    instructions = fields.Text(string='Instructions', readonly=True)
    pay_comments = fields.Text(string='Pay Comments', readonly=True)

    # ── Dates ─────────────────────────────────────────────────────────────────

    due_date_time = fields.Datetime(string='Due Date', readonly=True)
    created_datetime = fields.Datetime(string='Created', readonly=True)
    modified_datetime = fields.Datetime(string='Modified', readonly=True)

    # ── Counts ────────────────────────────────────────────────────────────────

    submission_count = fields.Integer(string='Submissions', readonly=True)

    # ── Money ─────────────────────────────────────────────────────────────────

    escrow_raw = fields.Float(string='Escrow', digits=(8, 2), readonly=True)
    escrow_currency = fields.Char(string='Escrow Currency', readonly=True)

    deposit_raw = fields.Float(string='Deposit', digits=(8, 2), readonly=True)
    deposit_currency = fields.Char(string='Deposit Currency', readonly=True)

    funded_raw = fields.Float(string='Funded', digits=(8, 2), readonly=True)
    funded_currency = fields.Char(string='Funded Currency', readonly=True)

    paid_raw = fields.Float(string='Paid', digits=(8, 2), readonly=True)
    paid_currency = fields.Char(string='Paid Currency', readonly=True)

    overpayment_raw = fields.Float(string='Overpayment', digits=(8, 2), readonly=True)
    overpayment_currency = fields.Char(string='Overpayment Currency', readonly=True)

    bonus_raw = fields.Float(string='Bonus', digits=(8, 2), readonly=True)
    bonus_currency = fields.Char(string='Bonus Currency', readonly=True)
