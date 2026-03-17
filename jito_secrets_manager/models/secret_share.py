from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SecretShare(models.Model):
    _name = 'secret.share'
    _description = 'Secret Share'
    _order = 'expires_at'

    secret_id = fields.Many2one(
        'secret.entry',
        string='Secret',
        required=True,
        ondelete='cascade',
        index=True,
    )
    shared_with_user_id = fields.Many2one(
        'res.users',
        string='Shared With',
        required=True,
        domain="[('id', '!=', uid)]",
    )
    shared_by_user_id = fields.Many2one(
        'res.users',
        string='Shared By',
        required=True,
        default=lambda self: self.env.uid,
        readonly=True,
    )
    expires_at = fields.Datetime(
        string='Expires At',
        required=True,
        help='The share will stop working after this date/time.',
    )
    is_expired = fields.Boolean(
        string='Expired',
        compute='_compute_is_expired',
        store=False,
    )

    _sql_constraints = [
        (
            'unique_share',
            'unique(secret_id, shared_with_user_id)',
            'This secret is already shared with that user.',
        ),
    ]

    @api.depends('expires_at')
    def _compute_is_expired(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.is_expired = bool(rec.expires_at and rec.expires_at <= now)

    @api.constrains('shared_with_user_id', 'secret_id')
    def _check_not_own_secret(self):
        for rec in self:
            if rec.secret_id.user_id == rec.shared_with_user_id:
                raise ValidationError(_(
                    'You cannot share a secret with its owner.'
                ))

    @api.constrains('secret_id')
    def _check_share_ownership(self):
        for rec in self:
            if not self.env.user.has_group('jito_secrets_manager.group_secrets_admin'):
                if rec.secret_id.user_id.id != self.env.uid:
                    raise ValidationError(_(
                        'You can only share secrets you own.'
                    ))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            self.env['secret.audit.log'].sudo()._log(rec.secret_id, 'share')
        return records

    def unlink(self):
        for rec in self:
            self.env['secret.audit.log'].sudo()._log(rec.secret_id, 'unshare')
        return super().unlink()
