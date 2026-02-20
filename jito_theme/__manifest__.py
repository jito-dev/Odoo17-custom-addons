# -*- coding: utf-8 -*-
{
    'name': 'Jito Theme',
    'version': '17.0.1.0.0',
    'category': 'Theme',
    'summary': 'Jito custom backend theme based on fightflow-hub color palette',
    'description': """
        Jito Theme applies the fightflow-hub brand identity to the Odoo backend.

        - Primary color: blue-indigo (#2644D9)
        - Fonts: DM Sans (body), Space Grotesk (headings)
        - Full light and dark mode support
        - Semantic colors: success, warning, danger aligned with fightflow palette
    """,
    'author': 'Jito',
    'depends': ['web', 'web_enterprise'],
    'data': [
        'views/webclient_templates.xml',
    ],
    'assets': {
        # Inject our primary variables BEFORE web_enterprise so our
        # non-!default definitions win over web_enterprise's !default ones.
        'web._assets_primary_variables': [
            (
                'before',
                'web_enterprise/static/src/scss/primary_variables.scss',
                'jito_theme/static/src/scss/primary_variables.scss',
            ),
        ],
        # Dark mode variable overrides
        'web.dark_mode_variables': [
            (
                'before',
                'web_enterprise/static/src/scss/primary_variables.dark.scss',
                'jito_theme/static/src/scss/primary_variables.dark.scss',
            ),
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
