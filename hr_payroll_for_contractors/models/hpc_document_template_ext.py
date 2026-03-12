from odoo import api, fields, models

_HOURLY_AGREEMENT_DEFAULTS = [
    ('hourly_rate', '100'),
    ('currency', 'USD'),
]


class DocumentTemplateHpcExt(models.Model):
    """Add contract/service agreement categories to document.template."""
    _inherit = 'document.template'

    category = fields.Selection(
        selection_add=[
            ('contract', 'Contract'),
            ('hourly_service_agreement', 'Hourly Service Agreement'),
            ('hourly_service_agreement_termination', 'Hourly Service Agreement Termination'),
        ],
        ondelete={
            'contract': 'set default',
            'hourly_service_agreement': 'set default',
            'hourly_service_agreement_termination': 'set default',
        },
    )
    metadata_default_ids = fields.One2many(
        'document.template.metadata.default',
        'template_id',
        string='Metadata Defaults',
    )

    @api.model
    def default_get(self, fields_list):
        """Ensure default_category context key is honoured even when the
        model-level default='other' would otherwise win."""
        defaults = super().default_get(fields_list)
        ctx_cat = self._context.get('default_category')
        if ctx_cat and 'category' in fields_list:
            defaults['category'] = ctx_cat
        return defaults

    @api.onchange('category')
    def _onchange_category_metadata_defaults(self):
        if self.category == 'hourly_service_agreement' and not self.metadata_default_ids:
            self.metadata_default_ids = [
                (0, 0, {'key': key, 'default_value': value})
                for key, value in _HOURLY_AGREEMENT_DEFAULTS
            ]
