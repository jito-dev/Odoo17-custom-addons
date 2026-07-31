"""Generate the "Expenses - Executive Overview" spreadsheet dashboard JSON.

Run from anywhere:  python tools/gen_dashboard.py
Writes: data/files/expense_accounting_dashboard.json

Format mirrors odoo17 spreadsheet_dashboard_hr_expense and jito_ecb_exchange_rate:
version 12 / odooVersion 4, ODOO.PIVOT / ODOO.PIVOT.HEADER / ODOO.LIST formulas.
See GUIDE.md for the reasoning behind the data model and the layout.

The trend and structure charts group by ``expense_category_id`` - a stored
related field this module adds to account.move.line. Grouping by
``account_root_id`` (the previous design) can only ever render "60", "61", ...
because account.root is an SQL view whose name is LEFT(code, 2).
"""
import json
import os

MODEL = "account.move.line"
EXPENSE_TYPES = ["expense", "expense_direct_cost"]
POSTED = ["parent_state", "=", "posted"]
BASE_DOMAIN = [["account_id.account_type", "in", EXPENSE_TYPES], POSTED]
DIRECT = [["account_id.account_type", "=", "expense_direct_cost"], POSTED]
OPERATING = [["account_id.account_type", "=", "expense"], POSTED]
# Keyed on the category, not on the account code, so it follows a re-mapping.
UNCATEGORIZED = BASE_DOMAIN + [["expense_category_id.code", "=", "uncategorized"]]
# LEFT(code, 2) = '60' - the concentration the category split is meant to break up.
ROOT_60 = BASE_DOMAIN + [["account_id.code", "=like", "60%"]]

CATEGORY_FIELD = "expense_category_id"
TREND_ID = "jito-expense-monthly-trend"
PIE_ID = "jito-expense-structure-pie"
TOP_VENDORS = 10
TOP_ACCOUNTS = 10
TOP_CATEGORIES = 9          # one row per category currently shipped
RECENT_N = 15
# Month columns in the numeric trend table. A 365-day period spans at most 13
# month buckets; unused columns render blank through IFERROR.
TREND_MONTHS = 10

TEAL = "#01666b"
RED = "#DC6965"
GREEN = "#00A04A"
AMBER = "#B26B00"

# --- styles / formats -------------------------------------------------------
STYLES = {
    "1": {"textColor": TEAL, "bold": True, "fontSize": 16},                  # section title
    "2": {"textColor": "#000000", "bold": True, "fillColor": "#ffffff", "fontSize": 10},
    "3": {"fillColor": "#f8f9fa", "fontSize": 10, "textColor": TEAL},
    "4": {"fontSize": 10, "textColor": TEAL},
    "5": {"bold": True, "align": "right", "fillColor": "#ffffff", "fontSize": 10},
    "6": {"fillColor": "#f8f9fa", "fontSize": 10, "textColor": TEAL, "align": "right"},
    "7": {"fontSize": 10, "textColor": TEAL, "align": "right"},
    "8": {"bold": True},
    "9": {"fontSize": 10, "textColor": "#777777", "italic": True},           # footnote
    "10": {"fontSize": 10, "textColor": TEAL, "italic": True},               # Others
    "11": {"fontSize": 10, "textColor": TEAL, "italic": True, "align": "right"},
    "12": {"fontSize": 10, "textColor": "#000000", "bold": True},            # Total
    "13": {"fontSize": 10, "textColor": "#000000", "bold": True, "align": "right"},
    "14": {"fontSize": 22, "bold": True, "textColor": "#000000"},            # H1
    "15": {"fontSize": 11, "textColor": "#777777"},                          # subtitle
    "16": {"fontSize": 11, "bold": True, "textColor": AMBER},                # attention label
    "17": {"fontSize": 11, "bold": True, "textColor": AMBER, "align": "right"},
}
BORDERS = {"1": {"bottom": ["thin", "#000"]}, "2": {"top": ["thin", "#000"]}}
FORMATS = {
    "1": "[$$]#,##0.00",     # headline money, full cents
    "2": "mm/dd/yyyy",
    "3": "0.0%",
    "4": "#,##0",
    "5": "[$$]#,##0",        # table money, no cents
}
CUR, DATE, PCT, INT, CUR0 = 1, 2, 3, 4, 5

HEAD, HEAD_R = 2, 5
ODD, EVEN, ODD_R, EVEN_R = 3, 4, 6, 7
OTHERS_L, OTHERS_R, TOTAL_L, TOTAL_R = 10, 11, 12, 13


def body(i, right=False):
    if right:
        return ODD_R if i % 2 else EVEN_R
    return ODD if i % 2 else EVEN


def ie(formula, fallback='""'):
    """Wrap a formula in IFERROR so an empty period renders blank, not #ERROR."""
    return "=IFERROR(%s,%s)" % (formula.lstrip("="), fallback)


# --- pivots -----------------------------------------------------------------
def pivot(pid, name, domain, measures, row_group_bys=()):
    return {
        "id": pid,
        "name": name,
        "model": MODEL,
        "rowGroupBys": list(row_group_bys),
        "colGroupBys": [],
        "measures": [{"field": m} for m in measures],
        "domain": domain,
        "context": {},
        "sortedColumn": {"groupId": [[], []], "measure": "balance", "order": "desc"},
    }


pivots = {
    # current period
    "1": pivot("1", "KPI - Total Expenses", BASE_DOMAIN, ["balance", "__count"]),
    "2": pivot("2", "KPI - Direct Costs", DIRECT, ["balance"]),
    "3": pivot("3", "KPI - Operating Expenses", OPERATING, ["balance"]),
    "4": pivot("4", "Top Vendors", BASE_DOMAIN + [["partner_id", "!=", False]],
               ["balance", "__count"], ["partner_id"]),
    "5": pivot("5", "Expense Structure", BASE_DOMAIN,
               ["balance", "__count"], [CATEGORY_FIELD]),
    # same measures, shifted one period back (see globalFilters offset below)
    "6": pivot("6", "KPI - Total Expenses (previous)", BASE_DOMAIN, ["balance", "__count"]),
    "7": pivot("7", "KPI - Direct Costs (previous)", DIRECT, ["balance"]),
    "8": pivot("8", "KPI - Operating Expenses (previous)", OPERATING, ["balance"]),
    # data-quality signals
    "9": pivot("9", "KPI - In Draft",
               [["account_id.account_type", "in", EXPENSE_TYPES],
                ["parent_state", "=", "draft"]], ["balance", "__count"]),
    "10": pivot("10", "Attention - Uncategorized", UNCATEGORIZED, ["balance", "__count"]),
    "11": pivot("11", "Attention - Root 60 concentration", ROOT_60, ["balance"]),
    # Category x month matrix. Same numbers as the stacked bar chart, but read
    # through ODOO.PIVOT cells - the mechanism the ranking tables already use.
    "12": pivot("12", "Monthly trend by category", BASE_DOMAIN, ["balance"],
                [CATEGORY_FIELD]),
    "13": pivot("13", "Top Expense Accounts", BASE_DOMAIN,
                ["balance", "__count"], ["account_id"]),
}
pivots["12"]["colGroupBys"] = ["date:month"]

lists = {
    "1": {
        "id": "1",
        "name": "Recent Vendor Bills",
        "model": MODEL,
        "columns": ["partner_id", "date", "move_id", CATEGORY_FIELD, "balance"],
        # Purchase journals only: keeps FX revaluation entries and bank-fee
        # micro-lines out of the list. The KPIs above stay unfiltered.
        "domain": BASE_DOMAIN + [["journal_id.type", "=", "purchase"]],
        "context": {},
        "orderBy": [{"name": "date", "asc": False}],
    },
}

# --- global filter ----------------------------------------------------------
# offset -1 on a "relative / last_year" range shifts the window back 365 days
# (spreadsheet/static/src/global_filters/helpers.js).
CURRENT_PIVOTS = ["1", "2", "3", "4", "5", "9", "10", "11", "12", "13"]
PREVIOUS_PIVOTS = ["6", "7", "8"]


def date_match(offset=0):
    return {"field": "date", "type": "date", "offset": offset}


global_filters = [{
    "id": "jito-expense-period",
    "type": "date",
    "label": "Period",
    "defaultValue": "last_year",
    "rangeType": "relative",
    "defaultsToCurrentPeriod": True,
    "pivotFields": dict(
        [(p, date_match(0)) for p in CURRENT_PIVOTS]
        + [(p, date_match(-1)) for p in PREVIOUS_PIVOTS]
    ),
    "listFields": {"1": date_match(0)},
    "graphFields": {TREND_ID: date_match(0), PIE_ID: date_match(0)},
}]

# --- Dashboard sheet --------------------------------------------------------
cells = {}


def put(ref, **kw):
    cells[ref] = {k: v for k, v in kw.items() if v is not None}


TOTAL_CELL = "Data!$B$1"
DOCS_CELL = "Data!$B$4"

# Row 1-2 carry the title; the figures float over rows 3..~22.
put("A1", style=14, content='=_t("Expenses - Executive Overview")')
put("A2", style=15,
    content='=_t("Period: last 365 days (\'last_year\' is a rolling 365 days, '
            'not a calendar year). Posted entries on expense accounts, company currency.")')

TOP_ROW = 25


def ranking_table(cols, title, pivot_id, group_field, entity_header, top_n,
                  start_row, caption=None):
    """Emit a top-N table followed by an Others and a Total row."""
    c_ent, c_docs, c_amt, c_pct = cols
    put("%s%d" % (c_ent, start_row), style=1, content='=_t("%s")' % title, border=1)
    for c in (c_docs, c_amt, c_pct):
        put("%s%d" % (c, start_row), border=1)

    hdr = start_row + 1
    put("%s%d" % (c_ent, hdr), style=HEAD, content='=_t("%s")' % entity_header, border=2)
    put("%s%d" % (c_docs, hdr), style=HEAD_R, content='=_t("Docs")', border=2)
    put("%s%d" % (c_amt, hdr), style=HEAD_R, content='=_t("Amount")', border=2)
    put("%s%d" % (c_pct, hdr), style=HEAD_R, content='=_t("%")', border=2)

    for i in range(1, top_n + 1):
        r = hdr + i
        pos = '"#%s",%d' % (group_field, i)
        put("%s%d" % (c_ent, r), style=body(i),
            content=ie('ODOO.PIVOT.HEADER(%s,%s)' % (pivot_id, pos)))
        put("%s%d" % (c_docs, r), style=body(i, True), format=INT,
            content=ie('ODOO.PIVOT(%s,"__count",%s)' % (pivot_id, pos)))
        put("%s%d" % (c_amt, r), style=body(i, True), format=CUR0,
            content=ie('ODOO.PIVOT(%s,"balance",%s)' % (pivot_id, pos)))
        put("%s%d" % (c_pct, r), style=body(i, True), format=PCT,
            content=ie('%s%d/%s' % (c_amt, r, TOTAL_CELL), "0"))

    first, last = hdr + 1, hdr + top_n
    others = last + 1
    put("%s%d" % (c_ent, others), style=OTHERS_L, content='=_t("Others")')
    put("%s%d" % (c_docs, others), style=OTHERS_R, format=INT,
        content=ie('%s-SUM(%s%d:%s%d)' % (DOCS_CELL, c_docs, first, c_docs, last), "0"))
    put("%s%d" % (c_amt, others), style=OTHERS_R, format=CUR0,
        content=ie('%s-SUM(%s%d:%s%d)' % (TOTAL_CELL, c_amt, first, c_amt, last), "0"))
    put("%s%d" % (c_pct, others), style=OTHERS_R, format=PCT,
        content=ie('%s%d/%s' % (c_amt, others, TOTAL_CELL), "0"))

    total = others + 1
    put("%s%d" % (c_ent, total), style=TOTAL_L, content='=_t("Total")', border=2)
    put("%s%d" % (c_docs, total), style=TOTAL_R, format=INT, border=2,
        content=ie(DOCS_CELL, "0"))
    put("%s%d" % (c_amt, total), style=TOTAL_R, format=CUR0, border=2,
        content=ie(TOTAL_CELL, "0"))
    put("%s%d" % (c_pct, total), style=TOTAL_R, border=2)

    if caption:
        put("%s%d" % (c_ent, total + 1), style=9, content='=_t("%s")' % caption)
        return total + 1
    return total


MONTH_COLS = [chr(ord("B") + i) for i in range(TREND_MONTHS)]   # B..K
TOTAL_COL = chr(ord("B") + TREND_MONTHS)                        # L


def trend_table(start_row):
    """Category x month matrix - the stacked chart's numbers, as cells.

    Charts are live queries handled by GraphModel; these cells go through the
    ordinary pivot data source. Having both means the monthly trend stays
    readable even when the chart cannot draw.
    """
    put("A%d" % start_row, style=1,
        content='=_t("Monthly trend by category")', border=1)
    for c in MONTH_COLS + [TOTAL_COL]:
        put("%s%d" % (c, start_row), border=1)

    hdr = start_row + 1
    put("A%d" % hdr, style=HEAD, content='=_t("Category")', border=2)
    for j, col in enumerate(MONTH_COLS, start=1):
        put("%s%d" % (col, hdr), style=HEAD_R, border=2,
            content=ie('ODOO.PIVOT.HEADER(12,"#date",%d)' % j))
    put("%s%d" % (TOTAL_COL, hdr), style=HEAD_R, content='=_t("Total")', border=2)

    for i in range(1, TOP_CATEGORIES + 1):
        r = hdr + i
        put("A%d" % r, style=body(i),
            content=ie('ODOO.PIVOT.HEADER(12,"#%s",%d)' % (CATEGORY_FIELD, i)))
        for j, col in enumerate(MONTH_COLS, start=1):
            put("%s%d" % (col, r), style=body(i, True), format=CUR0,
                content=ie('ODOO.PIVOT(12,"balance","#%s",%d,"#date",%d)'
                           % (CATEGORY_FIELD, i, j)))
        put("%s%d" % (TOTAL_COL, r), style=body(i, True), format=CUR0,
            content=ie('ODOO.PIVOT(12,"balance","#%s",%d)' % (CATEGORY_FIELD, i)))

    total = hdr + TOP_CATEGORIES + 1
    put("A%d" % total, style=TOTAL_L, content='=_t("Total")', border=2)
    for j, col in enumerate(MONTH_COLS, start=1):
        put("%s%d" % (col, total), style=TOTAL_R, format=CUR0, border=2,
            content=ie('ODOO.PIVOT(12,"balance","#date",%d)' % j))
    put("%s%d" % (TOTAL_COL, total), style=TOTAL_R, format=CUR0, border=2,
        content=ie(TOTAL_CELL, "0"))

    put("A%d" % (total + 1), style=9,
        content='=_t("Same figures as the stacked chart above. Months run oldest '
                'to newest; columns beyond the selected period stay blank.")')
    return total + 1


trend_last = trend_table(TOP_ROW)

structure_last = ranking_table(
    ("A", "B", "C", "D"), "Expense structure", 5, CATEGORY_FIELD, "Category",
    TOP_CATEGORIES, trend_last + 2,
    caption="Categories are exhaustive; Others catches any category added later.")

vendors_last = ranking_table(
    ("A", "B", "C", "D"), "Top vendors", 4, "partner_id", "Vendor",
    TOP_VENDORS, structure_last + 2,
    caption="Others is a remainder (Total minus the top 10). It also absorbs "
            "lines with no partner, so the table ties to the KPI even though no "
            "single vendor explains it.")

accounts_last = ranking_table(
    ("A", "B", "C", "D"), "Top expense accounts", 13, "account_id", "Account",
    TOP_ACCOUNTS, vendors_last + 2,
    caption="Account-level detail behind the categories above.")

# --- Recent Vendor Bills ----------------------------------------------------
REC_ROW = accounts_last + 2
put("A%d" % REC_ROW, style=1, content='=_t("Recent vendor bills")', border=1)
for c in "BCD":
    put("%s%d" % (c, REC_ROW), border=1)
for col, label, st in [("A", "Vendor", HEAD), ("B", "Date", HEAD),
                       ("C", "Reference", HEAD), ("D", "Amount", HEAD_R)]:
    put("%s%d" % (col, REC_ROW + 1), style=st, content='=_t("%s")' % label, border=2)
for i in range(1, RECENT_N + 1):
    r = REC_ROW + 1 + i
    put("A%d" % r, style=body(i), content=ie('ODOO.LIST(1,%d,"partner_id")' % i))
    put("B%d" % r, style=body(i), format=DATE, content=ie('ODOO.LIST(1,%d,"date")' % i))
    put("C%d" % r, style=body(i), content=ie('ODOO.LIST(1,%d,"move_id")' % i))
    put("D%d" % r, style=body(i, True), format=CUR0,
        content=ie('ODOO.LIST(1,%d,"balance")' % i))

NOTE_ROW = REC_ROW + RECENT_N + 2
put("A%d" % NOTE_ROW, style=9,
    content='=_t("KPIs cover all posted entries on expense accounts. This list shows '
            'purchase-journal documents only, so FX revaluation and bank fees are excluded.")')

# --- Needs attention --------------------------------------------------------
ATT_ROW = NOTE_ROW + 2
put("A%d" % ATT_ROW, style=1, content='=_t("Needs attention")', border=1)
for c in "BCD":
    put("%s%d" % (c, ATT_ROW), border=1)

ATTENTION = [
    ("Uncategorized", "Data!$B$7", "Data!$C$7", CUR0, PCT,
     "Money sits in account 600000 \'Expenses\'. No grouping fixes this - the "
     "account must be broken out into real categories."),
    ("Concentration", "Data!$B$8", "Data!$C$8", CUR0, PCT,
     "Share of spend on accounts whose code starts with 60: subcontractor work, "
     "platform fees and the catch-all. Shown because it drove the old chart into "
     "a single unreadable series."),
    ("Drafts", "Data!$B$5", "Data!$B$6", CUR0, INT,
     "Unposted documents are not in Total, but are shown separately so they do "
     "not get lost."),
]
row = ATT_ROW + 1
for label, value_cell, second_cell, fmt_a, fmt_b, explanation in ATTENTION:
    put("A%d" % row, style=16, content='=_t("%s")' % label)
    put("B%d" % row, style=17, format=fmt_a, content=ie(value_cell, "0"))
    put("C%d" % row, style=17, format=fmt_b, content=ie(second_cell, "0"))
    put("A%d" % (row + 1), style=9, content='=_t("%s")' % explanation)
    row += 2

LAST_ROW = row + 1

# --- figures ----------------------------------------------------------------
def scorecard(fid, title, x, key, baseline=None, descr="vs previous period"):
    data = {
        "title": title, "type": "scorecard", "background": "#FFFFFF",
        "keyValue": key, "baselineMode": "difference",
        "baselineColorUp": RED,      # spending more than last period is bad
        "baselineColorDown": GREEN,
    }
    if baseline:
        data["baseline"] = baseline
        data["baselineDescr"] = descr
    return {"id": fid, "x": x, "y": 52, "width": 200, "height": 120,
            "tag": "chart", "data": data}


def odoo_chart(fid, title, chart_type, x, y, width, height, group_by,
               domain=None, stacked=False, legend="right"):
    return {
        "id": fid, "x": x, "y": y, "width": width, "height": height, "tag": "chart",
        "data": {
            "title": title, "background": "#FFFFFF", "legendPosition": legend,
            "type": chart_type, "verticalAxisPosition": "left", "stacked": stacked,
            "metaData": {
                "groupBy": list(group_by), "measure": "balance",
                "order": None, "resModel": MODEL,
            },
            "searchParams": {
                "comparison": None, "context": {},
                "domain": domain if domain is not None else BASE_DOMAIN,
                "groupBy": list(group_by), "orderBy": [],
            },
        },
    }


figures = [
    scorecard("jito-sc-total", "Total expenses", 0, "Data!B1", "Data!C1"),
    scorecard("jito-sc-direct", "Direct costs", 210, "Data!B2", "Data!C2"),
    scorecard("jito-sc-operating", "Operating", 420, "Data!B3", "Data!C3"),
    scorecard("jito-sc-docs", "Documents", 630, "Data!B4", "Data!C4"),
    scorecard("jito-sc-draft", "In draft", 840, "Data!B5"),
    odoo_chart(TREND_ID, "Monthly trend by category", "odoo_bar",
               0, 192, 720, 300, ["date:month", CATEGORY_FIELD], stacked=True),
    odoo_chart(PIE_ID, "Expense structure", "odoo_pie",
               730, 192, 400, 300, [CATEGORY_FIELD], legend="right"),
]

# Negative amounts (credit notes, FX gains) in red.
conditional_formats = [{
    "id": "jito-negative-amounts",
    "ranges": ["B%d:%s%d" % (TOP_ROW + 2, TOTAL_COL, trend_last),
               "C%d:C%d" % (TOP_ROW, accounts_last),
               "D%d:D%d" % (REC_ROW + 2, REC_ROW + 1 + RECENT_N)],
    "rule": {"type": "CellIsRule", "operator": "LessThan",
             "values": ["0"], "style": {"textColor": RED}},
}]

# --- Data sheet -------------------------------------------------------------
data_cells = {}
kpis = [
    ("Total Expenses", 'ODOO.PIVOT(1,"balance")', 'ODOO.PIVOT(6,"balance")', CUR),
    ("Direct Costs", 'ODOO.PIVOT(2,"balance")', 'ODOO.PIVOT(7,"balance")', CUR),
    ("Operating Expenses", 'ODOO.PIVOT(3,"balance")', 'ODOO.PIVOT(8,"balance")', CUR),
    ("Documents", 'ODOO.PIVOT(1,"__count")', 'ODOO.PIVOT(6,"__count")', INT),
    ("In Draft", 'ODOO.PIVOT(9,"balance")', None, CUR),
]
for i, (label, cur_f, prev_f, fmt) in enumerate(kpis, start=1):
    data_cells["A%d" % i] = {"style": 8, "content": '=_t("%s")' % label}
    data_cells["B%d" % i] = {"content": ie(cur_f, "0"), "format": fmt}
    if prev_f:
        data_cells["C%d" % i] = {"content": ie(prev_f, "0"), "format": fmt}

# Row 6-8: the "needs attention" figures. Column C carries the share of total.
data_cells["A6"] = {"style": 8, "content": '=_t("In Draft - documents")'}
data_cells["B6"] = {"content": ie('ODOO.PIVOT(9,"__count")', "0"), "format": INT}

data_cells["A7"] = {"style": 8, "content": '=_t("Uncategorized")'}
data_cells["B7"] = {"content": ie('ODOO.PIVOT(10,"balance")', "0"), "format": CUR}
data_cells["C7"] = {"content": ie("B7/B1", "0"), "format": PCT}

data_cells["A8"] = {"style": 8, "content": '=_t("Root 60 concentration")'}
data_cells["B8"] = {"content": ie('ODOO.PIVOT(11,"balance")', "0"), "format": CUR}
data_cells["C8"] = {"content": ie("B8/B1", "0"), "format": PCT}

# --- document ---------------------------------------------------------------
doc = {
    "version": 12,
    "odooVersion": 4,
    "revisionId": "jito-expense-dashboard-v4",
    "sheets": [
        {
            "id": "sheet1", "name": "Dashboard",
            # A carries every row label (category / vendor / account / month),
            # B..K are the month columns of the trend table and double as the
            # Docs / Amount / % columns of the ranking tables, L is Total.
            "colNumber": 14, "rowNumber": LAST_ROW + 3,
            "rows": {}, "cols": {
                "0": {"size": 240}, "1": {"size": 100}, "2": {"size": 110},
                "3": {"size": 95}, "4": {"size": 95}, "5": {"size": 95},
                "6": {"size": 95}, "7": {"size": 95}, "8": {"size": 95},
                "9": {"size": 95}, "10": {"size": 110},
            },
            "merges": [], "cells": cells,
            "conditionalFormats": conditional_formats,
            "figures": figures, "areGridLinesVisible": False, "isVisible": True,
        },
        {
            "id": "sheet2", "name": "Data",
            "colNumber": 4, "rowNumber": 12,
            "rows": {}, "cols": {"0": {"size": 200}, "1": {"size": 140},
                                 "2": {"size": 140}},
            "merges": [], "cells": data_cells, "conditionalFormats": [],
            "figures": [], "areGridLinesVisible": True, "isVisible": False,
        },
    ],
    "entities": {},
    "styles": STYLES,
    "formats": FORMATS,
    "borders": BORDERS,
    "settings": {"locale": {
        "name": "English (US)", "code": "en_US", "thousandsSeparator": ",",
        "decimalSeparator": ".", "dateFormat": "mm/dd/yyyy",
        "timeFormat": "hh:mm:ss", "formulaArgSeparator": ",",
    }},
    "chartOdooMenusReferences": {},
    "lists": lists,
    "listNextId": 2,
    "pivots": pivots,
    "pivotNextId": 14,
    "globalFilters": global_filters,
}

out = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "files", "expense_accounting_dashboard.json",
)
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w") as fh:
    json.dump(doc, fh, indent=1)
print("written", out, os.path.getsize(out), "bytes")
