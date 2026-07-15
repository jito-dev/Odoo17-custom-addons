import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class RevolutInvoiceLinkWizard(models.TransientModel):
    _name = 'revolut.invoice.link.wizard'
    _description = 'Match & attach existing customer invoices to Revolut transactions'

    transaction_ids = fields.Many2many('revolut.transaction', string='Transactions')
    line_ids = fields.One2many('revolut.invoice.link.line', 'wizard_id')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        tx_ids = self._resolve_default_transaction_ids()
        txs = self.env['revolut.transaction'].browse(tx_ids)
        lines = []
        for tx in txs:
            inv, conf, reason = tx._find_matching_invoice()
            lines.append((0, 0, {
                'transaction_id': tx.id,
                'proposed_invoice_id': inv.id if inv else False,
                'confidence': conf,
                'match_reason': reason,
                'do_attach': bool(inv),
            }))
        res['transaction_ids'] = [(6, 0, tx_ids)]
        res['line_ids'] = lines
        return res

    def _resolve_default_transaction_ids(self):
        cmd = self.env.context.get('default_transaction_ids') or []
        for c in cmd:
            if isinstance(c, (list, tuple)) and len(c) == 3 and c[0] == 6:
                return list(c[2])
        # Fallback: launched from the list action context.
        if self.env.context.get('active_model') == 'revolut.transaction':
            return self.env.context.get('active_ids') or []
        return []

    def action_attach(self):
        """Link each confirmed customer invoice to its transaction (store the
        reference, not a copy). Linking only — reconcile separately."""
        self.ensure_one()
        linked = skipped = 0
        for line in self.line_ids:
            tx = line.transaction_id
            inv = line.proposed_invoice_id
            if not line.do_attach or not inv:
                skipped += 1
                continue
            tx.customer_invoice_id = inv.id
            linked += 1
            # Surface the invoice's document on the tx (receipt counter + preview)
            # by linking its main attachment, if any.
            main_att = inv.message_main_attachment_id
            if main_att and main_att not in tx.invoice_attachment_ids:
                tx.invoice_attachment_ids = [(4, main_att.id)]
        if not linked:
            raise UserError(_("Nothing to attach — tick 'Attach' on at least one matched line."))
        msg = _('%s invoice(s) attached, %s skipped.') % (linked, skipped)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Match & Attach Customer Invoices'),
                'message': msg,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
