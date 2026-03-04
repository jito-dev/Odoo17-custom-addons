import base64
import csv
import io

from odoo import api, fields, models


class HpcRevolutExportWizard(models.TransientModel):
    _name = 'hpc.revolut.export.wizard'
    _description = 'Export Salary Runs for Revolut Batch Payment'

    salary_run_ids = fields.Many2many(
        'hr.payroll.contractor.salary.run',
        'hpc_revolut_export_wizard_run_rel',
        'wizard_id',
        'run_id',
        string='Salary Runs',
    )
    export_file = fields.Binary(string='CSV File', readonly=True)
    export_filename = fields.Char(
        readonly=True, default='revolut_batch_payment.csv')

    @api.model_create_multi
    def create(self, vals_list):
        wizards = super().create(vals_list)
        for wizard in wizards:
            wizard._generate_csv()
        return wizards

    def _generate_csv(self):
        self.ensure_one()
        # Flush pending writes so the Many2many relation is readable
        self.env.flush_all()
        headers = [
            'Name',
            'Recipient type',
            'IBAN',
            'BIC',
            'Recipient bank country',
            'Currency',
            'Amount',
            'Payment reference',
            'Recipient country',
            'Address line 1',
            'Address line 2',
            'City',
            'Postal code',
        ]
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(headers)
        for run in self.salary_run_ids:
            contract = run.contract_id
            writer.writerow([
                contract.revolut_recipient_name or '',
                'COMPANY',
                contract.revolut_iban or '',
                contract.revolut_bic or '',
                contract.revolut_bank_country_id.code or '',
                run.currency_id.name or '',
                '%.2f' % (run.total_to_pay or 0.0),
                'Payment for Software Development Work',
                contract.revolut_recipient_country_id.code or '',
                contract.revolut_address_line1 or '',
                contract.revolut_address_line2 or '',
                contract.revolut_city or '',
                contract.revolut_postal_code or '',
            ])
        csv_bytes = buf.getvalue().encode('utf-8')
        self.export_file = base64.b64encode(csv_bytes)
