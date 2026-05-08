{
    'name': 'Payroll for Contractors',
    'version': '1.5.9',
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
- Contract management per employee with legal entities and payment methods
- Salary run generation from all timesheets (validated and non-validated)
- Vendor bill creation per salary run
- Contractor invoices with DOCX/PDF generation and Odoo Sign integration
- Service agreements per contract with template management
- Revolut Business CSV batch payment export
- Ukrainian PE contract fields (bilingual UA/EN)
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
        'jito_document_template',
        'sign',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'security/hpc_employee_rules.xml',
        'security/hpc_contractor_invoice_rules.xml',
        'data/sequences.xml',
        'data/hpc_service_agreement_context_types.xml',
        'views/hpc_contract_views.xml',
        'views/hpc_salary_run_views.xml',
        'views/hpc_settings_views.xml',
        'views/hpc_batch_wizard_views.xml',
        'views/hpc_employee_portal_views.xml',
        'views/hpc_contract_revolut_views.xml',
        'views/hpc_revolut_export_wizard_views.xml',
        'views/hpc_revolut_server_action.xml',
        'views/hpc_contractor_legal_entity_views.xml',
        'views/hpc_contractor_payment_method_views.xml',
        'views/hpc_contractor_views.xml',
        'views/hpc_contract_ua_pe_views.xml',
        'views/hpc_contract_extension_views.xml',
        'views/hpc_contract_service_agreement_views.xml',
        'views/hpc_res_company_views.xml',
        'views/hpc_contract_templates_views.xml',
        'views/hpc_contractor_invoice_views.xml',
        'views/hpc_service_agreement_views.xml',
        'views/hpc_salary_run_ext_views.xml',
        'views/hpc_menus.xml',
        'views/hpc_contractor_menus.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'post_migrate': 'post_migrate_hook',
    'installable': True,
    'application': True,
    'auto_install': False,
}
