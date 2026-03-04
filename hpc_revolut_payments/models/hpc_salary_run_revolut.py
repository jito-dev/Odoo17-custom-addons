from odoo import models


class HpcSalaryRunRevolut(models.Model):
    _inherit = 'hr.payroll.contractor.salary.run'

    def action_export_revolut_csv(self):
        wizard = self.env['hpc.revolut.export.wizard'].create({
            'salary_run_ids': [(6, 0, self.ids)],
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hpc.revolut.export.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
