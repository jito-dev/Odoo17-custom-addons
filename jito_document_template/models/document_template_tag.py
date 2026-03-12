from odoo import fields, models


class DocumentTemplateTag(models.Model):
    _name = 'document.template.tag'
    _description = 'Document Template Tag'
    _parent_name = 'parent_id'
    _parent_store = True
    _rec_name = 'complete_name'
    _order = 'complete_name'

    name = fields.Char(string='Tag', required=True)
    complete_name = fields.Char(
        string='Full Path',
        compute='_compute_complete_name',
        store=True,
        recursive=True,
    )
    parent_id = fields.Many2one(
        'document.template.tag',
        string='Parent Tag',
        ondelete='cascade',
        index=True,
    )
    parent_path = fields.Char(index=True, unaccent=False)
    child_ids = fields.One2many(
        'document.template.tag',
        'parent_id',
        string='Sub-Tags',
    )
    template_count = fields.Integer(
        string='Templates',
        compute='_compute_template_count',
    )

    def _compute_complete_name(self):
        for tag in self:
            if tag.parent_id:
                tag.complete_name = '%s / %s' % (tag.parent_id.complete_name, tag.name)
            else:
                tag.complete_name = tag.name

    def _compute_template_count(self):
        for tag in self:
            tag.template_count = self.env['document.template'].search_count(
                [('tag_ids', 'in', tag.id)]
            )
