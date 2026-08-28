{
    'name': "Portal: Bank Transfer Details",
    'version': '17.0.1.2.0',
    'category': 'Accounting/Payment',
    'summary': "Show the bank transfer details of an invoice on the customer portal, "
               "with one-click copy per field.",
    'description': """
Portal: Bank Transfer Details
=============================

A customer paying by bank transfer has to retype a dozen values into their bank:
IBAN, BIC, beneficiary, amount, reference. Stock Odoo answers that with a list of
IBANs pasted into the *Pending Message* of the Wire Transfer provider — no
beneficiary, no BIC, no amount, no reference, and the same list on every invoice
regardless of its currency.

This module replaces it with a card on the portal invoice page, built from the
invoice itself: the bank account it is actually payable to, the company as
beneficiary, the amount **still due**, and the payment reference. Every row copies
on click, and one button copies the lot as plain text.

The values shown are read, never stored: change the Recipient Bank on the invoice
and the card follows.
""",
    'author': 'JITO LTD',
    'website': 'https://jito.dev',
    'license': 'LGPL-3',
    'depends': ['account_payment', 'payment_custom'],
    'data': [
        'views/payment_provider_views.xml',
        'views/portal_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'account_portal_transfer_details/static/src/scss/transfer_card.scss',
            'account_portal_transfer_details/static/src/js/transfer_card.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
