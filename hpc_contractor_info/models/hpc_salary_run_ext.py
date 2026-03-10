import base64
import io
import zipfile

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class HpcSalaryRunExt(models.Model):
    _inherit = 'hr.payroll.contractor.salary.run'

    contractor_invoice_ids = fields.One2many(
        'hpc.contractor.invoice',
        'salary_run_id',
        string='Contractor Invoices',
    )
    contractor_invoice_count = fields.Integer(
        compute='_compute_contractor_invoice_count',
        string='Contractor Invoices',
    )
    contractor_invoice_id = fields.Many2one(
        'hpc.contractor.invoice',
        string='Contractor Invoice (Internal)',
        compute='_compute_contractor_invoice_id',
        store=False,
    )

    @api.depends('contractor_invoice_ids')
    def _compute_contractor_invoice_count(self):
        for run in self:
            run.contractor_invoice_count = len(run.contractor_invoice_ids)

    @api.depends('contractor_invoice_ids')
    def _compute_contractor_invoice_id(self):
        for run in self:
            run.contractor_invoice_id = run.contractor_invoice_ids[:1]

    # ── Core generation helper ─────────────────────────────────────────────────

    def _generate_and_attach_invoice_pdf(self):
        """Create/update the internal hpc.contractor.invoice, generate the PDF
        and write it back to contractor_invoice_file on this salary run.

        Returns (invoice, error_message_or_None).
        """
        self.ensure_one()
        contract = self.contract_id
        existing = self.contractor_invoice_ids[:1]
        vals = {
            'salary_run_id': self.id,
            'employee_id': self.employee_id.id,
            'legal_entity_id': (contract.legal_entity_id.id if contract else False) or False,
        }
        if existing:
            existing.write(vals)
            invoice = existing
        else:
            invoice = self.env['hpc.contractor.invoice'].create(vals)

        # Generate DOCX + PDF (raises UserError if template not configured)
        try:
            invoice.action_generate_invoice_docs()
        except Exception as e:
            return invoice, str(e)

        # Prefer PDF attachment; fall back to DOCX
        att = invoice.generated_pdf_id or invoice.generated_docx_id
        if att:
            file_data = att.with_context(bin_size=False).datas
            self.write({
                'contractor_invoice_file': file_data,
                'contractor_invoice_filename': att.name,
            })

        return invoice, None

    # ── Single-run action (form header button) ────────────────────────────────

    def action_generate_contractor_invoices(self):
        """Generate contractor invoice PDF for this salary run and navigate to it."""
        self.ensure_one()
        if self.state != 'approved_and_locked':
            raise UserError(_(
                'Contractor invoices can only be generated for approved & locked salary runs.'
            ))

        invoice, err = self._generate_and_attach_invoice_pdf()
        if err:
            # Warn but still open the invoice so the user can see what's missing
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Invoice generated with warnings'),
                    'message': err,
                    'type': 'warning',
                    'sticky': True,
                    'next': {
                        'type': 'ir.actions.act_window',
                        'res_model': 'hpc.contractor.invoice',
                        'res_id': invoice.id,
                        'view_mode': 'form',
                        'target': 'current',
                    },
                },
            }

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hpc.contractor.invoice',
            'res_id': invoice.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ── Batch action (list Action menu) ───────────────────────────────────────

    def action_batch_generate_contractor_invoices(self):
        """Batch: generate contractor invoice PDF for each selected salary run."""
        errors = []
        generated = 0
        for run in self:
            if run.state != 'approved_and_locked':
                errors.append(_('%s — not in Approved & Locked state.') % run.reference)
                continue
            _inv, err = run._generate_and_attach_invoice_pdf()
            if err:
                errors.append(_('%s — %s') % (run.reference, err))
            else:
                generated += 1

        msg = _('%d invoice(s) generated.') % generated
        if errors:
            msg += '\n\n' + _('Warnings:\n') + '\n'.join(errors)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Generate Contractor Invoices'),
                'message': msg,
                'type': 'warning' if errors else 'success',
                'sticky': bool(errors),
            },
        }

    def action_open_contractor_invoices(self):
        """Open contractor invoices list for this salary run."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Contractor Invoices'),
            'res_model': 'hpc.contractor.invoice',
            'domain': [('salary_run_id', '=', self.id)],
            'view_mode': 'tree,form',
            'target': 'current',
        }

    # ── Download (batch list action) ──────────────────────────────────────────

    def action_download_contractor_invoices(self):
        """Download the contractor_invoice_file attached to each selected salary run as a ZIP."""
        runs_with_file = self.filtered(lambda r: r.contractor_invoice_file)
        if not runs_with_file:
            raise UserError(_(
                'No invoice files are attached to the selected salary runs. '
                'Generate invoices first.'
            ))

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for run in runs_with_file:
                data = base64.b64decode(
                    run.with_context(bin_size=False).contractor_invoice_file
                )
                filename = run.contractor_invoice_filename or (
                    'invoice_%s.pdf' % run.reference
                )
                # Strip any path separators so the ZIP stays flat
                filename = filename.replace('/', '-').replace('\\', '-')
                zf.writestr(filename, data)
        buf.seek(0)

        zip_att = self.env['ir.attachment'].create({
            'name': 'contractor_invoices.zip',
            'datas': base64.b64encode(buf.read()),
            'mimetype': 'application/zip',
            'res_model': 'hr.payroll.contractor.salary.run',
            'res_id': self.ids[0] if self.ids else False,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % zip_att.id,
            'target': 'self',
        }
