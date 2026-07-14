/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component } from "@odoo/owl";

/**
 * Renders an HTML field (the QWeb-rendered call-invite body) inside an
 * isolated <iframe srcdoc> so the email's own styles can't bleed into — or be
 * overridden by — the backend CSS. Reads two sibling fields on the same
 * record: `device` (desktop/mobile width) and, indirectly, `has_button`
 * (the form shows the red banner). The resolved Book-a-call button is
 * outlined so the recruiter spots it instantly.
 */
export class CallStageEmailPreview extends Component {
    static template = "hr_recruitment_call_stage.EmailIframePreview";
    static props = { ...standardFieldProps };

    get srcdoc() {
        const body = this.props.record.data[this.props.name] || "";
        const style =
            "<style>" +
            "html,body{margin:0;padding:16px;background:#fff;" +
            "font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;}" +
            'a[href*="/book/"]{outline:3px solid #f59e0b;outline-offset:3px;' +
            "border-radius:6px;}" +
            "</style>";
        return style + body;
    }

    get isMobile() {
        return this.props.record.data.device === "mobile";
    }
}

export const callStageEmailPreview = {
    component: CallStageEmailPreview,
    supportedTypes: ["html", "text"],
};

registry.category("fields").add("call_stage_email_preview", callStageEmailPreview);
