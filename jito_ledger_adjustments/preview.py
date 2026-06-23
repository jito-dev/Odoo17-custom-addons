# -*- coding: utf-8 -*-

"""Tiny shared HTML renderer used by the Bridge / Restate / Regroup
wizard forms to preview the would-be jito.ledger.move lines before
the user clicks the primary action.

Each wizard computes a list of dicts shaped like:

    {
        'account_code':    'MGT.SALES',
        'account_name':    'Product Sales',
        'name':            'Restate to MGT.SALES',
        'currency_symbol': '$',
        'debit':           997.00,    # company-or-tx currency
        'credit':          0.00,
    }

…and feeds it into ``render_preview_table`` which returns a safe
``markupsafe.Markup`` string for an ``fields.Html`` field. Per-currency
totals appear in a footer row so the user can sanity-check balance
before posting.
"""

from collections import defaultdict

from markupsafe import Markup, escape


def _fmt(amount, symbol):
    if not amount:
        return ''
    return '%s %s' % (escape(symbol or ''), '{:,.2f}'.format(amount))


def render_preview_table(lines):
    """Return an HTML preview table (markupsafe.Markup).

    Empty list → a muted "nothing to preview" message so the form still
    has something rendered."""
    if not lines:
        return Markup(
            '<p class="text-muted">'
            'Fill the fields above to preview the resulting move.'
            '</p>'
        )

    sums_debit = defaultdict(float)
    sums_credit = defaultdict(float)
    for line in lines:
        sym = line.get('currency_symbol') or ''
        sums_debit[sym] += line.get('debit') or 0.0
        sums_credit[sym] += line.get('credit') or 0.0

    rows = []
    for line in lines:
        rows.append(Markup(
            '<tr>'
            '<td><code>{code}</code></td>'
            '<td>{name}</td>'
            '<td class="text-end">{debit}</td>'
            '<td class="text-end">{credit}</td>'
            '</tr>'
        ).format(
            code=escape(line.get('account_code') or ''),
            name=escape(line.get('name') or ''),
            debit=_fmt(line.get('debit'), line.get('currency_symbol')),
            credit=_fmt(line.get('credit'), line.get('currency_symbol')),
        ))

    foot_rows = []
    currencies = sorted(set(sums_debit) | set(sums_credit))
    balanced = True
    for sym in currencies:
        d = sums_debit[sym]
        c = sums_credit[sym]
        balanced = balanced and abs(d - c) < 1e-6
        foot_rows.append(Markup(
            '<tr class="fw-bold border-top">'
            '<td colspan="2">Total ({sym})</td>'
            '<td class="text-end">{d}</td>'
            '<td class="text-end">{c}</td>'
            '</tr>'
        ).format(
            sym=escape(sym or 'company currency'),
            d='{:,.2f}'.format(d),
            c='{:,.2f}'.format(c),
        ))

    badge = (
        Markup('<span class="badge text-bg-success">Balanced</span>')
        if balanced else
        Markup('<span class="badge text-bg-danger">Unbalanced</span>')
    )

    return Markup(
        '<div class="o_preview_table mb-2">{badge}</div>'
        '<table class="o_list_table table table-sm w-100">'
        '<thead>'
        '<tr>'
        '<th>Account</th>'
        '<th>Label</th>'
        '<th class="text-end">Debit</th>'
        '<th class="text-end">Credit</th>'
        '</tr>'
        '</thead>'
        '<tbody>{rows}</tbody>'
        '<tfoot>{foot}</tfoot>'
        '</table>'
    ).format(
        badge=badge,
        rows=Markup('').join(rows),
        foot=Markup('').join(foot_rows),
    )
