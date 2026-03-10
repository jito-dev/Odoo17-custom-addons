from odoo import fields, models


class ResCompanyHpcExt(models.Model):
    """Contractor document fields for the company — used when building
    Jinja2 context for legal relationships and contractor invoices."""
    _inherit = 'res.company'

    # ── Representative ─────────────────────────────────────────────────────────
    hpc_representative_id = fields.Many2one(
        'res.partner',
        string='Authorized Representative',
        domain=[('is_company', '=', False)],
        help='Contact person used as the authorized signatory in generated documents.',
        ondelete='set null',
    )
    hpc_representative_name_ua = fields.Char(
        string='Representative Name (UA)',
        help='Ukrainian name of the signatory (leave blank to use the contact name).',
    )

    # ── Ukrainian identity ─────────────────────────────────────────────────────
    hpc_legal_name_ua = fields.Char(
        string='Legal Name (UA)',
        help='Company legal name in Ukrainian.',
    )

    # ── Shared ─────────────────────────────────────────────────────────────────
    hpc_pay_duration = fields.Integer(
        string='Payment Duration (days)',
        default=10,
        help='Number of calendar days for invoice payment (used in contracts).',
    )
