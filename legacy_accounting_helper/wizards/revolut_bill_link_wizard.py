import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class RevolutBillLinkWizard(models.TransientModel):
    _name = 'revolut.bill.link.wizard'
    _description = 'Match & attach existing vendor bills to Revolut transactions'

    transaction_ids = fields.Many2many('revolut.transaction', string='Transactions')
    line_ids = fields.One2many('revolut.bill.link.line', 'wizard_id')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        tx_ids = self._resolve_default_transaction_ids()
        txs = self.env['revolut.transaction'].browse(tx_ids)
        lines = []
        for tx in txs:
            bill, conf, reason = tx._find_matching_bill()
            lines.append((0, 0, {
                'transaction_id': tx.id,
                'proposed_bill_id': bill.id if bill else False,
                'confidence': conf,
                'match_reason': reason,
                'do_attach': bool(bill),
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
        """Link each confirmed bill to its transaction (store the reference, not a
        copy). Linking only — reconcile separately via 'Reconcile injected bill &
        tx'."""
        self.ensure_one()
        linked = skipped = 0
        for line in self.line_ids:
            tx = line.transaction_id
            bill = line.proposed_bill_id
            if not line.do_attach or not bill:
                skipped += 1
                continue
            tx.vendor_bill_id = bill.id
            linked += 1
            # Surface the bill's document as a receipt on the tx (counter ++ +
            # preview) by linking its main attachment, if any.
            main_att = bill.message_main_attachment_id
            if main_att and main_att not in tx.invoice_attachment_ids:
                tx.invoice_attachment_ids = [(4, main_att.id)]
        if not linked:
            raise UserError(_("Nothing to attach — tick 'Attach' on at least one matched line."))
        msg = _('%s bill(s) attached, %s skipped. Reconcile via '
                '"Reconcile injected bill & tx".') % (linked, skipped)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Match & Attach Vendor Bills'),
                'message': msg,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
