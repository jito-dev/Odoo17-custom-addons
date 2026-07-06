from odoo import fields, models


class RevolutBillMatchLine(models.TransientModel):
    _name = 'revolut.bill.match.line'
    _description = 'Uploaded bill ↔ transaction match proposal'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'revolut.bill.match.wizard', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    attachment_id = fields.Many2one('ir.attachment', required=True, ondelete='cascade')
    bill_name = fields.Char(string='Bill')

    # ── AI-extracted data ────────────────────────────────────────────────────
    extracted_vendor = fields.Char(string='Vendor')
    extracted_amount = fields.Float(string='Amount', digits=(16, 2))
    extracted_currency = fields.Char(string='Currency')
    extracted_date = fields.Date(string='Invoice Date')
    extracted_invoice_number = fields.Char(string='Invoice #')
    extract_error = fields.Char(string='Extraction Error')

    # ── Proposed match ───────────────────────────────────────────────────────
    proposed_transaction_id = fields.Many2one(
        'revolut.transaction', string='Matched Transaction')
    confidence = fields.Selection(
        [('high', 'High'), ('medium', 'Medium'), ('low', 'Low'), ('none', 'No match')],
        default='none')
    match_reasons = fields.Text(string='Why this match')

    status = fields.Selection(
        [('pending', 'Pending'), ('attached', 'Attached'), ('skipped', 'Skipped')],
        default='pending', required=True)
