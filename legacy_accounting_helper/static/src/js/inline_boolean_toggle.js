/** @odoo-module **/

import { registry } from "@web/core/registry";
import {
    listBooleanToggleField,
    ListBooleanToggleField,
} from "@web/views/fields/boolean_toggle/list_boolean_toggle_field";

/**
 * A boolean toggle that can be flipped directly from a **non-editable** tree
 * (the stock `boolean_toggle`/`list.boolean_toggle` only toggles when the row is
 * already in edition, i.e. in an editable list).
 *
 * On click we:
 *   - `stopPropagation()` so the click does NOT also open the row's form view,
 *   - `preventDefault()` so the native checkbox doesn't double-toggle (its own
 *     onChange is suppressed; we drive the value ourselves),
 *   - write the flipped value with `{ save: true }` so it persists immediately.
 *
 * `props.readonly` is honoured: in a top-level non-editable list it is false for
 * a non-readonly field (see ListRenderer.isRecordReadonly), so the toggle is live;
 * a `readonly` modifier still disables it.
 */
export class InlineBooleanToggleField extends ListBooleanToggleField {
    async onClick(ev) {
        ev.stopPropagation();
        ev.preventDefault();
        if (this.props.readonly) {
            return;
        }
        await this.props.record.update(
            { [this.props.name]: !this.props.record.data[this.props.name] },
            { save: true }
        );
    }
}

export const inlineBooleanToggleField = {
    ...listBooleanToggleField,
    component: InlineBooleanToggleField,
};

registry.category("fields").add("inline_boolean_toggle", inlineBooleanToggleField);
