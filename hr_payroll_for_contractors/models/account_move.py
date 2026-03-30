import base64
import csv
import io
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    salary_run_id = fields.Many2one(
        'hr.payroll.contractor.salary.run',
        string='Salary Run',
        copy=False,
        readonly=True,
    )

    def unlink(self):
        # Find linked salary runs BEFORE deletion (invoice_id still set)
        SalaryRun = self.env['hr.payroll.contractor.salary.run']
        linked_runs = SalaryRun.sudo().search([('invoice_id', 'in', self.ids)])

        result = super().unlink()
        # Odoo ORM auto-nulls invoice_id via SET NULL (bypasses write())
        # Revert state back to approved_and_locked
        if linked_runs:
            try:
                linked_runs.sudo().write({'state': 'approved_and_locked'})
            except Exception as e:
                _logger.error('Failed to revert salary run state after bill deletion: %s', e)
        return result

    # ── Revolut CSV Export ────────────────────────────────────────────────────

    def action_export_revolut_csv(self):
        """Export selected vendor bills as Revolut Business batch payment CSV.

        For bills linked to a salary run, uses the same contract-based Revolut
        fields as the salary run export. For bills without a salary run link,
        maps from the bill's partner and bank account data.
        """
        headers = [
            'Name', 'Recipient type', 'IBAN', 'BIC',
            'Recipient bank country', 'Currency', 'Amount',
            'Payment reference', 'Recipient country',
            'Address line 1', 'Address line 2', 'City', 'Postal code',
        ]
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(headers)

        for bill in self:
            if bill.salary_run_id:
                row = self._revolut_row_from_salary_run(bill)
            else:
                row = self._revolut_row_from_bill(bill)
            writer.writerow(row)

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

    def _revolut_row_from_salary_run(self, bill):
        """Build CSV row using salary run's contract Revolut fields,
        falling back to service agreement payment method for missing values."""
        run = bill.salary_run_id
        contract = run.contract_id

        # Service agreement payment method as fallback
        sa = contract.service_agreement_id if contract else False
        pm = sa.payment_method_id if sa else False

        # Extract BIC and IBAN from payment method by type
        pm_bic = ''
        pm_iban = ''
        pm_bank_country = ''
        if pm:
            if pm.method_type == 'sepa':
                pm_bic = pm.sepa_bic or ''
                pm_iban = pm.sepa_iban or ''
                pm_bank_country = pm.sepa_bank_country_id.code if pm.sepa_bank_country_id else ''
            elif pm.method_type == 'swift':
                pm_bic = pm.swift_bic or ''
                pm_iban = pm.swift_account_number or ''
                pm_bank_country = pm.swift_bank_country_id.code if pm.swift_bank_country_id else ''

        inv_field = run._fields.get('contractor_invoice_ids')
        inv = run.contractor_invoice_ids[:1] if inv_field else None
        inv_uid = (inv.invoice_uid if inv and inv.invoice_uid else None) or run.reference
        inv_date = run.date_end.strftime('%d %B %Y') if run.date_end else ''
        payment_ref = 'Payment for invoice %s from %s' % (inv_uid, inv_date)

        return [
            contract.revolut_recipient_name or '',
            'COMPANY',
            contract.revolut_iban or pm_iban,
            contract.revolut_bic or pm_bic,
            contract.revolut_bank_country_id.code or pm_bank_country or '',
            run.currency_id.name or '',
            '%.2f' % (run.total_to_pay or 0.0),
            payment_ref,
            contract.revolut_recipient_country_id.code or '',
            contract.revolut_address_line1 or '',
            contract.revolut_address_line2 or '',
            contract.revolut_city or '',
            contract.revolut_postal_code or '',
        ]

    def _revolut_row_from_bill(self, bill):
        """Build CSV row from vendor bill's own partner and bank data."""
        partner = bill.partner_id
        bank = partner.bank_ids[:1] if partner else self.env['res.partner.bank']

        payment_ref = bill.payment_reference or bill.ref or ''
        bank_country = (
            bank.bank_id.country.code if bank and bank.bank_id and bank.bank_id.country
            else (partner.country_id.code if partner and partner.country_id else '')
        )

        return [
            partner.name or '',
            'COMPANY',
            bank.acc_number or '' if bank else '',
            bank.bank_bic or '' if bank else '',
            bank_country,
            bill.currency_id.name or '',
            '%.2f' % (bill.amount_total or 0.0),
            payment_ref,
            partner.country_id.code if partner and partner.country_id else '',
            partner.street or '' if partner else '',
            partner.street2 or '' if partner else '',
            partner.city or '' if partner else '',
            partner.zip or '' if partner else '',
        ]
