from odoo import models, fields


class MaintenanceEquipment(models.Model):
    _inherit = 'maintenance.equipment'

    condition = fields.Selection(selection=[
        ('good', 'Good'),
        ("standard", "Standard care"),
        ('check', 'Needs checking'),
        ("replace", "Needs replacement"),
        ('broken', 'Broken')
    ], string='Condition', default='good')
    next_maintenance_date = fields.Date(string='Next Maintenance')
    effective_date = fields.Date(help=False)