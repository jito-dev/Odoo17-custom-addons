from odoo import fields, models

# Fields this module adds to the My Profile (res.users preferences) form.
_HPC_USER_FIELDS = ['hpc_signature_img', 'hpc_signature_img_filename']


class ResUsersHpcExt(models.Model):
    """Per-user document signature image, shown on the My Profile page."""
    _inherit = 'res.users'

    hpc_signature_img = fields.Binary(
        string='Document Signature',
        attachment=True,
        help='Signature image used in generated documents (contracts, invoices).',
    )
    hpc_signature_img_filename = fields.Char()

    # These fields are shown on the My Profile (preferences) form. Odoo only
    # reads a user's own record under sudo when EVERY field on that form is in
    # SELF_READABLE_FIELDS (see res.users.read); a single unlisted field forces
    # a non-sudo read, which then raises AccessError on the officer-only HR
    # fields (birthday, ssnid, …) for any non-HR-Officer user. Registering our
    # own fields here keeps the self-read fast-path intact — they are the user's
    # own signature, legitimately self-readable/writeable.
    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + _HPC_USER_FIELDS

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + _HPC_USER_FIELDS
