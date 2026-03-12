import base64
import json

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class DocumentTestGenerator(models.Model):
    """
    Singleton test page for rendering .docx templates with arbitrary JSON context.
    One record is created per user on first open.
    """
    _name = 'document.test.generator'
    _description = 'Document Test Generator'

    user_id = fields.Many2one(
        'res.users',
        string='User',
        required=True,
        default=lambda self: self.env.uid,
        index=True,
    )
    template_id = fields.Many2one(
        'document.template',
        string='Template',
        domain="[('active', '=', True)]",
    )
    tag_id = fields.Many2one(
        'document.template.tag',
        string='Filter by Tag',
        help='Narrow the template list to a specific tag.',
    )
    context_json = fields.Text(
        string='Context Variables (JSON)',
        default='{}',
        help='JSON object passed as variables to the template.\nExample: {"name": "Alice", "amount": 1500}',
    )
    generate_pdf = fields.Boolean(
        string='Also Generate PDF',
        default=True,
    )
    libreoffice_available = fields.Boolean(
        string='LibreOffice Available',
        compute='_compute_libreoffice_available',
    )
    last_generated_id = fields.Many2one(
        'document.generated',
        string='Last Result',
        readonly=True,
    )

    @api.depends()
    def _compute_libreoffice_available(self):
        from ..services.docx_renderer import is_libreoffice_available
        available = is_libreoffice_available()
        for rec in self:
            rec.libreoffice_available = available

    @api.model
    def action_open(self):
        """Get or create the singleton for the current user, then open its form."""
        record = self.search([('user_id', '=', self.env.uid)], limit=1)
        if not record:
            record = self.create({'user_id': self.env.uid})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Test Generator'),
            'res_model': self._name,
            'res_id': record.id,
            'view_mode': 'form',
            'view_id': self.env.ref(
                'jito_document_template.view_document_test_generator_form'
            ).id,
            'target': 'current',
        }

    def action_generate(self):
        self.ensure_one()
        if not self.template_id:
            raise UserError(_('Please select a template first.'))
        if not self.template_id.template_file:
            raise UserError(_('The selected template has no file attached.'))

        # Parse JSON context
        ctx = {}
        raw = (self.context_json or '').strip()
        if raw and raw != '{}':
            try:
                ctx = json.loads(raw)
                if not isinstance(ctx, dict):
                    raise UserError(_('Context Variables must be a JSON object, e.g. {"key": "value"}.'))
            except json.JSONDecodeError as e:
                raise UserError(_('Invalid JSON in Context Variables: %s') % str(e))

        template_bytes = base64.b64decode(self.template_id.template_file)
        filename_base = (
            self.template_id.template_filename or self.template_id.name or 'document'
        ).rsplit('.', 1)[0]

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

        except UserError:
            raise
        except Exception as e:
            state = 'error'
            error_message = str(e)

        generated = self.env['document.generated'].create({
            'template_id': self.template_id.id,
            'docx_attachment_id': docx_attachment.id if docx_attachment else False,
            'pdf_attachment_id': pdf_attachment.id if pdf_attachment else False,
            'state': state,
            'error_message': error_message,
            'generated_by': self.env.uid,
        })

        self.last_generated_id = generated

        return {
            'type': 'ir.actions.act_window',
            'name': _('Generated Document'),
            'res_model': 'document.generated',
            'res_id': generated.id,
            'view_mode': 'form',
            'target': 'current',
        }
