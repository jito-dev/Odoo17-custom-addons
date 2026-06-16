/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { AttendeeCalendarController } from "@calendar/views/attendee_calendar/attendee_calendar_controller";
import { patch } from "@web/core/utils/patch";

// Adds an explicit "Sync now" action to the calendar: pull the latest changes
// from Google Calendar on demand, even when already connected (the stock
// "configured" button only STOPS the sync on click). Reuses the native model
// sync the calendar already runs on load — the proven path that handles
// auth/config edge cases — then reloads so pulled changes show immediately.
patch(AttendeeCalendarController.prototype, {
    async onForceGoogleSyncNow() {
        const syncResult = await this.model.syncGoogleCalendar();
        if (syncResult && syncResult.status === "need_auth") {
            window.location.assign(syncResult.url);
            return;
        }
        await this.model.load();
        this.env.services.notification.add(
            _t("Calendar synced with Google."),
            { title: _t("Google Calendar"), type: "success" },
        );
    },
});
