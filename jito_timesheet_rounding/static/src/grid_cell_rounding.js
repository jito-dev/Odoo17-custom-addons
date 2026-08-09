/** @odoo-module **/

/**
 * Make the grid show what was actually stored, not what was typed.
 *
 * `GridCell._update` (web_grid/static/src/views/grid_model.js) sends the new
 * cell value to `grid_update_cell` and then does
 * `this.row.updateCell(this.column, value)` — with the value it just sent, not
 * with the one the server kept. When this module rounds a duration on write,
 * the cell therefore keeps showing the typed number until the grid is reloaded.
 * The stored value was right all along; only the display lagged, which reads as
 * "the setting is not working".
 *
 * Cells do not go through onchange, so the form-view correction cannot help
 * here. Instead we re-read the cell after the update and, if the server kept a
 * different number, correct the cell in place.
 *
 * Why re-read instead of rounding in the browser: a cell is the *sum* of the
 * lines under it, while `grid_update_cell` applies the difference to a single
 * line. With more than one line in a cell — an approved entry next to a new one
 * — rounding the total is not the same arithmetic as rounding the line the
 * server actually touched, and the two would disagree. Asking is always right.
 *
 * The read is one `read_group` scoped to this one cell, and it only happens when
 * the company has rounding switched on (see `ir_http.py::session_info`) and the
 * user genuinely changed the cell.
 */

import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";
import { GridCell } from "@web_grid/views/grid_model";

const TIMESHEET_MODEL = "account.analytic.line";

patch(GridCell.prototype, {
    async _update(value) {
        const previousValue = this.value;
        await super._update(...arguments);

        if (!session.timesheet_rounding_step || this.model.resModel !== TIMESHEET_MODEL) {
            return; // rounding is off, or this is some other grid entirely
        }
        if (value === previousValue) {
            return; // `grid_update_cell` returns early on a zero difference
        }
        if (this.value !== value) {
            // The server answered with an action instead of writing (no project
            // on the row, timesheets disabled). Nothing was stored to re-read.
            return;
        }

        const storedValue = await this._fetchStoredValue();
        if (storedValue !== null && storedValue !== this.value) {
            // updateCell works in deltas, so this also fixes the row, column and
            // section totals that were added up from the typed value.
            this.row.updateCell(this.column, storedValue);
            this.model.notify();
        }
    },

    /**
     * The measure this cell really holds now, straight from the database.
     *
     * @returns {Promise<number|null>} null when the cell could not be read
     */
    async _fetchStoredValue() {
        const measureFieldName = this.model.measureFieldName;
        let groups;
        try {
            groups = await this.model.orm.readGroup(
                this.model.resModel,
                this.domain.toList({}),
                [measureFieldName],
                [],
                { context: this.context, lazy: false }
            );
        } catch {
            // Never let a cosmetic correction break the edit that succeeded.
            return null;
        }
        if (!groups?.length) {
            return null;
        }
        return groups[0][measureFieldName] || 0;
    },
});
