{
    'name': 'Helpdesk Quick Report',
    'version': '17.0.1.4.0',
    'category': 'Services/Helpdesk',
    'summary': 'Shift+Right-Click to report issues with auto-captured context',
    'description': """
        Adds a Shift+Right-Click context menu to the Odoo web client
        that lets internal users instantly create Helpdesk tickets
        with auto-captured screenshots, page context, and environment metadata.
    """,
    'author': 'Jito',
    'depends': ['helpdesk', 'web'],
    'data': [
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'jito_helpdesk_quick_report/static/src/xml/quick_report_dialog.xml',
            'jito_helpdesk_quick_report/static/src/scss/quick_report.scss',
            'jito_helpdesk_quick_report/static/src/js/quick_report_dialog.js',
            'jito_helpdesk_quick_report/static/src/js/quick_report_service.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
