{
    'name': 'Bank Account Internal Name',
    'version': '17.0.1.5.0',
    'category': 'Accounting',
    'summary': 'Give bank accounts a human-friendly internal name and search by it',
    'description': """
Bank Account Internal Name
==========================
Bank accounts are normally shown only by their IBAN / account number, which is
hard to recognise and easy to mis-pick. This module adds an **Internal Name**
field to bank accounts (e.g. "jito.eur.internal") and makes **every** bank-account
selector searchable by it — so you can type the internal name in the customer
invoice's *Recipient Bank* field (or any payment / bank selector) and it resolves
to the right account.
    """,
    'author': 'JITO LTD',
    'website': 'https://jito.dev',
    'license': 'LGPL-3',
    'depends': ['base', 'account'],
    'data': [
        'views/res_partner_bank_views.xml',
        'views/account_move_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
