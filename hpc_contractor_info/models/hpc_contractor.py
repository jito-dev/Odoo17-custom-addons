from odoo import api, fields, models


class HpcContractor(models.Model):
    _name = 'hpc.contractor'
    _description = 'Contractor'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'employee_id'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        ondelete='restrict',
        tracking=True,
    )
    display_name = fields.Char(
        compute='_compute_display_name',
        store=True,
    )
    legal_entity_ids = fields.One2many(
        'hpc.contractor.legal.entity',
        'contractor_id',
        string='Legal Entities',
    )
    payment_method_ids = fields.One2many(
        'hpc.contractor.payment.method',
        'contractor_id',
        string='Payment Methods',
    )

    _sql_constraints = [
        (
            'employee_uniq',
            'unique(employee_id)',
            'A contractor record already exists for this employee.',
        ),
    ]

    @api.depends('employee_id', 'employee_id.name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.employee_id.name or ''
