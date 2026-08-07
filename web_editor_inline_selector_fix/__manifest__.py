{
    'name': 'HTML Editor: Safe Inline Selectors',
    'version': '17.0.1.0.0',
    'category': 'Tools',
    'summary': 'Prevent a SyntaxError from blocking message sending when a foreign stylesheet is present',
    'description': """
HTML Editor: Safe Inline Selectors
==================================
When an HTML field is converted to email-compatible HTML, ``toInline()`` reads
every stylesheet of the document - including the ones injected by a browser
ad-blocker - and splits their selectors on commas. Commas inside quotes are not
protected by the core regex, so such a selector is torn into invalid fragments
and ``classToStyle()`` throws::

    Failed to execute 'querySelectorAll' on 'Element':
    '"][style$="position: absolute;"]' is not a valid selector.

The rejected promise blocks the user from sending the message.

This module patches ``HtmlField._toInline()`` to pre-compute the CSS rules and
drop the syntactically invalid selectors before the core uses them. Only
already-broken fragments are discarded, so no Odoo styling is lost.
Frontend-only, no data model.
    """,
    'author': 'JITO LTD',
    'website': 'https://jito.dev',
    'license': 'LGPL-3',
    'depends': ['web_editor'],
    'assets': {
        'web.assets_backend': [
            'web_editor_inline_selector_fix/static/src/js/html_field_inline_selector_fix.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
