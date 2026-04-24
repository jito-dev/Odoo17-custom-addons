/** @odoo-module **/

import { Dialog } from "@web/core/dialog/dialog";
import { Component, useState, useRef, onMounted } from "@odoo/owl";

export class QuickReportDialog extends Component {
    static template = "jito_helpdesk_quick_report.QuickReportDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        defaultTitle: { type: String, optional: true },
        onSubmit: Function,
    };

    setup() {
        this.state = useState({
            title: this.props.defaultTitle || "",
            description: "",
            isSubmitting: false,
        });
        this.titleInputRef = useRef("titleInput");
        onMounted(() => {
            if (this.titleInputRef.el) {
                this.titleInputRef.el.focus();
                this.titleInputRef.el.select();
            }
        });
    }

    onTitleInput(ev) {
        this.state.title = ev.target.value;
    }

    onDescriptionInput(ev) {
        this.state.description = ev.target.value;
    }

    async onConfirm() {
        if (!this.state.title.trim()) {
            return;
        }
        this.state.isSubmitting = true;
        try {
            await this.props.onSubmit({
                title: this.state.title.trim(),
                description: this.state.description.trim(),
            });
            this.props.close();
        } catch (e) {
            this.state.isSubmitting = false;
            throw e;
        }
    }
}
