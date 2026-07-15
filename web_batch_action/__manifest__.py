{
    'name': 'Batch Action Processing',
    'version': '17.0.1.3.0',
    'category': 'Tools',
    'summary': 'Run list-view Server Actions on a large selection in client-driven batches',
    'description': """
Batch Action Processing
=======================
Adds a "Batch" checkbox + size input next to the list view's **Actions** button.
When enabled, running a Server Action on a selection of N records processes it in
sequential slices of the configured size (default 100) — e.g. 10 000 records in
batches of 100 = 100 runs — with a live progress dialog, cancel, and per-batch
failure reporting (continue-on-error). Generic: works on every list view, no
per-model code. Frontend-only (patches the web ActionMenus component).
    """,
    'author': 'JITO LTD',
    'website': 'https://jito.dev',
    'license': 'LGPL-3',
    'depends': ['web'],
    'assets': {
        'web.assets_backend': [
            'web_batch_action/static/src/batch_progress_dialog.xml',
            'web_batch_action/static/src/batch_progress_dialog.js',
            'web_batch_action/static/src/action_menus_batch.xml',
            'web_batch_action/static/src/action_menus_batch.js',
            'web_batch_action/static/src/batch_action.scss',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
