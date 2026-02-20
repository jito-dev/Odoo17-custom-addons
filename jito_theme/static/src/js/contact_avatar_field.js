/** @odoo-module **/

/**
 * Jito Theme – Contact Avatar + Name Field Widget
 *
 * A custom CharField widget that prepends the contact's avatar image
 * (loaded via /web/image/res.partner/{id}/avatar_128) to the display_name
 * in read-only mode (list views).
 *
 * In edit mode it falls back to a plain text input so inline editing
 * (when the list is editable) still works correctly.
 */

import { registry } from "@web/core/registry";
import { charField, CharField } from "@web/views/fields/char/char_field";
import { useInputField } from "@web/views/fields/input_field_hook";
import { useRef } from "@odoo/owl";

export class ContactAvatarNameField extends CharField {
    static template = "jito_theme.ContactAvatarNameField";

    setup() {
        // Set up the input ref for edit mode (mirroring CharField.setup).
        // useInputField registers focus/change handlers on the ref element.
        // When the template renders in readonly mode the ref is simply null,
        // which useInputField handles gracefully.
        this.input = useRef("input");
        useInputField({
            getValue: () => this.props.record.data[this.props.name] || "",
            parse: (v) => (this.shouldTrim ? v.trim() : v),
        });
    }

    /**
     * Returns the Odoo image URL for this partner's 128-px avatar, or null
     * for unsaved (new) records so the initials placeholder is shown instead.
     */
    get avatarUrl() {
        const id = this.props.record.resId;
        if (!id) {
            return null;
        }
        return `/web/image/res.partner/${id}/avatar_128`;
    }

    /**
     * One or two uppercase initials derived from the display name.
     * Used as a fallback when the record has no saved ID yet.
     */
    get initials() {
        const name = this.props.record.data[this.props.name] || "";
        return name
            .split(" ")
            .filter(Boolean)
            .slice(0, 2)
            .map((w) => w[0].toUpperCase())
            .join("");
    }
}

registry.category("fields").add("jito_contact_name", {
    ...charField,
    component: ContactAvatarNameField,
    displayName: "Contact Name (Jito Avatar)",
});
