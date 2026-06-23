/** @odoo-module */

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListRenderer } from "@web/views/list/list_renderer";
import { useService } from "@web/core/utils/hooks";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";

/**
 * "Match Existing Entries" inline list renderer (17.0.8.2.0).
 *
 * Mirrors stock account_accountant's BankRecAmlsRenderer
 * (amls_list_view.js) but adapted to the standard `<field
 * mode="tree">` mount used in our widget form.
 *
 * Behavior:
 *   * Highlight rows whose `record.resId` is already in the parent
 *     widget's `selected_aml_ids` M2M.
 *   * Single-click anywhere on a row → if already selected, call
 *     `action_remove_new_aml(amlId)`; else `action_add_new_aml(amlId)`.
 *     Both are public methods on `jito.bank.rec.widget`.
 *   * After the RPC, reload the root form record so the parent's
 *     `selected_aml_ids` and `available_candidate_ids` refresh and
 *     the list re-renders with updated highlights.
 *
 * IMPORTANT (17.0.8.2.0 fix): an embedded `<field mode="tree">`
 * mounts `ListRenderer` *directly* via X2ManyField — `js_class` on
 * the inline `<tree>` is NEVER consulted. The renderer is therefore
 * exposed as a **field widget** (`jito_bank_rec_amls`) below; the
 * widget subclasses X2ManyField and swaps the renderer in its
 * components map. Apply via `widget="jito_bank_rec_amls"` in XML.
 *
 * The parent widget record is reached via
 * `this.props.list.model.root`. For an embedded x2many, props.list is
 * the field's StaticList whose `.model` is the parent form's
 * RelationalModel and `.model.root` is the owning record.
 */
export class JitoBankRecAmlsRenderer extends ListRenderer {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.notification = useService("notification");
    }

    _getParentWidgetRecord() {
        return this.props.list.model.root;
    }

    _getSelectedAmlIds() {
        const root = this._getParentWidgetRecord();
        const selected = root && root.data && root.data.selected_aml_ids;
        if (!selected) {
            return [];
        }
        // RelationalModel exposes .resIds on M2M field values in v17.
        if (Array.isArray(selected)) {
            return selected;
        }
        return selected.resIds || selected.currentIds || [];
    }

    /** @override */
    getRowClass(record) {
        const baseClasses = super.getRowClass(record);
        const selectedIds = this._getSelectedAmlIds();
        if (selectedIds.includes(record.resId)) {
            return `${baseClasses} o_jito_bank_rec_aml_selected`;
        }
        return baseClasses;
    }

    /** @override */
    async onCellClicked(record, column, ev) {
        const root = this._getParentWidgetRecord();
        if (!root || !root.resId) {
            // Form not yet committed; nothing to do.
            return;
        }
        const widgetId = root.resId;
        const selectedIds = this._getSelectedAmlIds();
        const isSelected = selectedIds.includes(record.resId);
        const method = isSelected
            ? "action_remove_new_aml"
            : "action_add_new_aml";
        try {
            await this.orm.call(
                "jito.bank.rec.widget",
                method,
                [widgetId, record.resId],
            );
            await root.load();
        } catch (err) {
            this.notification.add(
                err.data?.message || err.message || "Could not update matched lines",
                { type: "danger" },
            );
        }
    }
}

export const jitoBankRecAmlsListView = {
    ...listView,
    Renderer: JitoBankRecAmlsRenderer,
};

registry.category("views").add(
    "jito_bank_rec_amls_list_view",
    jitoBankRecAmlsListView,
);

/**
 * Field widget that mounts X2ManyField with our custom renderer.
 * The XML uses `widget="jito_bank_rec_amls"` on
 * `available_candidate_ids` (17.0.8.2.0). Without this, the embedded
 * `<tree js_class="...">` would silently fall back to the base
 * ListRenderer, and clicking a row would do nothing.
 */
export class JitoBankRecAmlsField extends X2ManyField {
    static components = {
        ...X2ManyField.components,
        ListRenderer: JitoBankRecAmlsRenderer,
    };
}

export const jitoBankRecAmlsField = {
    ...x2ManyField,
    component: JitoBankRecAmlsField,
};

registry.category("fields").add("jito_bank_rec_amls", jitoBankRecAmlsField);
