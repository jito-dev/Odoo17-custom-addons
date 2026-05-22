def migrate(cr, version):
    """Backfill hr.job.stage.config rows for jobs that already have
    add_test_task=True. Without these rows the three test task stages stay
    hidden on the kanban after hr_recruitment_job_stage_config switched
    visibility from job_ids-only to config-driven.
    """
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})
    if 'hr.job.stage.config' not in env:
        return
    jobs = env['hr.job'].search([('add_test_task', '=', True)])
    for job in jobs:
        job._manage_test_task_stages(True)
