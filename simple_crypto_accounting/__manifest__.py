{
    'name': 'Simple Crypto Accounting',
    'version': '17.0.1.2.4',
    'category': 'Accounting/Crypto',
    'summary': 'Track ERC-20 token transactions for watched Ethereum addresses via Etherscan API.',
    'depends': ['base', 'web', 'mail'],
    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'views/sca_settings_views.xml',
        'views/sca_known_address_views.xml',
        'views/sca_watched_address_views.xml',
        'views/sca_transaction_views.xml',
        'views/menus.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': True,
}
