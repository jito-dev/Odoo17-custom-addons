/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { useEffect } from "@odoo/owl";

/**
 * When a revolut.transaction form is opened (or navigated to via pager),
 * automatically call action_auto_fetch so the user sees Revolut receipts
 * and Gmail results without having to click any button.
 *
 * The server-side method is idempotent: it skips fetch/search if already done.
 */
patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);

        if (this.props.resModel === "revolut.transaction") {
            useEffect(
                () => {
                    const resId = this.model.root?.resId;
                    if (resId) {
                        this._revolutAutoFetch(resId);
                    }
                },
                () => [this.model.root?.resId],
            );
        }
    },

    async _revolutAutoFetch(resId) {
        try {
            await this.orm.call(
                "revolut.transaction",
                "action_auto_fetch",
                [[resId]],
            );
            await this.model.root.load();
        } catch (e) {
            // Auto-fetch is best-effort — never break the form
            console.debug("[revolut] auto-fetch skipped:", e);
        }
    },
});
