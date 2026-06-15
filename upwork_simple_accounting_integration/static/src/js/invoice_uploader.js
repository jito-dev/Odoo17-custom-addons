/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";

/**
 * Client action: bulk Upwork PDF uploader.
 *
 * Each file is POSTed to /upwork/invoice_upload one at a time. The server
 * splits the multi-page Upwork document into single-page PDFs and routes each
 * page to the right transaction (service invoice → customer invoice tx,
 * Upwork fee → the linked Service-Fee tx, charge → the matched tx) and returns
 * a structured per-file result which we render in a results table.
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
            results: [],  // per-file result dicts from the server
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
            results: [],
        });

        for (const file of files) {
            const formData = new FormData();
            formData.append("ufile", file, file.name);
            formData.append("csrf_token", odoo.csrf_token);

            let result;
            try {
                const resp = await fetch("/upwork/invoice_upload", {
                    method: "POST",
                    body: formData,
                });
                result = await resp.json();
            } catch {
                result = { status: "unreadable", message: "Upload error" };
            }
            if (!result.filename) result.filename = file.name;
            if (!result.routed) result.routed = [];
            this.state.results.push(result);
            this.state.current++;
        }

        this.state.uploading = false;
        this.state.done = true;
    }

    get progressPct() {
        if (!this.state.total) return 0;
        return Math.round((this.state.current / this.state.total) * 100);
    }

    get routedCount() {
        return this.state.results.filter((r) => r.status === "routed").length;
    }
    get warnCount() {
        return this.state.results.filter((r) =>
            ["fee_tx_missing", "payment_tx_missing"].includes(r.status)
        ).length;
    }
    get failedCount() {
        return this.state.results.filter(
            (r) => !["routed", "fee_tx_missing", "payment_tx_missing"].includes(r.status)
        ).length;
    }

    badgeClass(status) {
        if (status === "routed") return "text-bg-success";
        if (["fee_tx_missing", "payment_tx_missing"].includes(status)) return "text-bg-warning";
        return "text-bg-danger";
    }

    roleLabel(role) {
        const L = {
            customer_invoice: "Invoice",
            customer_refund: "Credit Note",
            vendor_bill: "Bill",
            vendor_refund: "Vendor Credit",
            withdrawal_summary: "Transfer",
            card_invoice: "Card Invoice",
            card_receipt: "Card Receipt",
            gl: "Doc",
        };
        return L[role] || role;
    }

    routedSummary(r) {
        return (r.routed || [])
            .map((x) => this.roleLabel(x.role) + " → " + x.record_id)
            .join(", ");
    }

    reset() {
        Object.assign(this.state, {
            uploading: false,
            done: false,
            current: 0,
            total: 0,
            results: [],
        });
    }
}

registry.category("actions").add("upwork_invoice_uploader", InvoiceUploader);
