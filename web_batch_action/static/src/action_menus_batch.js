/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ActionMenus } from "@web/search/action_menus/action_menus";
import { useService } from "@web/core/utils/hooks";
import { makeContext } from "@web/core/context";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { reactive, useState } from "@odoo/owl";
import { BatchProgressDialog } from "./batch_progress_dialog";

const STORAGE_ENABLED = "web_batch_action.enabled";
const STORAGE_SIZE = "web_batch_action.size";
const DEFAULT_SIZE = 100;
const SEARCH_PAGE = 10000; // page size when paginating ids for a "select all" selection
const MAX_IDS = 200000; // safety cap so batch mode never runs away on an unbounded domain
const COOLDOWN_SECONDS = 60; // wait between an exhausted pass and retrying the failed batches
const MAX_RETRIES = 3; // retry rounds after the initial pass (a batch is attempted at most 4×)

/**
 * Patch the list-view Action menu so that, when "Batch" is ticked, a Server
 * Action runs on the selection in client-driven sequential batches instead of a
 * single call with all active_ids.
 *
 * Only `executeAction` (server actions) is intercepted; static actions
 * (Archive/Delete/Export) and Print go through `item.callback` and are
 * untouched. The per-batch follow-up action returned by `/web/action/run` is
 * intentionally discarded (we show one consolidated summary) so a 100-batch run
 * does not open 100 dialogs/downloads — batch mode is for per-record bulk
 * mutations, not for actions whose returned wizard/window matters.
 */
patch(ActionMenus.prototype, {
    setup() {
        super.setup();
        this.rpc = useService("rpc");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.user = useService("user");

        const enabled = browser.localStorage.getItem(STORAGE_ENABLED) === "1";
        const storedSize = parseInt(browser.localStorage.getItem(STORAGE_SIZE), 10);
        this.batch = useState({
            enabled,
            size: Number.isInteger(storedSize) && storedSize > 0 ? storedSize : DEFAULT_SIZE,
        });
    },

    onBatchToggle(ev) {
        this.batch.enabled = ev.target.checked;
        browser.localStorage.setItem(STORAGE_ENABLED, this.batch.enabled ? "1" : "0");
    },

    onBatchSizeChange(ev) {
        let n = parseInt(ev.target.value, 10);
        if (!Number.isInteger(n) || n < 1) {
            n = 1;
        }
        this.batch.size = n;
        ev.target.value = n; // reflect the clamp back to the input
        browser.localStorage.setItem(STORAGE_SIZE, String(n));
    },

    async executeAction(action) {
        // Print actions also reach executeAction (no callback); never batch those —
        // only custom Server Actions from the Action menu.
        const isPrint = (this.props.items.print || []).some(
            (p) => p === action || p.id === action.id
        );
        if (!this.batch.enabled || isPrint) {
            return super.executeAction(action);
        }
        const size = Math.max(1, parseInt(this.batch.size, 10) || 1);

        let ids;
        try {
            ids = await this._batchResolveIds();
        } catch (e) {
            this.notification.add(e.message || String(e), { type: "danger" });
            return;
        }
        if (!ids.length) {
            this.notification.add(_t("No records selected."), { type: "warning" });
            return;
        }
        return this._runBatches(action, ids, size);
    },

    /**
     * Resolve the full list of record ids to process. For an explicit selection
     * we use the selected resIds; for a "select all matching domain" selection
     * we paginate orm.search so batching can cover the whole set (past the
     * single-call active_ids_limit), bounded by MAX_IDS.
     */
    async _batchResolveIds() {
        if (!this.props.isDomainSelected) {
            return this.props.getActiveIds();
        }
        const ids = [];
        let offset = 0;
        // eslint-disable-next-line no-constant-condition
        while (true) {
            const page = await this.orm.search(this.props.resModel, this.props.domain, {
                limit: SEARCH_PAGE,
                offset,
                context: this.props.context,
            });
            ids.push(...page);
            if (page.length < SEARCH_PAGE) {
                break;
            }
            if (ids.length >= MAX_IDS) {
                throw new Error(
                    _t("Selection too large for batch processing (over %s records).", MAX_IDS)
                );
            }
            offset += SEARCH_PAGE;
        }
        return ids;
    },

    async _runBatches(action, ids, size) {
        const rawBatches = [];
        for (let i = 0; i < ids.length; i += size) {
            const chunk = ids.slice(i, i + size);
            rawBatches.push({
                no: rawBatches.length + 1,
                chunk,
                count: chunk.length,
                status: "pending", // 'pending' | 'running' | 'ok' | 'failed'
                attempts: 0,
                error: null,
            });
        }

        const progress = reactive({
            total: ids.length,
            totalBatches: rawBatches.length,
            batches: rawBatches, // single source of truth (record counts derived from this)
            phase: "running", // 'running' | 'cooldown' | 'done'
            retryRound: 0, // 0 = initial pass, 1..MAX_RETRIES = retry rounds
            maxRetries: MAX_RETRIES,
            roundTotal: rawBatches.length,
            roundCurrent: 0,
            currentBatchNo: 0,
            cooldownRemaining: 0,
            skipCooldown: false,
            cancelled: false,
            done: false,
            // timing
            startTs: 0,
            nowTs: 0,
            lastBatchMs: 0,
            batchMsTotal: 0,
            batchMsCount: 0,
        });
        this.dialog.add(BatchProgressDialog, {
            progress,
            onCancel: () => {
                progress.cancelled = true;
            },
            onRetryNow: () => {
                progress.skipCooldown = true;
            },
        });

        // Warn if the user tries to leave while batches (or a cooldown) are still pending.
        const beforeUnload = (ev) => {
            ev.preventDefault();
            ev.returnValue = "";
        };
        browser.addEventListener("beforeunload", beforeUnload);

        // Tick a reactive clock each second so elapsed time / ETA update live even
        // while a single batch is in flight.
        progress.startTs = Date.now();
        progress.nowTs = progress.startTs;
        const ticker = browser.setInterval(() => {
            progress.nowTs = Date.now();
        }, 1000);

        try {
            // Initial pass over every batch.
            await this._runPass(action, progress.batches, progress);

            // Retry rounds: after the whole pass, cooldown, then re-run only the failed batches.
            while (
                !progress.cancelled &&
                progress.retryRound < MAX_RETRIES &&
                progress.batches.some((b) => b.status === "failed")
            ) {
                progress.retryRound += 1;
                await this._cooldown(progress);
                if (progress.cancelled) {
                    break;
                }
                await this._runPass(
                    action,
                    progress.batches.filter((b) => b.status === "failed"),
                    progress
                );
            }
        } finally {
            browser.clearInterval(ticker);
            progress.nowTs = Date.now();
            browser.removeEventListener("beforeunload", beforeUnload);
            progress.phase = "done";
            progress.done = true;
            // Refresh the list once, after all batches.
            this.props.onActionExecuted();
            this._notifySummary(progress);
        }
    },

    /** Run one sequential pass over `batchList` (the initial pass, or the failed
     *  subset on a retry round), updating per-batch status as it goes. */
    async _runPass(action, batchList, progress) {
        progress.phase = "running";
        progress.roundTotal = batchList.length;
        progress.roundCurrent = 0;
        for (const b of batchList) {
            if (progress.cancelled) {
                break;
            }
            progress.roundCurrent += 1;
            progress.currentBatchNo = b.no;
            await this._runOneBatch(action, b, progress);
        }
    },

    /** Run a single batch's chunk through the server action; record the outcome
     *  and how long it took. */
    async _runOneBatch(action, b, progress) {
        b.status = "running";
        b.attempts += 1;
        const context = makeContext([
            this.user.context,
            this.props.context,
            {
                active_model: this.props.resModel,
                active_ids: b.chunk,
                active_id: b.chunk[0],
                ...(this.props.domain ? { active_domain: this.props.domain } : {}),
            },
        ]);
        const t0 = Date.now();
        try {
            // Run the server action directly; discard its returned follow-up action.
            await this.rpc("/web/action/run", { action_id: action.id, context });
            b.status = "ok";
            b.error = null;
        } catch (e) {
            b.status = "failed";
            b.error = (e && (e.data?.message || e.message)) || String(e);
        } finally {
            const dt = Date.now() - t0;
            b.durationMs = dt;
            progress.lastBatchMs = dt;
            progress.batchMsTotal += dt;
            progress.batchMsCount += 1;
            progress.nowTs = Date.now();
        }
    },

    /** Wait COOLDOWN_SECONDS before a retry round, counting down each second.
     *  Cancel or "Retry now" break out early (within ≤1s). */
    async _cooldown(progress) {
        progress.phase = "cooldown";
        progress.skipCooldown = false;
        progress.cooldownRemaining = COOLDOWN_SECONDS;
        while (
            progress.cooldownRemaining > 0 &&
            !progress.cancelled &&
            !progress.skipCooldown
        ) {
            await new Promise((resolve) => browser.setTimeout(resolve, 1000));
            progress.cooldownRemaining -= 1;
        }
        progress.cooldownRemaining = 0;
        progress.phase = "running";
    },

    /** Final toast: record counts derived from the per-batch statuses. */
    _notifySummary(progress) {
        const sum = (status) =>
            progress.batches
                .filter((b) => b.status === status)
                .reduce((s, b) => s + b.count, 0);
        const okRecords = sum("ok");
        const failedRecords = sum("failed");
        const skippedRecords =
            progress.batches
                .filter((b) => b.status === "pending" || b.status === "running")
                .reduce((s, b) => s + b.count, 0);

        let message;
        if (progress.cancelled) {
            message = _t(
                "Batch processing cancelled — %s processed, %s failed, %s not processed.",
                okRecords,
                failedRecords,
                skippedRecords
            );
        } else if (failedRecords) {
            message = _t(
                "Batch processing finished — %s processed, %s failed after %s retries.",
                okRecords,
                failedRecords,
                MAX_RETRIES
            );
        } else {
            message = _t("Batch processing finished — %s record(s) processed.", okRecords);
        }
        const elapsedS = Math.max(0, Math.round((progress.nowTs - progress.startTs) / 1000));
        message += " " + _t("(took %ss)", elapsedS);
        this.notification.add(message, {
            type: failedRecords ? "warning" : "success",
            sticky: Boolean(failedRecords),
        });
    },
});
