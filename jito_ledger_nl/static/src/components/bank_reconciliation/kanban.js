/** @odoo-module */

import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { View } from "@web/views/view";
import { useService } from "@web/core/utils/hooks";
import { onWillStart, useState } from "@odoo/owl";

/**
 * Bank Reconciliation KanbanController for the parallel Management
 * Ledger. Click a kanban card → mount the widget's form inline in
 * the right pane (mirroring stock's two-pane bank-rec layout).
 *
 * Key detail: the `<View>` in the template gets an explicit
 * `views=[[false, 'form']]` so it does NOT inherit
 * `env.config.views` from the parent kanban action — that
 * inheritance was loading the bank-rec kanban's search view under
 * the widget model and crashing the SearchArchParser
 * (this.fields[name].type on undefined). With an explicit form-only
 * views array, no search view is loaded.
 */
export class JitoBankRecKanbanController extends KanbanController {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.widgetState = useState({
            widgetId: null,
            currentStLineId: null,
            accountSummary: null,
        });
        onWillStart(this.loadAccountSummary.bind(this));
    }

    async loadAccountSummary() {
        // Try the action context first (set by
        // jito_ledger_journal.action_open_reconcile_wizard_for_journal),
        // fall back to the first kanban record's journal_id if the
        // context isn't populated yet (e.g. cold reload of the action
        // URL where breadcrumb-restored context is sparse).
        let journalId =
            this.props.context?.default_journal_id
            || this.props.context?.active_id;
        if (!journalId && this.model?.root?.records?.length) {
            const first = this.model.root.records[0];
            const journalField = first?.data?.journal_id;
            if (Array.isArray(journalField) && journalField[0]) {
                journalId = journalField[0];
            }
        }
        if (!journalId) {
            return;
        }
        try {
            const summary = await this.orm.call(
                "jito.ledger.move.line",
                "get_bank_rec_account_summary",
                [journalId],
            );
            if (summary && summary.account_name) {
                this.widgetState.accountSummary = summary;
            }
        } catch (err) {
            // Non-fatal — kanban renders without the header.
        }
    }

    async _refreshAccountSummary() {
        // Re-call after a validate / reset so counters stay current.
        await this.loadAccountSummary();
    }

    async openRecord(record, mode) {
        if (record.resId === this.widgetState.currentStLineId) {
            return;
        }
        try {
            const widgetId = await this.orm.call(
                "jito.bank.rec.widget",
                "action_open_for_st_line",
                [record.resId],
            );
            this.widgetState.widgetId = widgetId;
            this.widgetState.currentStLineId = record.resId;
        } catch (err) {
            this.notification.add(
                err.data?.message || err.message || "Could not open reconciliation",
                { type: "danger" },
            );
        }
    }

    async onWidgetSaved() {
        const matchedLineId = this.widgetState.currentStLineId;
        this.widgetState.widgetId = null;
        this.widgetState.currentStLineId = null;
        await this.model.load();
        await this._refreshAccountSummary();
        const remaining = this.model.root.records.filter(
            (r) => r.resId !== matchedLineId,
        );
        if (remaining.length > 0) {
            await this.openRecord(remaining[0]);
        }
    }
}

JitoBankRecKanbanController.components = {
    ...KanbanController.components,
    View,
};
JitoBankRecKanbanController.template = "jito_ledger_nl.JitoBankRecKanbanController";

export const jitoBankRecKanbanView = {
    ...kanbanView,
    Controller: JitoBankRecKanbanController,
    searchMenuTypes: ["filter", "favorite"],
};

registry.category("views").add("jito_bank_rec_widget_kanban", jitoBankRecKanbanView);
