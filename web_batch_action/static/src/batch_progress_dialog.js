/** @odoo-module **/

import { Dialog } from "@web/core/dialog/dialog";
import { Component, useState } from "@odoo/owl";

const _WD = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const _MO = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Format a timestamp (ms) as a local clock string, e.g. "Sun Jun 14 22:47:02". */
function fmtClock(ts) {
    const d = new Date(ts);
    const pad = (n) => String(n).padStart(2, "0");
    return (
        `${_WD[d.getDay()]} ${_MO[d.getMonth()]} ${d.getDate()} ` +
        `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
    );
}

/** Format a duration in ms as "Hh Mm Ss" / "Mm Ss" / "Ss". */
function fmtDur(ms) {
    const s = Math.max(0, Math.round(ms / 1000));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    if (h) {
        return `${h}h ${m}m ${sec}s`;
    }
    if (m) {
        return `${m}m ${sec}s`;
    }
    return `${sec}s`;
}

/** Format a short duration: "<n> ms" (<1s), "X.Xs" (<10s), else fmtDur. */
function fmtMs(ms) {
    if (ms < 1000) {
        return `${Math.round(ms)} ms`;
    }
    if (ms < 10000) {
        return `${(ms / 1000).toFixed(1)}s`;
    }
    return fmtDur(ms);
}

/**
 * Modal shown while a Server Action runs in client-driven batches.
 *
 * It subscribes to the shared reactive `progress` object that the ActionMenus
 * patch mutates on every batch, so the bar / counters / failure list update
 * live. While the run is active the only way out is the Cancel button (which
 * signals the loop to stop after the current batch); once `progress.done` is
 * set the footer switches to a Close button.
 */
export class BatchProgressDialog extends Component {
    static template = "web_batch_action.BatchProgressDialog";
    static components = { Dialog };
    static props = {
        progress: Object, // shared reactive: see action_menus_batch.js
        onCancel: Function, // sets progress.cancelled = true
        onRetryNow: Function, // skips the remaining cooldown
        close: Function, // injected by the dialog service
    };

    setup() {
        this.progress = useState(this.props.progress);
    }

    get percent() {
        const p = this.progress;
        if (!p.roundTotal) {
            return 0;
        }
        return Math.round((p.roundCurrent / p.roundTotal) * 100);
    }

    get failedBatches() {
        return this.progress.batches.filter((b) => b.status === "failed");
    }

    get okRecords() {
        return this.progress.batches
            .filter((b) => b.status === "ok")
            .reduce((s, b) => s + b.count, 0);
    }

    get failedRecords() {
        return this.failedBatches.reduce((s, b) => s + b.count, 0);
    }

    get processedRecords() {
        return this.okRecords + this.failedRecords;
    }

    // ── Timing metrics ────────────────────────────────────────────────────────

    get elapsedMs() {
        const p = this.progress;
        return p.startTs ? p.nowTs - p.startTs : 0;
    }

    get elapsedText() {
        return fmtDur(this.elapsedMs);
    }

    get lastBatchText() {
        return fmtMs(this.progress.lastBatchMs);
    }

    get avgBatchMs() {
        const p = this.progress;
        return p.batchMsCount ? p.batchMsTotal / p.batchMsCount : 0;
    }

    get avgText() {
        return this.avgBatchMs ? fmtMs(this.avgBatchMs) : "—";
    }

    get throughputText() {
        const sec = this.elapsedMs / 1000;
        if (sec < 0.5 || !this.processedRecords) {
            return "—";
        }
        return `~${Math.round(this.processedRecords / sec)} rec/s`;
    }

    /** Best-effort remaining time for the current trajectory (the in-progress pass,
     *  plus an imminent cooldown). Future retry rounds are not predicted. */
    get remainingMs() {
        const p = this.progress;
        const avg = this.avgBatchMs;
        if (p.phase === "cooldown") {
            return p.cooldownRemaining * 1000 + this.failedBatches.length * avg;
        }
        return Math.max(0, p.roundTotal - p.roundCurrent) * avg;
    }

    get remainingText() {
        return fmtDur(this.remainingMs);
    }

    get etaText() {
        if (!this.avgBatchMs) {
            return "—";
        }
        return fmtClock(this.progress.nowTs + this.remainingMs);
    }

    onCancel() {
        this.props.onCancel();
    }

    onRetryNow() {
        this.props.onRetryNow();
    }

    onClose() {
        this.props.close();
    }
}
