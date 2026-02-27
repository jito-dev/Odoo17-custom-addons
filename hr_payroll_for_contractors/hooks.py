from datetime import date
from dateutil.relativedelta import relativedelta


def post_init_hook(env):
    """Initialize the singleton settings record on first install."""
    Settings = env['hr.payroll.contractor.settings']
    companies = env['res.company'].search([])
    for company in companies:
        existing = Settings.search([('company_id', '=', company.id)], limit=1)
        if not existing:
            today = date.today()
            date_start = today.replace(day=1)
            date_end = date_start + relativedelta(months=1, days=-1)
            Settings.create({
                'company_id': company.id,
                'dashboard_date_start': date_start,
                'dashboard_date_end': date_end,
            })


def post_migrate_hook(env):
    """Migrate existing 'locked' records to 'approved_and_locked'."""
    env.cr.execute(
        "UPDATE hr_payroll_contractor_salary_run "
        "SET state = 'approved_and_locked' WHERE state = 'locked'"
    )
