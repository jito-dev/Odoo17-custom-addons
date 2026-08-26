/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component } from "@odoo/owl";

/**
 * 7-day availability preview for the Call Stage settings dialog.
 *
 * Reads the JSON payload built by
 * `hr.job.stage.config._compute_call_availability_7d`, which calls the very
 * same `appointment.type._get_appointment_slots()` the public booking page
 * uses — so this grid can never disagree with what the candidate sees.
 *
 * Trust rule: when any interviewer has not connected their Google Calendar,
 * busy time may simply be missing from `calendar.event`, which would make a
 * high slot count confidently wrong. In that case the counter is rendered
 * NEUTRAL rather than green — green reads as "verified", and must not lie.
 */
export class CallStageAvailability extends Component {
    static template = "hr_recruitment_call_stage.AvailabilityPreview";
    static props = { ...standardFieldProps };

    get payload() {
        const raw = this.props.record.data[this.props.name];
        if (!raw) {
            return null;
        }
        try {
            return JSON.parse(raw);
        } catch {
            return null;
        }
    }

    get days() {
        return this.payload?.days || [];
    }

    get totalSlots() {
        return this.days.reduce((sum, day) => sum + (day.count || 0), 0);
    }

    get isTrusted() {
        return this.payload?.trusted !== false;
    }

    get counterClass() {
        if (!this.isTrusted) {
            return "o_cs_avail_count o_cs_avail_untrusted";
        }
        return this.totalSlots > 0
            ? "o_cs_avail_count o_cs_avail_good"
            : "o_cs_avail_count o_cs_avail_bad";
    }

    get headline() {
        const tz = this.payload?.timezone || "UTC";
        return `Next 7 days · ${tz}`;
    }

    /** One line explaining the empty days, only when there are any. */
    get emptyNote() {
        const reasons = new Set(
            this.days.filter((d) => !d.count && d.reason).map((d) => d.reason)
        );
        if (!reasons.size) {
            return "";
        }
        const labels = {
            off: "no booking window on that weekday",
            busy: "the window is fully booked",
            lead_time: "too soon — minimum notice not met",
            beyond_horizon: "beyond the booking horizon",
        };
        const parts = [...reasons].map((r) => labels[r]).filter(Boolean);
        return parts.length ? `Empty days: ${parts.join("; ")}.` : "";
    }

    cellClass(day) {
        return `o_cs_avail_cell o_cs_avail_${day.level}`;
    }

    cellLabel(day) {
        if (day.count) {
            return String(day.count);
        }
        return day.reason === "off" ? "off" : "—";
    }
}

export const callStageAvailability = {
    component: CallStageAvailability,
    supportedTypes: ["text"],
};

registry
    .category("fields")
    .add("call_stage_availability", callStageAvailability);
