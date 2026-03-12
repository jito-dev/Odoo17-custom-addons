import base64
import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class DocumentTemplate(models.Model):
    _name = 'document.template'
    _description = 'Document Template'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(
        string='Template Name',
        required=True,
        tracking=True,
    )
    category = fields.Selection(
        selection=[
            ('invoice', 'Invoice'),
            ('agreement', 'Agreement'),
            ('nda', 'NDA'),
            ('other', 'Other'),
        ],
        string='Category',
        required=True,
        default='other',
        tracking=True,
    )
    template_file = fields.Binary(
        string='Template File (.docx)',
        required=True,
        attachment=True,
    )
    template_filename = fields.Char(
        string='Filename',
    )
    description = fields.Text(
        string='Description',
        help='Describe available {{ variables }} for this template.',
    )
    tag_ids = fields.Many2many(
        'document.template.tag',
        string='Tags',
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )
    detected_variables = fields.Html(
        string='Detected Variables',
        compute='_compute_detected_variables',
        sanitize=False,
    )
    detected_filename_variables = fields.Html(
        string='Filename Variables',
        compute='_compute_detected_filename_variables',
        sanitize=False,
    )
    generated_count = fields.Integer(
        string='Generated',
        compute='_compute_generated_count',
    )

    @api.depends('template_file')
    def _compute_detected_variables(self):
        from ..services.docx_renderer import extract_jinja_variables  # noqa: PLC0415
        for rec in self:
            # Force bin_size=False: the web client passes bin_size=True which causes
            # the Binary field to return a human-readable size ("12.3 kB") instead of
            # the actual file content, breaking base64 decoding.
            file_data = rec.with_context(bin_size=False).template_file
            if not file_data:
                rec.detected_variables = False
                continue
            try:
                variables = extract_jinja_variables(base64.b64decode(file_data))
                if variables:
                    rows = ''.join(
                        '<tr class="o_data_row">'
                        '<td class="o_data_cell" style="font-family:monospace;font-size:13px;">'
                        '{{ %s }}</td>'
                        '<td class="o_data_cell" style="color:#6c757d;font-size:13px;">%s</td>'
                        '</tr>' % (v, v.split('.')[0])
                        for v in variables
                    )
                    rec.detected_variables = (
                        '<table class="o_list_table table table-sm table-hover mb-0"'
                        ' style="width:100%;">'
                        '<thead><tr class="o_column_headers">'
                        '<th class="o_column_header">Variable</th>'
                        '<th class="o_column_header">Object</th>'
                        '</tr></thead>'
                        '<tbody>' + rows + '</tbody>'
                        '</table>'
                    )
                else:
                    rec.detected_variables = (
                        '<span style="color:#6c757d;font-style:italic;">'
                        'No Jinja2 variables detected.</span>'
                    )
            except Exception as e:
                _logger.warning('Could not parse Jinja2 variables from template %s: %s', rec.id, e)
                rec.detected_variables = (
                    '<span style="color:#dc3545;font-style:italic;">'
                    'Could not parse template file.</span>'
                )

    @api.depends('template_filename')
    def _compute_detected_filename_variables(self):
        from ..services.docx_renderer import extract_jinja_variables_from_string  # noqa: PLC0415
        for rec in self:
            filename = rec.template_filename or ''
            variables = extract_jinja_variables_from_string(filename)
            if not variables:
                rec.detected_filename_variables = False
                continue
            rows = ''.join(
                '<tr class="o_data_row">'
                '<td class="o_data_cell" style="font-family:monospace;font-size:13px;">'
                '{{ %s }}</td>'
                '<td class="o_data_cell" style="color:#6c757d;font-size:13px;">%s</td>'
                '</tr>' % (v, v.split('.')[0])
                for v in variables
            )
            rec.detected_filename_variables = (
                '<table class="o_list_table table table-sm table-hover mb-0"'
                ' style="width:100%;">'
                '<thead><tr class="o_column_headers">'
                '<th class="o_column_header">Variable</th>'
                '<th class="o_column_header">Object</th>'
                '</tr></thead>'
                '<tbody>' + rows + '</tbody>'
                '</table>'
            )

    def _compute_generated_count(self):
        for rec in self:
            rec.generated_count = self.env['document.generated'].search_count(
                [('template_id', '=', rec.id)]
            )

    def action_test_generate(self):
        """Open the generate wizard pre-populated with this template for quick testing."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Test Generate'),
            'res_model': 'document.generate.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_template_id': self.id,
            },
        }

    def action_view_generated(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generated Documents'),
            'res_model': 'document.generated',
            'view_mode': 'tree,form',
            'domain': [('template_id', '=', self.id)],
            'context': {'default_template_id': self.id},
            'target': 'current',
        }
