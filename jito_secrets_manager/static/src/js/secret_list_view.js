/** @odoo-module **/

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";

/**
 * SecretListController
 *
 * Extends the standard ListController to add an explicit "New Secret" button.
 * The button always appears in the control panel (top-left, in layout-buttons slot)
 * and opens a blank secret.entry form view in the current tab.
 */
export class SecretListController extends ListController {
    async onClickNewSecret() {
        // this.actionService is inherited from ListController.setup()
        await this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "secret.entry",
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("views").add("secret_list", {
    ...listView,
    Controller: SecretListController,
    buttonTemplate: "jito_secrets_manager.SecretListView.Buttons",
});
