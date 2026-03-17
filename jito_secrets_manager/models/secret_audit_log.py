from odoo import api, fields, models


class SecretAuditLog(models.Model):
    """
    Append-only audit log. No write or unlink granted to anyone via ACL.
    All entries are created via sudo() in model methods.
    """
    _name = 'secret.audit.log'
    _description = 'Secret Audit Log'
    _order = 'timestamp desc'

    secret_id = fields.Many2one(
        'secret.entry',
        string='Secret',
        ondelete='set null',
        readonly=True,
        index=True,
    )
    secret_name = fields.Char(
        string='Secret Name',
        readonly=True,
        help='Snapshot of the secret name at the time of the action.',
    )
    user_id = fields.Many2one(
        'res.users',
        string='User',
        readonly=True,
        default=lambda self: self.env.uid,
        index=True,
    )
    action = fields.Selection(
        selection=[
            ('create', 'Created'),
            ('reveal', 'Revealed'),
            ('edit', 'Edited'),
            ('delete', 'Deleted'),
            ('share', 'Shared'),
            ('unseal', 'Vault Unsealed'),
            ('seal', 'Vault Sealed'),
        ],
        string='Action',
        required=True,
        readonly=True,
    )
    timestamp = fields.Datetime(
        string='Timestamp',
        default=fields.Datetime.now,
        readonly=True,
    )

    @api.model
    def _log(self, secret, action: str):
        """Create an audit log entry. Always call with sudo()."""
        vals = {
            'action': action,
            'user_id': self.env.uid,
            'timestamp': fields.Datetime.now(),
        }
        if secret:
            vals['secret_id'] = secret.id
            vals['secret_name'] = secret.name
        self.sudo().create(vals)
