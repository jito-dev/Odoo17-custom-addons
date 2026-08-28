{
    'name': 'Bank Account Internal Name',
    'version': '17.0.1.7.1',
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

It also makes the invoice's *Recipient Bank* **follow the document currency**: a
USD invoice defaults to the USD account, a EUR invoice to the EUR one, instead of
whichever account happens to come first. Ties between two accounts of the same
currency are broken by `sequence`, so the default is a choice you drag in the list.
The field stays editable — any account can still be picked by hand.
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
