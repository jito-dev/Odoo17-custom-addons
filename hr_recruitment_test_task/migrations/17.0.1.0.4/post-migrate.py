# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    jobs = env['hr.job'].search([('add_test_task', '=', True)])
    for job in jobs:
        job._manage_test_task_stages(True)
