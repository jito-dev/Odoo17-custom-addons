/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";

/**
 * Client action: bulk Upwork invoice PDF uploader.
 *
 * Files are sent to /upwork/invoice_upload one at a time so each POST
 * body contains only a single PDF. This avoids the nginx
 * client_max_body_size limit that breaks Odoo's built-in many2many_binary
 * widget when many files are selected at once.
 */
class InvoiceUploader extends Component {
    static template = "upwork_simple_accounting_integration.InvoiceUploader";
    static props = ["*"];

    setup() {
        this.state = useState({
            uploading: false,
            done: false,
            current: 0,   // files processed so far
            total: 0,     // files selected
            matched: 0,
            unmatched: [],
        });
    }

    async onFileChange(ev) {
        const files = [...ev.target.files];
        ev.target.value = "";   // allow re-selecting same files later
        if (!files.length) return;

        Object.assign(this.state, {
            uploading: true,
            done: false,
            current: 0,
            total: files.length,
            matched: 0,
            unmatched: [],
        });

        for (const file of files) {
            const formData = new FormData();
            formData.append("ufile", file, file.name);
            formData.append("csrf_token", odoo.csrf_token);

            try {
                const resp = await fetch("/upwork/invoice_upload", {
                    method: "POST",
                    body: formData,
                });
                const result = await resp.json();
                if (result.matched) {
                    this.state.matched++;
                } else {
                    this.state.unmatched.push(file.name);
                }
            } catch {
                this.state.unmatched.push(file.name + " (upload error)");
            }
            this.state.current++;
        }

        this.state.uploading = false;
        this.state.done = true;
    }

    get progressPct() {
        if (!this.state.total) return 0;
        return Math.round((this.state.current / this.state.total) * 100);
    }

    reset() {
        Object.assign(this.state, {
            uploading: false,
            done: false,
            current: 0,
            total: 0,
            matched: 0,
            unmatched: [],
        });
    }
}

registry.category("actions").add("upwork_invoice_uploader", InvoiceUploader);
