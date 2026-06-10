from odoo import fields, models


class ResUsersHpcExt(models.Model):
    """Per-user document signature image, shown on the My Profile page."""
    _inherit = 'res.users'

    hpc_signature_img = fields.Binary(
        string='Document Signature',
        attachment=True,
        help='Signature image used in generated documents (contracts, invoices).',
    )
    hpc_signature_img_filename = fields.Char()
