/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { useService } from "@web/core/utils/hooks";

/**
 * Unified reconciliation-lines table (17.0.8.2.0).
 *
 * Mirrors stock account_accountant's ``o_bank_rec_lines_widget_table``
 * row layout: bank/liquidity row + each picked counterpart + the
 * auto-balance/suspense row. Reads the synthesised payload from
 * ``display_lines_data`` (JSON) on ``jito.bank.rec.widget`` so the
 * backend owns the row composition.
 *
 * Click on the trash icon (counterpart rows only) → ORM call
 * ``action_remove_new_aml`` then refresh the form record.
 */
export class JitoBankRecLinesTable extends Component {
    static template = "jito_ledger_nl.JitoBankRecLinesTable";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
    }

    get widgetRecord() {
        return this.props.record;
    }

    get rows() {
        const raw = this.widgetRecord.data.display_lines_data;
        if (!raw) {
            return [];
        }
        try {
            return JSON.parse(raw);
        } catch (e) {
            return [];
        }
    }

    get currencyDigits() {
        const curr = this.widgetRecord.data.currency_id;
        if (curr && curr.length === 2) {
            // M2O field is exposed as [id, display_name] in record.data.
            return 2;
        }
        return 2;
    }

    formatAmount(value) {
        if (value === null || value === undefined || value === 0) {
            return "";
        }
        const curr = this.widgetRecord.data.currency_id;
        const symbol = curr && curr.length === 2 ? "" : "";
        const formatted = Number(value).toLocaleString(undefined, {
            minimumFractionDigits: this.currencyDigits,
            maximumFractionDigits: this.currencyDigits,
        });
        return symbol ? `${symbol} ${formatted}` : formatted;
    }

    rowClasses(row) {
        const cls = [
            "o_data_row",
            "o_selected_row",
            "o_list_no_open",
            "o_bank_rec_expanded_line",
            "o_jito_bank_rec_row",
        ];
        if (row.flag === "liquidity") {
            cls.push("o_bank_rec_liquidity_line");
        } else if (row.flag === "auto_balance") {
            cls.push("o_bank_rec_auto_balance_line");
        }
        if (row.reconciled) {
            cls.push("o_jito_bank_rec_row_reconciled");
        }
        return cls.join(" ");
    }

    secondRowClasses(row) {
        const cls = [
            "o_data_row",
            "o_selected_row",
            "o_list_no_open",
            "o_bank_rec_second_line",
            "o_jito_bank_rec_second_row",
        ];
        if (row.flag === "liquidity") {
            cls.push("o_bank_rec_liquidity_line");
        } else if (row.flag === "auto_balance") {
            cls.push("o_bank_rec_auto_balance_line");
        }
        if (row.reconciled) {
            cls.push("o_jito_bank_rec_row_reconciled");
        }
        return cls.join(" ");
    }

    async onRemoveCounterpart(row) {
        if (!row.aml_id || !this.widgetRecord.resId) {
            return;
        }
        try {
            await this.orm.call(
                "jito.bank.rec.widget",
                "action_remove_new_aml",
                [this.widgetRecord.resId, row.aml_id],
            );
            await this.widgetRecord.load();
        } catch (err) {
            this.notification.add(
                err.data?.message || err.message || "Could not remove counterpart",
                { type: "danger" },
            );
        }
    }
}

export const jitoBankRecLinesTable = {
    component: JitoBankRecLinesTable,
    fieldDependencies: [
        { name: "display_lines_data", type: "text" },
        { name: "currency_id", type: "many2one" },
        { name: "balance_amount", type: "monetary" },
    ],
};

registry
    .category("view_widgets")
    .add("jito_bank_rec_lines_table", jitoBankRecLinesTable);
