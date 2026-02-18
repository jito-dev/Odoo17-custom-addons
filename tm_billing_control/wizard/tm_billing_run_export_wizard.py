# -*- coding: utf-8 -*-

import io
import base64
from datetime import datetime
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.misc import xlsxwriter


class TmBillingRunExportWizard(models.TransientModel):
    """
    Wizard for exporting billing run timesheets to Excel/CSV

    Provides three-step workflow:
    1. Choose formats (Excel, CSV)
    2. Preview export data
    3. Download generated files
    """

    _name = 'tm.billing.run.export.wizard'
    _description = 'Billing Run Export Wizard'

    # ========================================================================
    # FIELDS
    # ========================================================================

    # Parent billing run
    billing_run_id = fields.Many2one(
        comodel_name='tm.billing.run',
        string='Billing Run',
        required=True,
        ondelete='cascade',
    )

    # Preview data
    preview_data = fields.Html(
        string='Preview',
        compute='_compute_preview_data',
        sanitize=False,
        help="Preview of export data",
    )

    # Statistics
    timesheet_count = fields.Integer(
        string='Timesheet Count',
        compute='_compute_preview_data',
    )

    total_hours = fields.Float(
        string='Total Hours',
        compute='_compute_preview_data',
    )

    total_amount = fields.Monetary(
        string='Total Amount',
        compute='_compute_preview_data',
        currency_field='currency_id',
    )

    # Export file field (computed on-demand)
    export_file = fields.Binary(
        string='Export File',
        compute='_compute_export_file',
    )

    export_filename = fields.Char(
        string='Export Filename',
        compute='_compute_export_file',
    )

    # Related fields from billing run (for display)
    client_id = fields.Many2one(
        related='billing_run_id.client_id',
        string='Client',
        readonly=True,
    )

    date_start = fields.Date(
        related='billing_run_id.date_start',
        string='Period Start',
        readonly=True,
    )

    date_end = fields.Date(
        related='billing_run_id.date_end',
        string='Period End',
        readonly=True,
    )

    total_hours = fields.Float(
        related='billing_run_id.total_hours',
        string='Total Hours',
        readonly=True,
    )

    total_amount = fields.Monetary(
        related='billing_run_id.total_amount',
        string='Total Amount',
        readonly=True,
    )

    currency_id = fields.Many2one(
        related='billing_run_id.currency_id',
        string='Currency',
        readonly=True,
    )

    # ========================================================================
    # COMPUTED FIELDS
    # ========================================================================

    @api.depends('billing_run_id')
    def _compute_preview_data(self):
        """Compute preview data on wizard load"""
        for wizard in self:
            if not wizard.billing_run_id:
                wizard.preview_data = ''
                wizard.timesheet_count = 0
                wizard.total_hours = 0.0
                wizard.total_amount = 0.0
                continue

            # Get export data
            data = wizard._get_export_data()

            if not data:
                wizard.preview_data = '<div class="alert alert-warning">No included timesheets to export.</div>'
                wizard.timesheet_count = 0
                wizard.total_hours = 0.0
                wizard.total_amount = 0.0
                continue

            # Calculate statistics
            wizard.timesheet_count = len(data)
            wizard.total_hours = sum(record['hours'] for record in data)
            wizard.total_amount = sum(record['amount'] for record in data)

            # Generate preview HTML
            wizard.preview_data = wizard._generate_preview_html(data)

    @api.depends('billing_run_id')
    def _compute_export_file(self):
        """Compute export file on-demand (used by download action)"""
        for wizard in self:
            # This will be computed when accessed via download URL
            wizard.export_file = False
            wizard.export_filename = False

    # ========================================================================
    # ACTIONS
    # ========================================================================

    def action_export_csv(self):
        """Generate and download CSV export"""
        self.ensure_one()

        # Get export data
        data = self._get_export_data()

        if not data:
            raise UserError(_("No timesheet data to export"))

        # Generate CSV
        csv_data = self._generate_csv_file(data)

        # Generate filename
        filename = self._get_base_filename() + '.csv'

        # Create attachment
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'datas': csv_data,
            'res_model': 'tm.billing.run',
            'res_id': self.billing_run_id.id,
            'mimetype': 'text/csv',
        })

        # Return download action
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def action_export_pdf(self):
        """Open timesheet list view with Print button"""
        self.ensure_one()

        # Get all included timesheet IDs from billing run
        timesheet_ids = []
        for line in self.billing_run_id.line_ids:
            for ts_link in line.timesheet_line_ids.filtered(lambda tl: tl.included):
                timesheet_ids.append(ts_link.timesheet_id.id)

        if not timesheet_ids:
            raise UserError(_("No timesheets to export"))

        # Get custom tree view
        tree_view_id = self.env.ref('tm_billing_control.view_account_analytic_line_export_tree').id

        # Open timesheet list view with custom columns
        return {
            'name': _('Timesheets - %s') % self.billing_run_id.reference,
            'type': 'ir.actions.act_window',
            'res_model': 'account.analytic.line',
            'view_mode': 'tree,form',
            'views': [(tree_view_id, 'tree'), (False, 'form')],
            'domain': [('id', 'in', timesheet_ids)],
            'context': {
                'default_project_id': False,
                'search_default_groupby_project': 1,
                'search_default_groupby_employee': 1,
            },
            'target': 'current',
        }

    # ========================================================================
    # FILE GENERATION
    # ========================================================================

    def _generate_excel_file(self, data):
        """
        Generate Excel file using xlsxwriter (Odoo standard)

        Args:
            data: list of dicts with export data

        Returns:
            base64 encoded Excel file
        """
        self.ensure_one()

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Timesheets')

        # Define formats
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#D3D3D3',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
        })

        date_format = workbook.add_format({
            'num_format': 'yyyy-mm-dd',
        })

        number_format = workbook.add_format({
            'num_format': '#,##0.00',
        })

        # Write headers
        headers = [
            'Billing Run',
            'Period Start',
            'Period End',
            'Client',
            'Project',
            'Employee',
            'Date',
            'Task',
            'Description',
            'Hours Spent',
            'Adjusted Hours',
            'Rate',
            'Amount',
            'Currency',
            'Product',
            'Sales Order',
            'Invoice',
            'Invoice State',
        ]

        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_format)

        # Set column widths
        worksheet.set_column(0, 0, 15)   # Billing Run
        worksheet.set_column(1, 2, 12)   # Dates
        worksheet.set_column(3, 3, 20)   # Client
        worksheet.set_column(4, 4, 20)   # Project
        worksheet.set_column(5, 5, 20)   # Employee
        worksheet.set_column(6, 6, 12)   # Date
        worksheet.set_column(7, 7, 20)   # Task
        worksheet.set_column(8, 8, 40)   # Description
        worksheet.set_column(9, 12, 12)  # Hours Spent, Adjusted Hours, Rate, Amount
        worksheet.set_column(13, 17, 15) # Rest

        # Write data
        row = 1
        for record in data:
            worksheet.write(row, 0, record['billing_run_ref'])
            worksheet.write(row, 1, record['period_start'], date_format)
            worksheet.write(row, 2, record['period_end'], date_format)
            worksheet.write(row, 3, record['client'])
            worksheet.write(row, 4, record['project'])
            worksheet.write(row, 5, record['employee'])
            worksheet.write(row, 6, record['date'], date_format)
            worksheet.write(row, 7, record['task'])
            worksheet.write(row, 8, record['description'])
            worksheet.write(row, 9, record['hours_spent'], number_format)
            worksheet.write(row, 10, record['hours'], number_format)
            worksheet.write(row, 11, record['rate'], number_format)
            worksheet.write(row, 12, record['amount'], number_format)
            worksheet.write(row, 13, record['currency'])
            worksheet.write(row, 14, record['product'])
            worksheet.write(row, 15, record['sales_order'])
            worksheet.write(row, 16, record['invoice'])
            worksheet.write(row, 17, record['invoice_state'])
            row += 1

        # Freeze header row
        worksheet.freeze_panes(1, 0)

        workbook.close()
        return base64.b64encode(output.getvalue())

    def _generate_csv_file(self, data):
        """
        Generate CSV file with essential columns only

        Args:
            data: list of dicts with export data

        Returns:
            base64 encoded CSV file
        """
        self.ensure_one()

        import csv
        output = io.StringIO()
        writer = csv.writer(output)

        # Write headers (11 essential columns — includes both Hours Spent and Adjusted Hours)
        headers = [
            'Client',
            'Project',
            'Employee',
            'Date',
            'Task',
            'Description',
            'Hours Spent',
            'Adjusted Hours',
            'Rate',
            'Amount',
            'Currency',
        ]
        writer.writerow(headers)

        # Write data
        for record in data:
            writer.writerow([
                record['client'],
                record['project'],
                record['employee'],
                record['date'],
                record['task'],
                record['description'],
                record['hours_spent'],
                record['hours'],
                record['rate'],
                record['amount'],
                record['currency'],
            ])

        return base64.b64encode(output.getvalue().encode('utf-8'))

    def _old_generate_csv_file(self, data):
        """
        Generate print-ready HTML that can be printed to PDF from browser

        Args:
            data: list of dicts with export data
            total_hours: total hours
            total_amount: total amount

        Returns:
            HTML string
        """
        self.ensure_one()

        html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <title>Timesheet Export - {self.billing_run_id.reference}</title>
    <style>
        @media print {{
            body {{ margin: 0; }}
            .no-print {{ display: none; }}
        }}
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            font-size: 10pt;
        }}
        .header {{
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #333;
        }}
        .header h1 {{
            margin: 0 0 10px 0;
            font-size: 20pt;
            color: #333;
        }}
        .info-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-top: 10px;
        }}
        .info-item {{
            margin-bottom: 5px;
        }}
        .info-label {{
            font-weight: bold;
            color: #666;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
            font-size: 9pt;
        }}
        th {{
            background-color: #f0f0f0;
            border: 1px solid #ddd;
            padding: 8px;
            text-align: left;
            font-weight: bold;
        }}
        td {{
            border: 1px solid #ddd;
            padding: 6px;
        }}
        tr:nth-child(even) {{
            background-color: #f9f9f9;
        }}
        .text-right {{
            text-align: right;
        }}
        .total-row {{
            background-color: #e0e0e0 !important;
            font-weight: bold;
        }}
        .print-button {{
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 10px 20px;
            background-color: #007bff;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
        }}
        .print-button:hover {{
            background-color: #0056b3;
        }}
    </style>
</head>
<body>
    <button class="print-button no-print" onclick="window.print()">Print to PDF</button>

    <div class="header">
        <h1>Timesheet Export Report</h1>
        <div class="info-grid">
            <div>
                <div class="info-item">
                    <span class="info-label">Billing Run:</span> {self.billing_run_id.reference}
                </div>
                <div class="info-item">
                    <span class="info-label">Client:</span> {self.billing_run_id.client_id.name}
                </div>
                <div class="info-item">
                    <span class="info-label">Period:</span> {self.billing_run_id.date_start} to {self.billing_run_id.date_end}
                </div>
            </div>
            <div>
                <div class="info-item">
                    <span class="info-label">Total Timesheets:</span> {len(data)}
                </div>
                <div class="info-item">
                    <span class="info-label">Total Hours:</span> {total_hours:.2f}
                </div>
                <div class="info-item">
                    <span class="info-label">Total Amount:</span> {total_amount:.2f} {self.billing_run_id.currency_id.name}
                </div>
            </div>
        </div>
    </div>

    <table>
        <thead>
            <tr>
                <th>Date</th>
                <th>Project</th>
                <th>Employee</th>
                <th>Task</th>
                <th>Description</th>
                <th class="text-right">Hours</th>
                <th class="text-right">Rate</th>
                <th class="text-right">Amount</th>
            </tr>
        </thead>
        <tbody>
'''

        # Add data rows
        for record in data:
            desc = record['description'][:80]
            if len(record['description']) > 80:
                desc += '...'

            html += f'''
            <tr>
                <td>{record['date']}</td>
                <td>{record['project']}</td>
                <td>{record['employee']}</td>
                <td>{record['task']}</td>
                <td>{desc}</td>
                <td class="text-right">{record['hours']:.2f}</td>
                <td class="text-right">{record['rate']:.2f}</td>
                <td class="text-right">{record['amount']:.2f}</td>
            </tr>
'''

        # Add total row
        html += f'''
        </tbody>
        <tfoot>
            <tr class="total-row">
                <td colspan="5" class="text-right">TOTAL:</td>
                <td class="text-right">{total_hours:.2f}</td>
                <td></td>
                <td class="text-right">{total_amount:.2f} {self.billing_run_id.currency_id.name}</td>
            </tr>
        </tfoot>
    </table>
</body>
</html>
'''

        return html

    # ========================================================================
    # DATA EXTRACTION
    # ========================================================================

    def _get_export_data(self):
        """
        Extract timesheet data from billing run lines

        Returns:
            list of dicts with export columns
        """
        self.ensure_one()

        # Validate billing run has lines
        if not self.billing_run_id.line_ids:
            return []

        data = []

        # Prefetch relationships for performance
        self.billing_run_id.line_ids.mapped('timesheet_line_ids.timesheet_id')

        # Iterate through billing lines (sorted by project, employee)
        for line in self.billing_run_id.line_ids.sorted(
            lambda l: (l.project_id.name or '', l.employee_id.name)
        ):
            # Iterate through timesheet links (sorted by date)
            # Only export INCLUDED timesheets
            for ts_link in line.timesheet_line_ids.filtered(lambda tl: tl.included).sorted(lambda tl: tl.timesheet_id.date):
                ts = ts_link.timesheet_id

                # Extract sales order reference
                so_ref = ''
                if ts.tm_rate_card_entry_id and ts.tm_rate_card_entry_id.sale_order_line_id:
                    so_ref = ts.tm_rate_card_entry_id.sale_order_line_id.order_id.name or ''

                # Build export row
                data.append({
                    'billing_run_ref': self.billing_run_id.reference,
                    'period_start': self.billing_run_id.date_start,
                    'period_end': self.billing_run_id.date_end,
                    'client': self.billing_run_id.client_id.name,
                    'project': ts.project_id.name or '',
                    'employee': ts.employee_id.name,
                    'date': ts.date,
                    'task': ts.task_id.name or '',
                    'description': ts.name or '',
                    'hours_spent': ts.unit_amount,
                    'hours': ts.tm_adjusted_hours,
                    'rate': ts.tm_billing_rate,
                    'amount': ts.tm_billable_amount,
                    'currency': self.billing_run_id.currency_id.name,
                    'product': line.product_id.name,
                    'sales_order': so_ref,
                    'invoice': self.billing_run_id.invoice_id.name if self.billing_run_id.invoice_id else '',
                    'invoice_state': dict(self.billing_run_id.invoice_id._fields['state'].selection).get(
                        self.billing_run_id.invoice_id.state, ''
                    ) if self.billing_run_id.invoice_id else '',
                })

        return data

    # ========================================================================
    # CSV GENERATION
    # ========================================================================

    def _generate_csv(self, data):
        """
        Generate CSV file

        Args:
            data: list of dicts with export columns

        Returns:
            base64 encoded CSV file
        """
        self.ensure_one()

        output = io.StringIO()

        # Define headers
        headers = [
            'Billing Run Ref',
            'Period Start',
            'Period End',
            'Client',
            'Project',
            'Employee',
            'Date',
            'Task',
            'Description',
            'Hours Spent',
            'Adjusted Hours',
            'Rate',
            'Amount',
            'Currency',
            'Product/Service',
            'Sales Order',
            'Invoice Number',
            'Invoice State',
        ]

        # Create CSV writer
        writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

        # Write headers
        writer.writerow(headers)

        # Write data
        for record in data:
            writer.writerow([
                record['billing_run_ref'],
                record['period_start'],
                record['period_end'],
                record['client'],
                record['project'],
                record['employee'],
                record['date'],
                record['task'],
                record['description'],
                record['hours_spent'],
                record['hours'],
                record['rate'],
                record['amount'],
                record['currency'],
                record['product'],
                record['sales_order'],
                record['invoice'],
                record['invoice_state'],
            ])

        # Encode to base64
        return base64.b64encode(output.getvalue().encode('utf-8'))

    # ========================================================================
    # PREVIEW GENERATION
    # ========================================================================

    def _generate_preview_html(self, data):
        """
        Generate HTML preview of export data

        Args:
            data: list of dicts with export data

        Returns:
            HTML string
        """
        self.ensure_one()

        # Limit to first 100 rows for preview
        preview_data = data[:100]
        show_limit_message = len(data) > 100

        html = f'''
        <style>
            .export-preview {{
                max-height: 500px;
                overflow-y: auto;
                border: 1px solid #dee2e6;
                border-radius: 4px;
            }}
            .export-preview table {{
                margin-bottom: 0;
                font-size: 12px;
            }}
            .export-preview th {{
                position: sticky;
                top: 0;
                background-color: #f8f9fa;
                z-index: 10;
                border-bottom: 2px solid #dee2e6;
                padding: 8px;
                white-space: nowrap;
            }}
            .export-preview td {{
                padding: 6px 8px;
                border-bottom: 1px solid #f0f0f0;
            }}
            .export-preview tr:hover {{
                background-color: #f8f9fa;
            }}
            .text-end {{
                text-align: right;
            }}
        </style>
        '''

        if show_limit_message:
            html += f'''
            <div class="alert alert-info mb-2" role="alert">
                <i class="fa fa-info-circle"></i>
                Showing first <strong>100</strong> of <strong>{len(data)}</strong> included timesheets.
                All timesheets will be included in the export.
            </div>
            '''

        html += '''
        <div class="export-preview">
            <table class="table table-sm table-striped">
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Project</th>
                        <th>Employee</th>
                        <th>Task</th>
                        <th>Description</th>
                        <th class="text-end">Hours Spent</th>
                        <th class="text-end">Adjusted Hours</th>
                        <th class="text-end">Rate</th>
                        <th class="text-end">Amount</th>
                    </tr>
                </thead>
                <tbody>
        '''

        for record in preview_data:
            description = record['description']
            if len(description) > 60:
                description = description[:60] + '...'

            html += f'''
                <tr>
                    <td>{record['date']}</td>
                    <td>{record['project']}</td>
                    <td>{record['employee']}</td>
                    <td>{record['task']}</td>
                    <td>{description}</td>
                    <td class="text-end">{record['hours_spent']:.2f}</td>
                    <td class="text-end">{record['hours']:.2f}</td>
                    <td class="text-end">{record['rate']:.2f}</td>
                    <td class="text-end">{record['amount']:.2f}</td>
                </tr>
            '''

        html += '''
                </tbody>
            </table>
        </div>
        '''

        return html

    # ========================================================================
    # HELPERS
    # ========================================================================

    def _get_base_filename(self):
        """Generate base filename for exports"""
        self.ensure_one()

        # Clean client name (remove special characters)
        client_name = self.billing_run_id.client_id.name
        client_name = ''.join(c if c.isalnum() or c in (' ', '_') else '_' for c in client_name)
        client_name = client_name.replace(' ', '_')

        # Format: Billing_Run_{reference}_{client}_{date}
        filename = 'Billing_Run_{ref}_{client}_{date}'.format(
            ref=self.billing_run_id.reference,
            client=client_name,
            date=self.billing_run_id.date_end.strftime('%Y-%m-%d') if self.billing_run_id.date_end else 'NoDate',
        )

        return filename
