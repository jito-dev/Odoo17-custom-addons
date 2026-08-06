# -*- coding: utf-8 -*-
"""
Export Adjusted Hours as a real Excel duration instead of a decimal number.

The standard exporter picks a cell format from the Python type of the value
(``ExportXlsxWriter.write_cell``), so every float lands as ``#,##0.00``. That
turns 1 h 10 min into ``1.17``, which reads like 1 h 17 min.

``from_data`` only receives column labels, not field names, so the columns to
treat as durations are resolved in ``base()`` — where the export payload is
still available — and handed over through the request object.

Scope is deliberately narrow: only ``account.analytic.line`` and only the fields
listed in ``DURATION_FIELDS``. Every other model and column keeps the stock
behaviour, including Hours Spent.
"""

import json
import logging

from odoo.addons.web.controllers import export
from odoo.http import request

from ..models.rounding import hours_to_excel_duration

_logger = logging.getLogger(__name__)

# Excel duration format: [h] lets the hour part exceed 24 instead of wrapping.
EXCEL_DURATION_FORMAT = '[h]:mm'

# model -> field names exported as durations
DURATION_FIELDS = {
    'account.analytic.line': {'tm_adjusted_hours'},
}


def _duration_column_indexes(params):
    """Indexes of the exported columns that must be written as durations."""
    model = params.get('model')
    field_names = DURATION_FIELDS.get(model)
    if not field_names:
        return set()

    fields_spec = params.get('fields') or []
    if model in request.env and not request.env[model]._is_an_ordinary_table():
        # base() drops the 'id' column for those models, which shifts every index
        fields_spec = [f for f in fields_spec if f.get('name') != 'id']

    return {
        index for index, field in enumerate(fields_spec)
        if field.get('name') in field_names
    }


class DurationCellMixin:
    """Writes the configured columns as Excel durations."""

    def _init_duration(self, duration_columns):
        self.duration_columns = set(duration_columns or ())
        # A dedicated format object: the base styles are mutated in place by
        # write_cell/_write_group_header, so reusing them would leak the format.
        self.duration_style = self.workbook.add_format({
            'text_wrap': True,
            'num_format': EXCEL_DURATION_FORMAT,
        })
        self.duration_header_style = self.workbook.add_format({
            'text_wrap': True,
            'bold': True,
            'bg_color': '#e9ecef',
            'num_format': EXCEL_DURATION_FORMAT,
        })

    def write_cell(self, row, column, cell_value):
        if column in self.duration_columns and isinstance(cell_value, float):
            return self.write(
                row, column, hours_to_excel_duration(cell_value), self.duration_style
            )
        return super().write_cell(row, column, cell_value)


class DurationExportXlsxWriter(DurationCellMixin, export.ExportXlsxWriter):

    def __init__(self, field_names, row_count=0, duration_columns=()):
        super().__init__(field_names, row_count)
        self._init_duration(duration_columns)


class DurationGroupExportXlsxWriter(DurationCellMixin, export.GroupExportXlsxWriter):

    def __init__(self, fields, row_count=0, duration_columns=()):
        super().__init__(fields, row_count)
        self._init_duration(duration_columns)

    def _write_group_header(self, row, column, label, group, group_depth=0):
        """Same as the stock header, with duration columns kept as durations.

        Without this the per-group subtotal of Adjusted Hours would print as a
        decimal right above rows formatted as durations.
        """
        aggregates = group.aggregated_values
        label = '%s%s (%s)' % ('    ' * group_depth, label, group.count)
        self.write(row, column, label, self.header_bold_style)

        for field in self.fields[1:]:  # first column carries the group title
            column += 1
            aggregated_value = aggregates.get(field['name'])
            if column in self.duration_columns and isinstance(aggregated_value, float):
                self.write(
                    row, column,
                    hours_to_excel_duration(aggregated_value),
                    self.duration_header_style,
                )
                continue
            if field.get('type') == 'monetary':
                self.header_bold_style.set_num_format(self.monetary_format)
            elif field.get('type') == 'float':
                self.header_bold_style.set_num_format(self.float_format)
            else:
                aggregated_value = str(
                    aggregated_value if aggregated_value is not None else ''
                )
            self.write(row, column, aggregated_value, self.header_bold_style)
        return row + 1, 0


class ExcelExport(export.ExcelExport):

    def base(self, data):
        # Resolve the duration columns while the field specification is still
        # around; from_data/from_group_data only get labels.
        #
        # This runs for EVERY xlsx export of EVERY model, so it must never be the
        # reason an export fails. Any problem resolving the columns degrades to
        # the stock decimal format instead of propagating.
        try:
            request.jito_duration_columns = _duration_column_indexes(json.loads(data))
        except Exception:  # noqa: BLE001 - deliberately never break a core export
            _logger.warning(
                "Could not resolve duration columns for the xlsx export, "
                "falling back to the standard format.", exc_info=True,
            )
            request.jito_duration_columns = set()
        return super().base(data)

    def _jito_duration_columns(self):
        return getattr(request, 'jito_duration_columns', None) or set()

    def from_data(self, fields, rows):
        duration_columns = self._jito_duration_columns()
        if not duration_columns:
            return super().from_data(fields, rows)

        with DurationExportXlsxWriter(fields, len(rows), duration_columns) as xlsx_writer:
            for row_index, row in enumerate(rows):
                for cell_index, cell_value in enumerate(row):
                    xlsx_writer.write_cell(row_index + 1, cell_index, cell_value)
        return xlsx_writer.value

    def from_group_data(self, fields, groups):
        duration_columns = self._jito_duration_columns()
        if not duration_columns:
            return super().from_group_data(fields, groups)

        with DurationGroupExportXlsxWriter(
            fields, groups.count, duration_columns
        ) as xlsx_writer:
            x, y = 1, 0
            for group_name, group in groups.children.items():
                x, y = xlsx_writer.write_group(x, y, group_name, group)
        return xlsx_writer.value
