import base64
import logging
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _now_version():
    return 'v' + datetime.now().strftime('%Y%m%d-%H%M')


def _vars_html(file_data_b64):
    """Return an HTML table of Jinja2 variables found in a .docx binary, or False."""
    from odoo.addons.jito_document_template.services.docx_renderer import (  # noqa: PLC0415
        extract_jinja_variables,
    )
    if not file_data_b64:
        return False
    try:
        variables = extract_jinja_variables(base64.b64decode(file_data_b64))
        if not variables:
            return (
                '<span style="color:#6c757d;font-style:italic;">'
                'No Jinja2 variables detected.</span>'
            )
        rows = ''.join(
            '<tr class="o_data_row">'
            '<td class="o_data_cell" style="font-family:monospace;font-size:13px;">{{ %s }}</td>'
            '<td class="o_data_cell" style="color:#6c757d;font-size:13px;">%s</td>'
            '</tr>' % (v, v.split('.')[0])
            for v in variables
        )
        return (
            '<table class="o_list_table table table-sm table-hover mb-0" style="width:100%;">'
            '<thead><tr class="o_column_headers">'
            '<th class="o_column_header">Variable</th>'
            '<th class="o_column_header">Object</th>'
            '</tr></thead>'
            '<tbody>' + rows + '</tbody></table>'
        )
    except Exception as exc:
        return '<span style="color:#dc3545;font-style:italic;">Could not parse: %s</span>' % str(exc)


def _filename_vars_html(filename_template):
    """Return an HTML table of Jinja2 variables in a filename template string, or False."""
    from odoo.addons.jito_document_template.services.docx_renderer import (  # noqa: PLC0415
        extract_jinja_variables_from_string,
    )
    variables = extract_jinja_variables_from_string(filename_template or '')
    if not variables:
        return False
    rows = ''.join(
        '<tr class="o_data_row">'
        '<td class="o_data_cell" style="font-family:monospace;font-size:13px;">{{ %s }}</td>'
        '<td class="o_data_cell" style="color:#6c757d;font-size:13px;">%s</td>'
        '</tr>' % (v, v.split('.')[0])
        for v in variables
    )
    return (
        '<table class="o_list_table table table-sm table-hover mb-0" style="width:100%;">'
        '<thead><tr class="o_column_headers">'
        '<th class="o_column_header">Variable</th>'
        '<th class="o_column_header">Object</th>'
        '</tr></thead>'
        '<tbody>' + rows + '</tbody></table>'
    )


class UsaInvoiceConfig(models.Model):
    """Singleton invoice template configuration for Upwork Simple Accounting."""

    _name = 'usa.invoice.config'
    _description = 'Upwork Invoice Template Configuration'
    _inherit = ['mail.thread']

    lock_field = fields.Char(default='global', copy=False)

    _sql_constraints = [
        (
            'singleton',
            'UNIQUE(lock_field)',
            'Only one invoice configuration record is allowed.',
        ),
    ]

    # ── Template file ─────────────────────────────────────────────────────────

    inv_template_file = fields.Binary(
        string='Invoice Template (.docx)',
        attachment=True,
    )
    inv_template_filename = fields.Char(string='Template Filename')
    inv_output_filename = fields.Char(
        string='Output Filename Template',
        help='Jinja2 template for the generated file name. '
             'E.g.: invoice_{{ transaction.record_id }}.docx',
    )
    inv_template_version = fields.Char(
        string='Template Version',
        readonly=True,
        copy=False,
    )
    # ── Supplier / Issuer Info ────────────────────────────────────────────────

    supplier_legal_name = fields.Char(
        string='Supplier Legal Name',
        help='Legal name of the invoice issuer (your company / agency).',
    )
    supplier_legal_address = fields.Char(
        string='Supplier Legal Address',
        help='Full registered address of the invoice issuer.',
    )
    supplier_vat = fields.Char(
        string='Supplier VAT / Tax ID',
        help='VAT number or tax identifier of the invoice issuer.',
    )

    inv_detected_vars = fields.Html(
        string='Template Variables',
        compute='_compute_inv_detected_vars',
        sanitize=False,
    )
    inv_detected_filename_vars = fields.Html(
        string='Filename Variables',
        compute='_compute_inv_detected_filename_vars',
        sanitize=False,
    )
    inv_uploaded = fields.Boolean(
        string='Template Uploaded',
        compute='_compute_inv_uploaded',
    )

    # ── Computed ──────────────────────────────────────────────────────────────

    @api.depends('inv_template_file')
    def _compute_inv_uploaded(self):
        for rec in self:
            rec.inv_uploaded = bool(rec.with_context(bin_size=True).inv_template_file)

    @api.depends('inv_template_file')
    def _compute_inv_detected_vars(self):
        for rec in self:
            file_b64 = rec.with_context(bin_size=False).inv_template_file
            rec.inv_detected_vars = _vars_html(file_b64)

    @api.depends('inv_output_filename')
    def _compute_inv_detected_filename_vars(self):
        for rec in self:
            rec.inv_detected_filename_vars = _filename_vars_html(rec.inv_output_filename)

    # ── Onchange: auto-set version on upload ──────────────────────────────────

    @api.onchange('inv_template_file')
    def _onchange_inv_template_file(self):
        if self.inv_template_file:
            self.inv_template_version = _now_version()
            if self.inv_template_filename and not self.inv_output_filename:
                base = self.inv_template_filename.rsplit('.', 1)[0]
                self.inv_output_filename = base + '.docx'

    # ── Singleton helper ──────────────────────────────────────────────────────

    @api.model
    def _get_singleton(self):
        record = self.sudo().search([], limit=1)
        if not record:
            record = self.sudo().create({})
        return record

    @api.model
    def action_open(self):
        record = self._get_singleton()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'usa.invoice.config',
            'res_id': record.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_template(self):
        self.ensure_one()
        if not self.inv_uploaded:
            raise UserError(_('No invoice template uploaded yet.'))
        atts = self.env['ir.attachment'].search([
            ('res_model', '=', self._name),
            ('res_id', '=', self.id),
            ('res_field', '=', 'inv_template_file'),
        ], limit=1)
        if atts:
            return {
                'type': 'ir.actions.act_url',
                'url': '/web/content/%d?download=true' % atts.id,
                'target': 'self',
            }
        raise UserError(_('Template attachment not found.'))
