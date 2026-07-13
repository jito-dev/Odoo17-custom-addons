{
    'name': 'Simple Crypto Accounting',
    'version': '17.0.11.1.0',
    'category': 'Accounting/Crypto',
    'summary': 'Track ERC-20 (Etherscan) and TRC-20 (Tronscan) token '
               'transactions for watched wallets; inject directly into the '
               'Management Ledger (jito.ledger.move) with provenance traces.',
    'depends': [
        'base', 'web', 'mail', 'account',
        'jito_ledger_nl',           # jito.ledger.move + jito.ledger.move.line
        'jito_ledger_adjustments',  # jito.ledger.trace + crypto_tx payload schema
        'jito_crypto_currencies',   # seeded res.currency records: USDC/USDT/DAI/BTC/ETH
    ],
    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'data/sca_token_preset.xml',
        'views/sca_settings_views.xml',
        'views/sca_known_address_views.xml',
        'views/sca_contact_views.xml',
        'views/sca_token_preset_views.xml',
        'views/sca_watched_address_views.xml',
        'views/sca_transaction_views.xml',
        'views/sca_mgt_ledger_map_views.xml',
        'views/sca_accounting_views.xml',
        'views/menus.xml',
        'views/sca_price_candle_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': True,
}
