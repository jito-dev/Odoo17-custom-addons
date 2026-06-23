/** @odoo-module **/

import { Dialog } from "@web/core/dialog/dialog";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Component, useState, onWillStart } from "@odoo/owl";

/**
 * Analytic Distribution grid dialog (17.0.9.0.4).
 *
 * A modal grid for configuring a record's `analytic_distribution`:
 *   * one column per Analytic Plan (account selector per plan),
 *   * a Percentage column and a Subtotal column with two-way recompute
 *     (editing one recalculates the other against the line amount),
 *   * per-plan header showing the plan's running total, e.g.
 *     "Cost Center (82.5%)",
 *   * add / remove distribution lines,
 *   * hide / unhide plan columns.
 *
 * Opened via the `jito_open_analytic_dialog` client action returned by
 * the pie-chart buttons (action_open_analytic_picker /
 * action_edit_analytic). On Save it writes the recomposed
 * `{account_ids_csv: pct}` JSON back to the target record.
 */
export class JitoAnalyticDistributionDialog extends Component {
    static template = "jito_ledger_nl.JitoAnalyticDistributionDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        resModel: String,
        resId: Number,
        amount: { type: Number, optional: true },
        currencyId: { type: [Number, Boolean], optional: true },
        onSaved: { type: Function, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.amount = this.props.amount || 0;
        this.state = useState({
            plans: [],          // [{id, name, color, accounts: [{id, name}]}]
            hiddenPlanIds: [],  // plan ids whose column is hidden
            lines: [],          // [{accounts: {planId: accountId}, percentage, subtotal}]
        });
        onWillStart(this.load.bind(this));
    }

    get displaySubtotal() {
        return !!this.amount;
    }

    get visiblePlans() {
        return this.state.plans.filter((p) => !this.state.hiddenPlanIds.includes(p.id));
    }

    async load() {
        const plans = await this.orm.call(
            "jito.ledger.analytic.plan", "get_relevant_plans", [], {},
        );
        const planIds = plans.map((p) => p.id);
        const accounts = planIds.length
            ? await this.orm.searchRead(
                  "jito.ledger.analytic.account",
                  [["root_plan_id", "in", planIds]],
                  ["id", "display_name", "root_plan_id"],
              )
            : [];
        const byPlan = {};
        for (const p of plans) {
            byPlan[p.id] = [];
        }
        const accountPlan = {};
        for (const a of accounts) {
            const planId = a.root_plan_id && a.root_plan_id[0];
            if (byPlan[planId]) {
                byPlan[planId].push({ id: a.id, name: a.display_name });
                accountPlan[a.id] = planId;
            }
        }
        this.state.plans = plans.map((p) => ({
            id: p.id, name: p.name, color: p.color, accounts: byPlan[p.id] || [],
        }));

        const [rec] = await this.orm.read(
            this.props.resModel, [this.props.resId], ["analytic_distribution"],
        );
        const dist = (rec && rec.analytic_distribution) || {};
        const lines = [];
        for (const [csv, pct] of Object.entries(dist)) {
            const lineAccounts = {};
            for (const idStr of csv.split(",")) {
                const id = parseInt(idStr);
                const planId = accountPlan[id];
                if (planId) {
                    lineAccounts[planId] = id;
                }
            }
            lines.push({
                accounts: lineAccounts,
                percentage: pct,
                subtotal: (this.amount * pct) / 100,
            });
        }
        if (!lines.length) {
            lines.push(this.newLine());
        }
        this.state.lines = lines;
    }

    newLine() {
        const remaining = Math.max(100 - this.totalPercentage(), 0) || 100;
        return {
            accounts: {},
            percentage: remaining,
            subtotal: (this.amount * remaining) / 100,
        };
    }

    totalPercentage() {
        return this.state.lines.reduce((s, l) => s + (l.percentage || 0), 0);
    }

    planTotal(planId) {
        return this.state.lines.reduce(
            (s, l) => s + (l.accounts[planId] ? l.percentage || 0 : 0), 0,
        );
    }

    formatPct(v) {
        return `${(v || 0).toFixed(1)}%`;
    }

    addLine() {
        this.state.lines.push(this.newLine());
    }

    removeLine(index) {
        this.state.lines.splice(index, 1);
        if (!this.state.lines.length) {
            this.state.lines.push(this.newLine());
        }
    }

    onAccountChange(line, planId, ev) {
        const val = parseInt(ev.target.value);
        if (val) {
            line.accounts[planId] = val;
        } else {
            delete line.accounts[planId];
        }
    }

    onPercentageChange(line, ev) {
        const v = parseFloat(ev.target.value) || 0;
        line.percentage = v;
        line.subtotal = (this.amount * v) / 100;
    }

    onSubtotalChange(line, ev) {
        const v = parseFloat(ev.target.value) || 0;
        line.subtotal = v;
        line.percentage = this.amount ? (v / this.amount) * 100 : 0;
    }

    togglePlan(planId) {
        const i = this.state.hiddenPlanIds.indexOf(planId);
        if (i >= 0) {
            this.state.hiddenPlanIds.splice(i, 1);
        } else {
            this.state.hiddenPlanIds.push(planId);
        }
    }

    isPlanVisible(planId) {
        return !this.state.hiddenPlanIds.includes(planId);
    }

    async save() {
        const dist = {};
        for (const line of this.state.lines) {
            const ids = Object.values(line.accounts).filter(Boolean);
            if (!ids.length) {
                continue;
            }
            const key = ids.sort((a, b) => a - b).join(",");
            dist[key] = (dist[key] || 0) + (line.percentage || 0);
        }
        try {
            await this.orm.write(
                this.props.resModel, [this.props.resId],
                { analytic_distribution: Object.keys(dist).length ? dist : false },
            );
            this.props.close();
            this.props.onSaved?.();
        } catch (err) {
            this.notification.add(
                err.data?.message || err.message || _t("Could not save the analytic distribution."),
                { type: "danger" },
            );
        }
    }
}

function openAnalyticDialog(env, action) {
    const params = action.params || {};
    env.services.dialog.add(JitoAnalyticDistributionDialog, {
        resModel: params.res_model,
        resId: params.res_id,
        amount: params.amount || 0,
        currencyId: params.currency_id || false,
        onSaved: () =>
            env.services.action.doAction({ type: "ir.actions.client", tag: "soft_reload" }),
    });
}

registry.category("actions").add("jito_open_analytic_dialog", openAnalyticDialog);
