# -*- coding: utf-8 -*-
from odoo import fields, models

class JobContextTag(models.AbstractModel):
    _name = 'hr.job.context.tag.mixin'
    _description = 'Mixin for Job Context Tags'
    _order = 'name'

    name = fields.Char(string='Name', required=True, translate=True)
    color = fields.Integer(string='Color Index', default=0)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Tag name must be unique!'),
    ]

class HrJobEnglishLevel(models.Model):
    _name = 'hr.job.english.level'
    _inherit = 'hr.job.context.tag.mixin'
    _description = 'English Expectation Level'

class HrJobHiringReason(models.Model):
    _name = 'hr.job.hiring.reason'
    _inherit = 'hr.job.context.tag.mixin'
    _description = 'Reason for Hiring'

class HrJobRelocationStatus(models.Model):
    _name = 'hr.job.relocation.status'
    _inherit = 'hr.job.context.tag.mixin'
    _description = 'Relocation Status'

class HrJobCommitment(models.Model):
    _name = 'hr.job.commitment'
    _inherit = 'hr.job.context.tag.mixin'
    _description = 'Commitment Expectation'