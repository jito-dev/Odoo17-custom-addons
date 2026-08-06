# -*- coding: utf-8 -*-
"""
Requirement A: Adjusted Hours must leave the XLSX export as a duration.

The workbook is produced by the real writer and then read back straight from the
zip container — xlsxwriter can only write and openpyxl is not installed here, so
``xl/styles.xml`` (number formats) and ``xl/worksheets/sheet1.xml`` (raw values)
are parsed by hand. That checks the actual bytes Excel will open, not just the
Python-side conversion.
"""

import io
import zipfile
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import patch

from odoo.addons.web.controllers import export as web_export
from odoo.tests import tagged

from ..controllers.export_xlsx import (
    EXCEL_DURATION_FORMAT,
    DurationExportXlsxWriter,
    _duration_column_indexes,
)
from ..models.rounding import hours_to_excel_duration
from .common import TimesheetRoundingCommon

MAIN_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'

# The four durations from the specification.
CASES = [
    (1 / 3, '00:20'),
    (2 / 3, '00:40'),
    (7 / 6, '01:10'),
    (1.25, '01:15'),
]


@tagged('post_install', '-at_install')
class TestExportFormat(TimesheetRoundingCommon):

    def _fake_request(self):
        return SimpleNamespace(env=self.env)

    def _build_workbook(self, values, duration_columns):
        """Run the real writer and return the produced xlsx bytes."""
        with patch.object(web_export, 'request', self._fake_request()):
            with DurationExportXlsxWriter(
                ['Hours Spent', 'Adjusted Hours'],
                len(values),
                duration_columns,
            ) as writer:
                for row_index, row in enumerate(values):
                    for column, cell_value in enumerate(row):
                        writer.write_cell(row_index + 1, column, cell_value)
        return writer.value

    @staticmethod
    def _parse(content):
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            styles = ET.fromstring(archive.read('xl/styles.xml'))
            sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        return styles, sheet

    @staticmethod
    def _column_values(sheet, letter):
        """Data cells of one column, in row order.

        Row 1 is the header and its cells hold shared-string indexes, not values,
        so it is skipped — reading it as a number is how the first version of
        this helper turned a 02:00 total into 26:00.
        """
        cells = {}
        for cell in sheet.iter('{%s}c' % MAIN_NS):
            ref = cell.get('r') or ''
            node = cell.find('{%s}v' % MAIN_NS)
            if not ref.startswith(letter) or node is None:
                continue
            if cell.get('t') == 's':  # shared string
                continue
            row = int(ref[len(letter):])
            if row == 1:
                continue
            cells[row] = node.text
        return [cells[key] for key in sorted(cells)]

    # ------------------------------------------------------------------

    def test_conversion_matches_expected_durations(self):
        """00:20, 00:40, 01:10, 01:15 survive the round trip."""
        for hours, expected in CASES:
            day_fraction = hours_to_excel_duration(hours)
            minutes = round(day_fraction * 24 * 60)
            self.assertEqual('%02d:%02d' % divmod(minutes, 60), expected)

    def test_duration_format_is_registered_in_the_workbook(self):
        content = self._build_workbook([[1.25, 7 / 6]], duration_columns={1})
        styles, _sheet = self._parse(content)

        formats = [
            node.get('formatCode') for node in styles.iter('{%s}numFmt' % MAIN_NS)
        ]
        self.assertIn(EXCEL_DURATION_FORMAT, formats)

    def test_adjusted_hours_written_as_day_fraction(self):
        rows = [[hours, hours] for hours, _label in CASES]
        content = self._build_workbook(rows, duration_columns={1})
        _styles, sheet = self._parse(content)

        exported = [float(value) for value in self._column_values(sheet, 'B')]
        self.assertEqual(len(exported), len(CASES))
        for actual, (hours, _label) in zip(exported, CASES):
            self.assertAlmostEqual(actual, hours_to_excel_duration(hours), places=12)

    def test_hours_spent_stays_decimal(self):
        """Explicit requirement: the Hours Spent column is not converted."""
        rows = [[hours, hours] for hours, _label in CASES]
        content = self._build_workbook(rows, duration_columns={1})
        _styles, sheet = self._parse(content)

        exported = [float(value) for value in self._column_values(sheet, 'A')]
        for actual, (hours, _label) in zip(exported, CASES):
            self.assertAlmostEqual(actual, hours, places=12)

    def test_sums_stay_correct(self):
        """Requirement A.5: three 00:40 entries must total 02:00, not 02:01."""
        rows = [[2 / 3, 2 / 3] for _ in range(3)]
        content = self._build_workbook(rows, duration_columns={1})
        _styles, sheet = self._parse(content)

        total = sum(float(value) for value in self._column_values(sheet, 'B'))
        minutes = round(total * 24 * 60)
        self.assertEqual('%02d:%02d' % divmod(minutes, 60), '02:00')

    # -- column resolution ---------------------------------------------

    def test_duration_columns_detected_for_timesheets(self):
        params = {
            'model': 'account.analytic.line',
            'fields': [
                {'name': 'date', 'label': 'Date'},
                {'name': 'unit_amount', 'label': 'Hours Spent'},
                {'name': 'tm_adjusted_hours', 'label': 'Adjusted Hours'},
            ],
        }
        with patch('odoo.addons.jito_timesheet_rounding.controllers.export_xlsx.request',
                   self._fake_request()):
            self.assertEqual(_duration_column_indexes(params), {2})

    def test_no_duration_columns_for_other_models(self):
        params = {
            'model': 'res.partner',
            'fields': [{'name': 'name', 'label': 'Name'}],
        }
        with patch('odoo.addons.jito_timesheet_rounding.controllers.export_xlsx.request',
                   self._fake_request()):
            self.assertEqual(_duration_column_indexes(params), set())
