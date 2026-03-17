/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart, useEffect } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * SecretPayloadWidget
 *
 * Renders the encrypted payload of a secret.entry record.
 *
 * Responsibilities:
 *  - View mode: masked fields with 👁 reveal toggle + copy-to-clipboard
 *  - Edit mode: editable inputs + add/remove custom fields
 *  - Sealed state: shows a placeholder
 *
 * Save strategy:
 *  - Existing records: writes plaintext JSON to `transient_payload` via
 *    record.update() when user modifies values; the form's Save button
 *    triggers the model's write() which encrypts transient_payload → encrypted_payload.
 *  - New records: same — transient_payload is encrypted in create().
 *
 * Reveal strategy:
 *  - Calls get_decrypted_payload() RPC to get plaintext from server.
 *  - Decrypted values are held only in component state (not in the DOM until revealed).
 *
 * Type-change detection:
 *  - useEffect watches props.record.data.secret_type (reactive via useState(model)).
 *  - When type changes, state.fields is reset to the new type's defaults via RPC.
 *  - The Python @api.onchange('secret_type') also resets transient_payload server-side
 *    as a safety net so the saved payload is always consistent with the displayed type.
 */
class SecretPayloadWidget extends Component {
    static template = "jito_secrets_manager.SecretPayloadWidget";
    static props = {
        ...standardFieldProps,
        options: { type: Object, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");

        this.state = useState({
            vaultUnsealed: false, // set from RPC in _bootstrap — never trust record field for new records
            loaded: false,
            currentType: null,    // tracks the last-loaded type; null until bootstrap completes
            fields: [],           // [{key, label, value, sensitive, multiline}]
            customFields: [],     // [{label, value, sensitive}]
            revealedFields: {},   // {key: bool}
            revealedCustom: {},   // {index: bool}
            copiedField: null,    // key of recently copied built-in field
            copiedCustom: null,   // index of recently copied custom field
        });

        onWillStart(async () => {
            await this._bootstrap();
        });

        // useEffect tracks props.record.data.secret_type reactively (record is part of
        // the form model which is useState-wrapped in the form controller). Fires after
        // every render where the type changes — reliable unlike onWillUpdateProps which
        // receives the same mutable record object for both old and new props.
        useEffect(() => {
            const newType = this._secretType(this.props);
            if (this.state.currentType !== null && newType !== this.state.currentType) {
                this._applyTypeChange(newType);
            }
        }, () => [this._secretType(this.props)]);
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    _secretType(props) {
        return (props.record.data.secret_type) || "login";
    }

    // ── Type change ───────────────────────────────────────────────────────────

    _applyTypeChange(newType) {
        // Mark as loading so the template shows a spinner while we fetch defaults.
        this.state.loaded = false;
        this.orm.call("secret.entry", "get_default_fields", [newType]).then((defaults) => {
            this.state.fields = defaults;
            this.state.customFields = [];
            this.state.revealedFields = {};
            this.state.revealedCustom = {};
            this.state.currentType = newType;
            this.state.loaded = true;
            this._pushToRecord();
        }).catch(() => {
            this.state.loaded = true;
        });
    }

    // ── Bootstrap / Load ──────────────────────────────────────────────────────

    async _bootstrap() {
        // vault_is_unsealed is a non-stored computed field that Odoo does NOT
        // compute for new (unsaved) records — it stays false even when the vault
        // is open. Always ask the server for the real state instead.
        const vaultState = await this.orm.call("secret.entry", "get_vault_state", []);
        this.state.vaultUnsealed = vaultState.is_unsealed;
        if (!vaultState.is_unsealed) {
            this.state.loaded = false;
            return;
        }

        const recordId = this.props.record.resId;
        if (!recordId) {
            // New record — load default schema for the selected type.
            const defaults = await this.orm.call(
                "secret.entry",
                "get_default_fields",
                [this._secretType(this.props)],
            );
            this.state.fields = defaults;
            this.state.customFields = [];
            this.state.currentType = this._secretType(this.props);
            this.state.loaded = true;
            this._pushToRecord();
            return;
        }

        // Existing record — decrypt payload from server.
        try {
            const payload = await this.orm.call(
                "secret.entry",
                "get_decrypted_payload",
                [[recordId]],
            );
            this.state.fields = (payload.fields || []).map((f) => ({ ...f }));
            this.state.customFields = (payload.custom_fields || []).map((f) => ({ ...f }));
            this.state.currentType = this._secretType(this.props);
            this.state.loaded = true;
        } catch (err) {
            this.state.loaded = true;  // unblock UI even on error
            this.notification.add(
                err.data?.message || err.message || "Failed to load secret.",
                { type: "danger" },
            );
        }
    }

    // ── Reveal / Hide ─────────────────────────────────────────────────────────

    toggleReveal(key) {
        this.state.revealedFields[key] = !this.state.revealedFields[key];
    }

    toggleRevealCustom(index) {
        this.state.revealedCustom[index] = !this.state.revealedCustom[index];
    }

    // ── Copy to clipboard ────────────────────────────────────────────────────

    async copyField(key, label) {
        const field = this.state.fields.find((f) => f.key === key);
        if (!field) return;
        await this._writeClipboard(field.value || "", label);
        this.state.copiedField = key;
        setTimeout(() => { this.state.copiedField = null; }, 2000);
    }

    async copyCustomField(index, label) {
        const cf = this.state.customFields[index];
        if (!cf) return;
        await this._writeClipboard(cf.value || "", label);
        this.state.copiedCustom = index;
        setTimeout(() => { this.state.copiedCustom = null; }, 2000);
    }

    async _writeClipboard(text, label) {
        try {
            await navigator.clipboard.writeText(text);
            this.notification.add(`"${label}" copied to clipboard.`, {
                type: "info",
                sticky: false,
            });
        } catch {
            this.notification.add("Could not access clipboard. Please copy manually.", {
                type: "warning",
            });
        }
    }

    // ── Edit mode: built-in field changes ────────────────────────────────────

    onFieldInput(key, value) {
        const field = this.state.fields.find((f) => f.key === key);
        if (field) {
            field.value = value;
            this._pushToRecord();
        }
    }

    // ── Edit mode: custom fields ──────────────────────────────────────────────

    addCustomField() {
        this.state.customFields.push({ label: "", value: "", sensitive: false });
        this._pushToRecord();
    }

    removeCustomField(index) {
        this.state.customFields.splice(index, 1);
        delete this.state.revealedCustom[index];
        this._pushToRecord();
    }

    onCustomLabelInput(index, value) {
        this.state.customFields[index].label = value;
        this._pushToRecord();
    }

    onCustomValueInput(index, value) {
        this.state.customFields[index].value = value;
        this._pushToRecord();
    }

    onCustomSensitiveChange(index, checked) {
        this.state.customFields[index].sensitive = checked;
        this._pushToRecord();
    }

    // ── Persistence ───────────────────────────────────────────────────────────

    /**
     * Serialise the current payload state to JSON and push it into the record's
     * `transient_payload` field. On form Save, Odoo sends this to the server
     * where create()/write() encrypts it into `encrypted_payload`.
     */
    _pushToRecord() {
        const payload = {
            type: this._secretType(this.props),
            fields: this.state.fields.map((f) => ({ ...f })),
            custom_fields: this.state.customFields.map((f) => ({ ...f })),
        };
        this.props.record.update({
            transient_payload: JSON.stringify(payload),
        });
    }
}

export const secretPayloadField = {
    component: SecretPayloadWidget,
    supportedTypes: ["text"],
    isEmpty: () => false,  // Never treat as empty — it always renders the UI
};

registry.category("fields").add("SecretPayloadWidget", secretPayloadField);
