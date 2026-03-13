# -*- coding: utf-8 -*-
{
    'name': "Dev Cost Estimator",
    'website': "https://jito.dev",
    'category': 'Human Resources/Recruitment',
    'version': '17.0.1.26.0',
    'depends': ['base', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'data/category_data.xml',
        'views/cost_estimator.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'dev_cost_estimator/static/lib/d3/d3.min.js',
            'dev_cost_estimator/static/src/xml/salary_chart_widget.xml',
            'dev_cost_estimator/static/src/xml/multi_salary_chart_widget.xml',
            'dev_cost_estimator/static/src/scss/salary_chart_widget.scss',
            'dev_cost_estimator/static/src/js/salary_chart_widget.js',
            'dev_cost_estimator/static/src/js/multi_salary_chart_widget.js',
            'dev_cost_estimator/static/src/js/pdf_export.js',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'application': True,
}
