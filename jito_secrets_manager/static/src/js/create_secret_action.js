/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component } from "@odoo/owl";

class CreateSecretAction extends Component {
    static template = "jito_secrets_manager.CreateSecretAction";

    setup() {
        this.actionService = useService("action");
    }

    async onClickCreate() {
        await this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "secret.entry",
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("jito_secrets_manager.create_secret", CreateSecretAction);
