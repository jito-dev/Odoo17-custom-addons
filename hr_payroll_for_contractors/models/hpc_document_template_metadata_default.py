from odoo import fields, models


class DocumentTemplateMetadataDefault(models.Model):
    _name = 'document.template.metadata.default'
    _description = 'Document Template Metadata Default'
    _order = 'key'

    template_id = fields.Many2one(
        'document.template',
        string='Template',
        required=True,
        ondelete='cascade',
        index=True,
    )
    key = fields.Char(string='Key', required=True)
    default_value = fields.Char(string='Default Value')
