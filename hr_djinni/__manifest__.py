# Copyright © 2024 Garazd Creation (https://garazd.biz)
# @author: Yurii Razumovskyi (support@garazd.biz)
# @author: Iryna Razumovska (support@garazd.biz)
# License OPL-1 (https://www.odoo.com/documentation/master/legal/licenses.html#odoo-apps).

{
    'name': 'Odoo Djinni Integration',
    'version': '17.0.9.0.1',
    'category': 'Human Resources/Recruitment',
    'author': 'Garazd Creation',
    'website': 'https://garazd.biz/shop/odoo-djinni-integration-239',
    'license': 'OPL-1',
    'summary': 'Odoo Djinni Integration',
    'images': ['static/description/banner.png', 'static/description/icon.png'],
    'live_test_url': 'https://garazd.biz/r/HJF',
    'depends': [
        'hr_service_ua',
        'garazd_request',
        'queue_job',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/hr_djinni_security.xml',
        'data/queue_job_channel_data.xml',
        'data/ir_cron_data.xml',
        'data/ir_config_parameter_data.xml',
        'data/utm_source_data.xml',
        'views/djinni_menus.xml',
        'views/res_config_settings.xml',
        'views/djinni_account_views.xml',
        'views/djinni_sync_log_views.xml',
        'views/hr_applicant_views.xml',
        'views/hr_job_views.xml',
        'views/djinni_quiz_views.xml',
        'wizard/djinni_create_vacancy_views.xml',
        'views/djinni_menu.xml',
        'wizard/djinni_set_ref_views.xml',
    ],
    'price': 194.00,
    'currency': 'EUR',
    'support': 'support@garazd.biz',
    'application': True,
    'installable': True,
    'auto_install': False,
}
