# -*- coding: utf-8 -*-
{
    'name': 'ECB Exchange Rates Downloader',
    'version': '17.0.1.0.5',
    'category': 'Accounting/Accounting',
    'summary': 'Download ECB exchange rates daily and historically for all active currencies.',
    'description': """
Download exchange rates from the European Central Bank (ECB).

Features:
- Daily automatic download via scheduled action
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
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizard/ecb_history_wizard_views.xml',
        'views/res_config_settings_views.xml',
        'data/ir_cron_data.xml',
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
