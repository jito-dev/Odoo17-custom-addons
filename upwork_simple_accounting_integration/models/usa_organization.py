from odoo import fields, models


class UsaOrganization(models.Model):
    """Cache of Upwork organizations fetched from companySelector GraphQL query."""

    _name = 'usa.organization'
    _description = 'Upwork Organization'
    _rec_name = 'title'
    _order = 'title'

    title = fields.Char(string='Name', required=True)
    organization_id = fields.Char(string='Organization ID', required=True)
    organization_rid = fields.Char(string='Organization RID')
    organization_type = fields.Char(string='Type')
    photo_url = fields.Char(string='Photo URL')
