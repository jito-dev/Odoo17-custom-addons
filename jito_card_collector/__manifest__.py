# -*- coding: utf-8 -*-
{
    'name': 'Card Collector',
    'version': '17.0.1.0.20',
    'category': 'Website/Website',
    'summary': 'Pokemon-style collectible card app with AI-generated artwork',
    'description': '''
        A collectible card game-style module for Odoo:
        - Create cards with AI-generated artwork via Google Nano Banana (Gemini)
        - Beautiful holographic card visuals with rarity tiers
        - Public gallery of shared cards
        - Personal card collection for logged-in users
        - Shareable card links with animated card view
        - 3D card flip animations and holographic shimmer effects
    ''',
    'author': 'JITO LTD',
    'website': 'https://jito.dev',
    'depends': [
        'website',
    ],
    'data': [
        # Security
        'security/card_collector_security.xml',
        'security/ir.model.access.csv',
        # Data
        'data/card_collector_data.xml',
        # Views
        'views/card_card_views.xml',
        'views/card_back_views.xml',
        'views/res_config_settings_views.xml',
        'views/menuitems.xml',
        # Website
        'views/website_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'jito_card_collector/static/src/scss/card_collector.scss',
            'jito_card_collector/static/src/js/card_collector.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
