/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListRenderer } from "@web/views/list/list_renderer";

/**
 * Timesheet list with permanently visible totals.
 *
 * A single row repeated inside the sticky header (see the template) is what
 * keeps the totals on screen; the standard footer is left untouched. The values
 * come from the core `aggregates` getter, so both rows always agree.
 *
 * The row carries its own label, which is not decoration: in an ungrouped list
 * the aggregates are computed client side over the records of the loaded page
 * (`ListRenderer.aggregates`, web/views/list/list_renderer.js:687-695), so with
 * more records than the page limit they cover the page, not the whole search
 * result. Grouped lists and active selections are different - their aggregates
 * already cover everything they claim to - so there the label stays plain.
 */
export class TimesheetTotalsListRenderer extends ListRenderer {
    /**
     * @returns {boolean} true when the aggregates only cover the loaded page
     */
    get totalsArePartial() {
        const list = this.props.list;
        if (list.isGrouped || (list.selection && list.selection.length)) {
            return false;
        }
        return Boolean(list.count) && list.records.length < list.count;
    }

    /**
     * Kept short on purpose: `freezeColumnWidths()` measures the table with
     * `table-layout: auto`, so a long string here would push the columns around.
     * The full sentence lives in the tooltip instead.
     *
     * @returns {string}
     */
    get totalsLabel() {
        if (!this.totalsArePartial) {
            return _t("Totals");
        }
        return _t("Totals · %(loaded)s of %(total)s", {
            loaded: this.props.list.records.length,
            total: this.props.list.count,
        });
    }

    /**
     * @returns {string|undefined} undefined leaves the attribute off the DOM
     */
    get totalsTooltip() {
        if (!this.totalsArePartial) {
            return undefined;
        }
        return _t(
            "These totals cover the %(loaded)s records loaded on this page; " +
                "%(total)s records match the current filters.",
            { loaded: this.props.list.records.length, total: this.props.list.count }
        );
    }

    /**
     * @returns {boolean} whether any *displayed* column carries an aggregate.
     *                    `aggregates` is built from `allColumns`, so a sum can
     *                    exist for a column that is not on screen; a totals bar
     *                    with nothing to total would be pure noise.
     */
    get hasTotals() {
        const aggregates = this.aggregates;
        return this.state.columns.some((column) => aggregates[column.name]);
    }

    /**
     * Number of leading columns the label spans: everything up to the first
     * total. Spanning them rather than writing into the first cell keeps the
     * label off any single column's width - in a timesheet list that cell is
     * Date, which is far too narrow for it. `0` means the first column is
     * already a total and the label is dropped.
     *
     * @returns {number}
     */
    get totalsLabelColspan() {
        const aggregates = this.aggregates;
        const index = this.state.columns.findIndex((column) => aggregates[column.name]);
        return index === -1 ? 0 : index;
    }
}
TimesheetTotalsListRenderer.template = "tm_rate_card.TimesheetTotalsListRenderer";

export const timesheetTotalsListView = {
    ...listView,
    Renderer: TimesheetTotalsListRenderer,
};

registry.category("views").add("tm_timesheet_totals_list", timesheetTotalsListView);
