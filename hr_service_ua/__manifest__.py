# Copyright © 2021 Garazd Creation (https://garazd.biz)
# @author: Yurii Razumovskyi (support@garazd.biz)
# @author: Iryna Razumovska (support@garazd.biz)
# License OPL-1 (https://www.odoo.com/documentation/master/legal/licenses.html#odoo-apps).

{
    'name': 'HR services of Ukraine',
    'version': '17.0.1.0.1',
    'category': 'Hidden',
    'author': 'Garazd Creation',
    'website': 'https://garazd.biz/shop/category/odoo-hr-19',
    'license': 'OPL-1',
    'summary': 'Technical extension module for HR services of Ukraine',
    'depends': [
        'hr_recruitment',
    ],
    'data': [
        'data/ir_filters_data.xml',
        'views/hr_applicant_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'price': 1.00,
    'currency': 'EUR',
    # ---------------------------
    # LIMITATIONS ON SALE AND USE
    # ---------------------------
    # This module is not sold or distributed separately.
    # It can only be delivered as part of Odoo solutions by Garazd Creation.
    # Prohibited to use this module separately from the solution with which it is supplied.
    # Contact us if you want to use the module for other purposes.
    'support': 'support@garazd.biz',
    'application': False,
    'installable': True,
    'auto_install': False,
}
