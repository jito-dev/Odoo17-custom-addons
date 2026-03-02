{
    'name': 'Payroll for Contractors',
    'version': '1.2.2',
    'category': 'Human Resources/Payroll',
    'summary': 'Manage contractor payroll based on timesheets',
    'description': """
Payroll for Contractors
=======================
Manages contractor payroll with support for:
- Hourly contracting (rate * hours worked)
- Monthly with tracking (proportional to hours fulfilled)
- Monthly fixed (flat monthly compensation)

Features:
- Contract management per employee
- Salary run generation from all timesheets (validated and non-validated)
- Vendor bill creation per salary run
- Dashboard with period navigation
- Batch salary run creation wizard
    """,
    'author': 'JITO LTD',
    'website': 'https://jito.dev',
    'license': 'LGPL-3',
    'depends': [
        'hr',
        'project',
        'hr_timesheet',
        'timesheet_grid',
        'account',
        'mail',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/sequences.xml',
        'views/hpc_contract_views.xml',
        'views/hpc_salary_run_views.xml',
        'views/hpc_settings_views.xml',
        'views/hpc_batch_wizard_views.xml',
        'views/hpc_menus.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'post_migrate': 'post_migrate_hook',
    'installable': True,
    'application': True,
    'auto_install': False,
}
