/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { browser } from "@web/core/browser/browser";
import { Tooltip } from "@web/core/tooltip/tooltip";
import { usePopover } from "@web/core/popover/popover_hook";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { CharField } from "@web/views/fields/char/char_field";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, useRef } from "@odoo/owl";

/**
 * A copy-to-clipboard button that calls a server method before copying.
 * Used for access tokens that may need refreshing before they are valid.
 */
class RefreshCopyButton extends Component {
    static template = "upwork.RefreshCopyButton";
    static props = {
        className: { type: String, optional: true },
        copyText: { type: String, optional: true },
        disabled: { type: Boolean, optional: true },
        successText: { type: String, optional: true },
        content: { type: [String, Object], optional: true },
        resModel: { type: String },
        resId: { type: [Number, Boolean] },
        refreshMethod: { type: String },
    };

    setup() {
        this.button = useRef("button");
        this.popover = usePopover(Tooltip);
        this.orm = useService("orm");
        this.notification = useService("notification");
    }

    showTooltip(message) {
        this.popover.open(this.button.el, { tooltip: message });
        browser.setTimeout(this.popover.close, 1200);
    }

    async onClick() {
        let freshContent;
        try {
            freshContent = await this.orm.call(
                this.props.resModel,
                this.props.refreshMethod,
                [[this.props.resId]],
            );
        } catch (error) {
            // Error is already handled by Odoo's RPC error handler (UserError → dialog)
            return;
        }

        if (!freshContent) {
            this.notification.add(_t("No token available."), { type: "warning" });
            return;
        }

        try {
            await browser.navigator.clipboard.writeText(freshContent);
        } catch (error) {
            browser.console.warn(error);
            return;
        }
        this.showTooltip(this.props.successText);
    }
}

/**
 * Custom field widget: refreshes token via RPC, then copies to clipboard.
 * Drop-in replacement for CopyClipboardChar on token fields.
 */
class RefreshCopyClipboardCharField extends Component {
    static template = "upwork.RefreshCopyClipboardCharField";
    static components = { Field: CharField, RefreshCopyButton };
    static props = {
        ...standardFieldProps,
        string: { type: String, optional: true },
    };

    setup() {
        this.copyText = this.props.string || _t("Copy");
        this.successText = _t("Copied");
    }

    get copyButtonClassName() {
        return "o_btn_char_copy btn-sm";
    }

    get fieldProps() {
        const { string, ...rest } = this.props;
        return rest;
    }
}

export const refreshCopyClipboardCharField = {
    component: RefreshCopyClipboardCharField,
    displayName: _t("Refresh & Copy to Clipboard"),
    supportedTypes: ["char"],
    extractProps({ attrs }) {
        return {
            string: attrs.string,
        };
    },
};

registry.category("fields").add("RefreshCopyClipboardChar", refreshCopyClipboardCharField);
