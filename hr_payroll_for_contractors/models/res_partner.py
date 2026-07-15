from odoo import _, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # Provenance of an auto-generated contractor vendor (which legal entity + payment
    # method it was built from) is recorded as a chatter note on the partner in
    # hpc_contract_extension._ensure_payroll_vendor — NOT as stored columns, so the
    # module never requires a schema upgrade (-u) to keep res.partner reads working.

    def action_clear_unused_vendor_flag(self):
        """Un-mark the selected partners as vendors (supplier_rank = 0) ONLY when
        they have no accounting history (no journal items) — so they drop out of the
        Vendor lists/dropdowns without deleting the contact or touching its links.
        Partners that are actually used (any move line) or aren't vendors are skipped."""
        AML = self.env['account.move.line'].sudo()
        cleared = skipped = 0
        for partner in self:
            if partner.supplier_rank <= 0:
                skipped += 1
                continue
            if AML.search_count([('partner_id', '=', partner.id)]):
                skipped += 1  # has accounting history → leave it
                continue
            partner.sudo().write({'supplier_rank': 0})
            cleared += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Clear Vendor Flag'),
                'message': _('%s partner(s) un-marked as vendor, %s skipped '
                             '(used in accounting, or not a vendor).', cleared, skipped),
                'type': 'success',
                'sticky': False,
            },
        }
