# -*- coding: utf-8 -*-
{
    'name': 'Expenses Dashboard (Accounting)',
    'version': '17.0.3.1.0',
    'category': 'Accounting/Accounting',
    'summary': 'Executive expense overview built on accounting entries.',
    'description': """
Expenses dashboard built on accounting data.

The standard Odoo "Expenses" dashboard reads exclusively from ``hr.expense``.
Companies that book their costs as vendor bills and journal entries instead of
employee expense reports therefore see an empty dashboard.

This module adds a spreadsheet dashboard in the Finance group that reads from
``account.move.line``, restricted to posted entries on accounts of type
``expense`` and ``expense_direct_cost``:

- KPI scorecards with prior-period deltas: total expenses, direct costs,
  operating expenses, document count, plus an unposted "In Draft" figure
- Monthly trend stacked by management expense category
- Expense structure: share per category, with the catch-all kept visible
- Top vendors and recent vendor bills
- A "Needs attention" block surfacing uncategorised spend and drafts
- Period global filter (rolling 365 days by default)

It also introduces ``jito.expense.category``: a management categorisation of
expense accounts, mirrored onto ``account.move.line`` as a stored field so the
charts can group by something readable. Odoo's own ``account.root`` renders as
bare code prefixes ("60", "61") and cannot be renamed, and ``account.group`` is
optional and largely unpopulated here.
    """,
    'author': 'Jito',
    'website': 'https://jito.dev',
    'depends': [
        'account',
        'spreadsheet_dashboard',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/expense_category_data.xml',
        'views/expense_category_views.xml',
        'views/account_account_views.xml',
        'data/expense_dashboard.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}
