import base64
import logging
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

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
    except Exception as e:
        return '<span style="color:#dc3545;font-style:italic;">Could not parse: %s</span>' % str(e)


def _filename_vars_html(filename_template):
    """Return an HTML table of Jinja2 variables found in a filename template string, or False."""
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


def _now_version():
    return 'v' + datetime.now().strftime('%Y%m%d-%H%M')


class HpcServiceAgreement(models.Model):
    """Singleton configuration record per agreement category.
    Each category (e.g. 'UA PE - Hourly - Consulting Agreement') has exactly
    one record holding template files and default values used when generating
    real contracts for contractors."""

    _name = 'hpc.service.agreement'
    _description = 'Service Agreement Template Configuration'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'agreement_category'

    _sql_constraints = [
        (
            'unique_agreement_category',
            'UNIQUE(agreement_category)',
            'A configuration for this agreement category already exists.',
        ),
    ]

    # ── Category ────────────────────────────────────────────────────────────────

    agreement_category = fields.Selection(
        selection=[
            ('ua_pe_hourly_consulting', 'UA PE - Hourly - Consulting Agreement'),
        ],
        string='Agreement Category',
        required=True,
        default='ua_pe_hourly_consulting',
        tracking=True,
    )
    # Non-stored navigation selector shown in the form header.
    # Allows switching the view between implemented and future categories
    # without modifying the underlying singleton record.
    view_category = fields.Selection(
        selection=[
            ('ua_pe_hourly_consulting', 'UA PE - Hourly - Consulting Agreement'),
            ('ua_pe_monthly_retainer_consulting', 'UA PE - Monthly Retainer - Consulting Agreement'),
        ],
        string='Agreement Category',
        compute='_compute_view_category',
        inverse='_inverse_view_category',
        store=False,
    )
    name = fields.Char(
        string='Name',
        compute='_compute_name',
    )

    # ── Tab 1 — Service Agreement Initiation ────────────────────────────────────

    agreement_type = fields.Selection(
        selection=[
            ('hourly_based', 'Hourly-based'),
            ('monthly_retainer', 'Monthly Retainer'),
            ('fix_price_deliveries', 'Fix-price Deliveries'),
        ],
        string='Service Agreement Type',
        default='hourly_based',
        required=True,
        tracking=True,
    )
    # Hourly-based defaults
    currency_id = fields.Many2one(
        'res.currency',
        string='Default Currency',
        default=lambda self: self.env.ref('base.USD', raise_if_not_found=False),
    )
    default_hourly_rate = fields.Float(
        string='Default Hourly Rate',
        default=100.0,
    )
    # Contract term defaults
    termination_notice_days = fields.Integer(
        string='Default Termination Notice (days)',
        default=14,
        help='Default number of days either party must give notice before terminating.',
    )
    payment_banking_days = fields.Integer(
        string='Default Payment Period (banking days)',
        default=15,
        help='Default number of banking days the customer has to pay the invoice.',
    )
    customer_email_contact_id = fields.Many2one(
        'res.partner',
        string='Default Customer Official Email Contact',
        help='Default contact to receive official notices (invoices, termination etc.).',
    )

    # Required context — used to filter applicable agreements per contractor
    acceptable_entity_type_ids = fields.Many2many(
        'hpc.legal.entity.type',
        'hpc_service_agreement_entity_type_rel',
        'agreement_id',
        'entity_type_id',
        string='Acceptable Legal Entity Types',
    )

    # Initiation template
    init_template_file = fields.Binary(string='Template File (.docx)', attachment=True)
    init_template_filename = fields.Char(string='Uploaded Filename')
    init_output_filename = fields.Char(
        string='Output Filename',
        help='Defaults to the uploaded filename. Supports Jinja2 variables, e.g. "SA_{{ ctx.contract_id }}.docx".',
    )
    init_template_version = fields.Char(string='Template Version', readonly=True, copy=False)
    init_detected_vars = fields.Html(
        string='Detected Variables (Template Body)',
        compute='_compute_init_detected_vars',
        sanitize=False,
    )
    init_detected_filename_vars = fields.Html(
        string='Detected Variables (Filename)',
        compute='_compute_init_detected_filename_vars',
        sanitize=False,
    )

    # ── Tab 2 — Service Agreement Termination ───────────────────────────────────

    term_template_file = fields.Binary(string='Template File (.docx)', attachment=True)
    term_template_filename = fields.Char(string='Uploaded Filename')
    term_output_filename = fields.Char(
        string='Output Filename',
        help='Defaults to the uploaded filename. Supports Jinja2 variables.',
    )
    term_template_version = fields.Char(string='Template Version', readonly=True, copy=False)
    term_detected_vars = fields.Html(
        string='Detected Variables (Template Body)',
        compute='_compute_term_detected_vars',
        sanitize=False,
    )
    term_detected_filename_vars = fields.Html(
        string='Detected Variables (Filename)',
        compute='_compute_term_detected_filename_vars',
        sanitize=False,
    )

    # ── Tab 3 — Contractor-side Invoicing ───────────────────────────────────────

    acceptable_payment_type_ids = fields.Many2many(
        'hpc.payment.method.type',
        'hpc_service_agreement_payment_type_rel',
        'agreement_id',
        'payment_type_id',
        string='Acceptable Payment Methods',
    )

    inv_template_file = fields.Binary(string='Template File (.docx)', attachment=True)
    inv_template_filename = fields.Char(string='Uploaded Filename')
    inv_output_filename = fields.Char(
        string='Output Filename',
        help='Defaults to the uploaded filename. Supports Jinja2 variables.',
    )
    inv_template_version = fields.Char(string='Template Version', readonly=True, copy=False)
    inv_detected_vars = fields.Html(
        string='Detected Variables (Template Body)',
        compute='_compute_inv_detected_vars',
        sanitize=False,
    )
    inv_detected_filename_vars = fields.Html(
        string='Detected Variables (Filename)',
        compute='_compute_inv_detected_filename_vars',
        sanitize=False,
    )

    # ── Template upload status (computed) ───────────────────────────────────────

    init_uploaded = fields.Boolean(
        string='Initiation Template Uploaded',
        compute='_compute_upload_status',
    )
    term_uploaded = fields.Boolean(
        string='Termination Template Uploaded',
        compute='_compute_upload_status',
    )
    inv_uploaded = fields.Boolean(
        string='Invoicing Template Uploaded',
        compute='_compute_upload_status',
    )

    # ── Computed ────────────────────────────────────────────────────────────────

    @api.depends('agreement_category')
    def _compute_view_category(self):
        for rec in self:
            rec.view_category = rec.agreement_category

    def _inverse_view_category(self):
        pass  # Navigation-only — never persisted

    @api.depends('init_template_file', 'term_template_file', 'inv_template_file')
    def _compute_upload_status(self):
        for rec in self:
            rec.init_uploaded = bool(rec.with_context(bin_size=True).init_template_file)
            rec.term_uploaded = bool(rec.with_context(bin_size=True).term_template_file)
            rec.inv_uploaded = bool(rec.with_context(bin_size=True).inv_template_file)

    @api.depends('agreement_category')
    def _compute_name(self):
        labels = dict(self._fields['agreement_category'].selection)
        for rec in self:
            rec.name = labels.get(rec.agreement_category, _('Service Agreement'))

    @api.depends('init_template_file')
    def _compute_init_detected_vars(self):
        for rec in self:
            rec.init_detected_vars = _vars_html(
                rec.with_context(bin_size=False).init_template_file
            )

    @api.depends('init_output_filename')
    def _compute_init_detected_filename_vars(self):
        for rec in self:
            rec.init_detected_filename_vars = _filename_vars_html(rec.init_output_filename)

    @api.depends('term_template_file')
    def _compute_term_detected_vars(self):
        for rec in self:
            rec.term_detected_vars = _vars_html(
                rec.with_context(bin_size=False).term_template_file
            )

    @api.depends('term_output_filename')
    def _compute_term_detected_filename_vars(self):
        for rec in self:
            rec.term_detected_filename_vars = _filename_vars_html(rec.term_output_filename)

    @api.depends('inv_template_file')
    def _compute_inv_detected_vars(self):
        for rec in self:
            rec.inv_detected_vars = _vars_html(
                rec.with_context(bin_size=False).inv_template_file
            )

    @api.depends('inv_output_filename')
    def _compute_inv_detected_filename_vars(self):
        for rec in self:
            rec.inv_detected_filename_vars = _filename_vars_html(rec.inv_output_filename)

    # ── Singleton opener ────────────────────────────────────────────────────────

    @api.model
    def action_open_agreement(self, category='ua_pe_hourly_consulting'):
        """Return an act_window opening the singleton for the given category,
        creating it if it does not exist yet."""
        record = self.search([('agreement_category', '=', category)], limit=1)
        if not record:
            record = self.create({'agreement_category': category})
        labels = dict(self._fields['agreement_category'].selection)
        return {
            'type': 'ir.actions.act_window',
            'name': labels.get(category, 'Service Agreement'),
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': record.id,
            'target': 'current',
        }

    # ── ORM overrides ───────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        now = _now_version()
        for vals in vals_list:
            for file_f, fn_f, out_f, ver_f in self._template_slots():
                if vals.get(file_f):
                    vals[ver_f] = now
                    # Auto-fill output filename from uploaded filename if empty
                    if vals.get(fn_f) and not vals.get(out_f):
                        vals[out_f] = vals[fn_f]
        return super().create(vals_list)

    def write(self, vals):
        now = _now_version()
        for file_f, fn_f, out_f, ver_f in self._template_slots():
            if vals.get(file_f):
                vals[ver_f] = now
                # Auto-fill output filename from uploaded filename if currently empty
                if vals.get(fn_f) and out_f not in vals:
                    for rec in self:
                        if not rec[out_f]:
                            vals[out_f] = vals[fn_f]
                            break
        return super().write(vals)

    @staticmethod
    def _template_slots():
        return [
            ('init_template_file', 'init_template_filename', 'init_output_filename', 'init_template_version'),
            ('term_template_file', 'term_template_filename', 'term_output_filename', 'term_template_version'),
            ('inv_template_file', 'inv_template_filename', 'inv_output_filename', 'inv_template_version'),
        ]

    # ── Download / view actions ──────────────────────────────────────────────────

    def _file_url(self, field_name, filename_field, download=False):
        url = (
            '/web/content?model=%s&id=%d&field=%s&filename_field=%s'
            % (self._name, self.id, field_name, filename_field)
        )
        if download:
            url += '&download=true'
        return url

    def action_view_init_template(self):
        self.ensure_one()
        if not self.init_template_file:
            raise UserError(_('No initiation template file uploaded yet.'))
        return {'type': 'ir.actions.act_url',
                'url': self._file_url('init_template_file', 'init_template_filename'),
                'target': 'new'}

    def action_download_init_template(self):
        self.ensure_one()
        if not self.init_template_file:
            raise UserError(_('No initiation template file uploaded yet.'))
        return {'type': 'ir.actions.act_url',
                'url': self._file_url('init_template_file', 'init_template_filename', download=True),
                'target': 'self'}

    def action_view_term_template(self):
        self.ensure_one()
        if not self.term_template_file:
            raise UserError(_('No termination template file uploaded yet.'))
        return {'type': 'ir.actions.act_url',
                'url': self._file_url('term_template_file', 'term_template_filename'),
                'target': 'new'}

    def action_download_term_template(self):
        self.ensure_one()
        if not self.term_template_file:
            raise UserError(_('No termination template file uploaded yet.'))
        return {'type': 'ir.actions.act_url',
                'url': self._file_url('term_template_file', 'term_template_filename', download=True),
                'target': 'self'}

    def action_view_inv_template(self):
        self.ensure_one()
        if not self.inv_template_file:
            raise UserError(_('No invoice template file uploaded yet.'))
        return {'type': 'ir.actions.act_url',
                'url': self._file_url('inv_template_file', 'inv_template_filename'),
                'target': 'new'}

    def action_download_inv_template(self):
        self.ensure_one()
        if not self.inv_template_file:
            raise UserError(_('No invoice template file uploaded yet.'))
        return {'type': 'ir.actions.act_url',
                'url': self._file_url('inv_template_file', 'inv_template_filename', download=True),
                'target': 'self'}
