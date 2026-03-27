# -*- coding: utf-8 -*-
{
    'name': 'ECB Exchange Rates Downloader',
    'version': '17.0.1.7.0',
    'category': 'Accounting/Accounting',
    'summary': 'Download ECB exchange rates daily and historically for all active currencies.',
    'description': """
Download exchange rates from the European Central Bank (ECB).

Features:
- Daily automatic download via scheduled action with retry and fallback
- Fallback to 90-day history feed if daily feed is unavailable
- Sync status tracking with last sync date and error display
- Admin notification on persistent download failures
- Stale rate guardrail: blocks posting invoices with outdated FX rates
- Manual force-update button
- Historical backfill wizard for a user-chosen date range (useful for migration)
- Supports all ECB-published currencies
- Rate normalization to company base currency
    """,
    'author': 'Jito',
    'website': 'https://jito.dev',
    'depends': [
        'base',
        'account',
        'mail',
        'spreadsheet_dashboard',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/ecb_security.xml',
        'wizard/ecb_history_wizard_views.xml',
        'views/res_config_settings_views.xml',
        'views/ecb_sync_dashboard_views.xml',
        'data/ir_cron_data.xml',
        'data/ecb_spreadsheet_dashboard.xml',
    ],
    'external_dependencies': {
        'python': [
            'lxml',
            'requests',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}
