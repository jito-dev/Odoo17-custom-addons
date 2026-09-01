{
    'name': 'Payment Provider: Revolut',
    'version': '17.0.2.3.0',
    'category': 'Accounting/Payment Providers',
    'sequence': 350,
    'summary': "Accept card payments on invoices and orders through the Revolut "
               "Merchant API hosted checkout.",
    'description': """
Payment Provider: Revolut
=========================

Adds Revolut as an Odoo payment provider. When the customer clicks **Pay now**
on a portal invoice or sales order, Odoo creates a Revolut *order* through the
Merchant API and redirects the customer to the Revolut-hosted payment page
(the payment link). Revolut then notifies Odoo through a signed webhook, and
Odoo confirms the transaction and registers the payment.

* Hosted checkout — no card data ever reaches Odoo.
* Signed webhooks (HMAC SHA-256) with a replay-protection time window.
* Manual capture (authorise now, capture later) and full or partial refunds
  from the transaction form.
* Sandbox and production environments, selected by the provider state.
""",
    'author': 'JITO LTD',
    'website': 'https://jito.dev',
    'license': 'LGPL-3',
    'depends': ['payment'],
    'data': [
        'views/payment_revolut_templates.xml',
        'views/payment_provider_views.xml',
        'views/payment_transaction_views.xml',

        'data/payment_cron.xml',
        'data/payment_provider_data.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
