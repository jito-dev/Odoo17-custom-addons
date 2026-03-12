import base64
import csv
import io

from odoo import models


class HpcSalaryRunRevolut(models.Model):
    _inherit = 'hr.payroll.contractor.salary.run'

    def action_export_revolut_csv(self):
        headers = [
            'Name', 'Recipient type', 'IBAN', 'BIC',
            'Recipient bank country', 'Currency', 'Amount',
            'Payment reference', 'Recipient country',
            'Address line 1', 'Address line 2', 'City', 'Postal code',
        ]
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(headers)

        for run in self:
            contract = run.contract_id
            inv_field = run._fields.get('contractor_invoice_ids')
            inv = run.contractor_invoice_ids[:1] if inv_field else None
            inv_uid = (inv.invoice_uid if inv and inv.invoice_uid else None) or run.reference
            inv_date = run.date_end.strftime('%d %B %Y') if run.date_end else ''
            payment_ref = 'Payment for invoice %s from %s' % (inv_uid, inv_date)
            writer.writerow([
                contract.revolut_recipient_name or '',
                'COMPANY',
                contract.revolut_iban or '',
                contract.revolut_bic or '',
                contract.revolut_bank_country_id.code or '',
                run.currency_id.name or '',
                '%.2f' % (run.total_to_pay or 0.0),
                payment_ref,
                contract.revolut_recipient_country_id.code or '',
                contract.revolut_address_line1 or '',
                contract.revolut_address_line2 or '',
                contract.revolut_city or '',
                contract.revolut_postal_code or '',
            ])

        csv_bytes = buf.getvalue().encode('utf-8')
        att = self.env['ir.attachment'].create({
            'name': 'revolut_batch_payment.csv',
            'datas': base64.b64encode(csv_bytes),
            'mimetype': 'text/csv',
            'res_model': self._name,
            'res_id': self.ids[0] if self.ids else False,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % att.id,
            'target': 'self',
        }
