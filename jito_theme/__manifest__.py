# -*- coding: utf-8 -*-
{
    'name': 'Jito Theme',
    'version': '17.0.2.0.0',
    'category': 'Theme',
    'summary': 'Jito custom backend theme based on fightflow-hub color palette',
    'description': """
        Jito Theme applies the fightflow-hub brand identity to the Odoo backend.

        - Primary color: blue-indigo (#2644D9)
        - Fonts: DM Sans (body), Space Grotesk (headings)
        - Full light and dark mode support
        - Semantic colors: success, warning, danger aligned with fightflow palette
        - Contacts list view with circular avatar images + fightflow table styling
    """,
    'author': 'Jito',
    'depends': ['web', 'web_enterprise', 'contacts'],
    'data': [
        'views/webclient_templates.xml',
        'views/res_partner_views.xml',
    ],
    'assets': {
        # ── SCSS variable overrides ────────────────────────────────────────
        # Inject BEFORE web_enterprise so our (non-!default) definitions win.
        'web._assets_primary_variables': [
            (
                'before',
                'web_enterprise/static/src/scss/primary_variables.scss',
                'jito_theme/static/src/scss/primary_variables.scss',
            ),
        ],
        # Dark-mode variable overrides
        'web.dark_mode_variables': [
            (
                'before',
                'web_enterprise/static/src/scss/primary_variables.dark.scss',
                'jito_theme/static/src/scss/primary_variables.dark.scss',
            ),
        ],
        # ── Backend assets (JS widget + component SCSS) ───────────────────
        'web.assets_backend': [
            # OWL component template (must load before the JS that references it)
            'jito_theme/static/src/xml/contact_avatar_field.xml',
            # Custom field widget JS
            'jito_theme/static/src/js/contact_avatar_field.js',
            # Fightflow table styling + avatar styles
            'jito_theme/static/src/scss/backend.scss',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
