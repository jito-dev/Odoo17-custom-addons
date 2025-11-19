# -*- coding: utf-8 -*-
from odoo import fields, models

class HrJobRequirementTag(models.Model):
    """
    Model to store tags for job requirements (statements).
    e.g., "Domain Knowledge", "Hard Skill", "Soft Skill"
    """
    _name = 'hr.job.requirement.tag'
    _description = 'Job Requirement Tag'
    _order = 'name'

    name = fields.Char(string='Name', required=True, translate=True)
    color = fields.Integer(string='Color Index', default=10)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Tag name must be unique!'),
    ]