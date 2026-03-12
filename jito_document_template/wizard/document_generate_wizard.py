import base64
import json

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class DocumentGenerateWizard(models.TransientModel):
    _name = 'document.generate.wizard'
    _description = 'Generate Document Wizard'

    template_id = fields.Many2one(
        'document.template',
        string='Template',
        required=True,
        domain="[('active', '=', True)]",
    )
    tag_id = fields.Many2one(
        'document.template.tag',
        string='Filter by Tag',
        help='Filter the template list to a specific tag or sub-tag.',
    )
    res_model = fields.Char(
        string='Source Model',
        default=lambda self: self.env.context.get('default_res_model'),
    )
    res_id = fields.Integer(
        string='Source Record ID',
        default=lambda self: self.env.context.get('default_res_id', 0),
    )
    context_json = fields.Text(
        string='Context Variables (JSON)',
        default='{}',
        help='JSON object passed as variables to the template, e.g. {"name": "Alice", "amount": 1500}',
    )
    generate_pdf = fields.Boolean(
        string='Also Generate PDF',
        default=True,
    )
    libreoffice_available = fields.Boolean(
        string='LibreOffice Available',
        compute='_compute_libreoffice_available',
    )

    @api.depends()
    def _compute_libreoffice_available(self):
        from ..services.docx_renderer import is_libreoffice_available
        available = is_libreoffice_available()
        for rec in self:
            rec.libreoffice_available = available

    @api.onchange('tag_id')
    def _onchange_tag_id(self):
        self.template_id = False

    def _get_template_domain(self):
        domain = [('active', '=', True)]
        if self.tag_id:
            domain.append(('tag_ids', 'in', self.tag_id.id))
        return domain

    def action_generate(self):
        self.ensure_one()
        template = self.template_id
        if not template.template_file:
            raise UserError(_('The selected template has no file attached.'))

        # Build context: start from source record if available
        ctx = {}
        if self.res_model and self.res_id:
            try:
                source = self.env[self.res_model].browse(self.res_id)
                if hasattr(source, '_build_document_context'):
                    ctx = source._build_document_context()
            except Exception:
                ctx = {}

        # Merge/override with manually provided JSON context
        if self.context_json and self.context_json.strip() not in ('', '{}'):
            try:
                manual_ctx = json.loads(self.context_json)
                if not isinstance(manual_ctx, dict):
                    raise UserError(_('Context Variables must be a JSON object, e.g. {"key": "value"}.'))
                ctx.update(manual_ctx)
            except json.JSONDecodeError as e:
                raise UserError(_('Invalid JSON in Context Variables: %s') % str(e))

        template_bytes = base64.b64decode(template.template_file)
        filename_base = (template.template_filename or template.name or 'document').rsplit('.', 1)[0]

        docx_attachment = None
        pdf_attachment = None
        state = 'generated'
        error_message = False

        try:
            from ..services.docx_renderer import render_docx, convert_to_pdf, is_libreoffice_available

            docx_bytes = render_docx(template_bytes, ctx)

            docx_attachment = self.env['ir.attachment'].create({
                'name': '%s.docx' % filename_base,
                'datas': base64.b64encode(docx_bytes),
                'mimetype': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            })

            if self.generate_pdf and is_libreoffice_available():
                pdf_bytes = convert_to_pdf(docx_bytes)
                pdf_attachment = self.env['ir.attachment'].create({
                    'name': '%s.pdf' % filename_base,
                    'datas': base64.b64encode(pdf_bytes),
                    'mimetype': 'application/pdf',
                })

        except (UserError, Exception) as e:
            if isinstance(e, UserError):
                raise
            state = 'error'
            error_message = str(e)

        generated = self.env['document.generated'].create({
            'template_id': template.id,
            'res_model': self.res_model or False,
            'res_id': self.res_id or 0,
            'docx_attachment_id': docx_attachment.id if docx_attachment else False,
            'pdf_attachment_id': pdf_attachment.id if pdf_attachment else False,
            'state': state,
            'error_message': error_message,
            'generated_by': self.env.uid,
        })

        return {
            'type': 'ir.actions.act_window',
            'name': _('Generated Document'),
            'res_model': 'document.generated',
            'res_id': generated.id,
            'view_mode': 'form',
            'target': 'current',
        }
