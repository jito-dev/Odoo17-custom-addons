from odoo import api, fields, models, _


class DocumentGeneratorMixin(models.AbstractModel):
    _name = 'document.generator.mixin'
    _description = 'Document Generator Mixin'

    document_generated_ids = fields.One2many(
        'document.generated',
        string='Generated Documents',
        compute='_compute_document_generated_ids',
    )
    document_generated_count = fields.Integer(
        string='Documents',
        compute='_compute_document_generated_ids',
    )

    def _compute_document_generated_ids(self):
        if not self.ids:
            for rec in self:
                rec.document_generated_ids = self.env['document.generated']
                rec.document_generated_count = 0
            return
        recs = self.env['document.generated'].search([
            ('res_model', '=', self._name),
            ('res_id', 'in', self.ids),
        ])
        by_id = {}
        for doc in recs:
            by_id.setdefault(doc.res_id, []).append(doc.id)
        for rec in self:
            ids = by_id.get(rec.id, [])
            rec.document_generated_ids = self.env['document.generated'].browse(ids)
            rec.document_generated_count = len(ids)

    def _build_document_context(self):
        """Override in consuming modules to provide template variables."""
        return {}

    def action_generate_document(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generate Document'),
            'res_model': 'document.generate.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': self._name,
                'default_res_id': self.id,
            },
        }

    def action_view_generated_documents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generated Documents'),
            'res_model': 'document.generated',
            'view_mode': 'tree,form',
            'domain': [
                ('res_model', '=', self._name),
                ('res_id', '=', self.id),
            ],
            'target': 'current',
        }
