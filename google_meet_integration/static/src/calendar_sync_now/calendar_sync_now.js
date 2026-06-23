/** @odoo-module **/

import { AttendeeCalendarController } from "@calendar/views/attendee_calendar/attendee_calendar_controller";
import { patch } from "@web/core/utils/patch";

// Adds an explicit "Sync now" action to the calendar: force a refresh of
// Google Calendar on demand, even when already connected (the stock
// "configured" button only STOPS the sync on click).
//
// Routes through the backend `res.users.action_sync_google_calendar_now` so
// this toolbar button matches the "Sync Google now" menu: a FORCED FULL sync
// over the recent-past → near-future window (default -7d/+30d), not the stock
// incremental ±1y pull. Forcing a full sync is what re-imports meetings that
// the incremental sync silently never re-fetches; the focused window keeps it
// fast. The action returns a notification (success / not-connected warning /
// failure); we reload first so pulled events show at once, then surface it.
patch(AttendeeCalendarController.prototype, {
    async onForceGoogleSyncNow() {
        const action = await this.env.services.orm.call(
            "res.users", "action_sync_google_calendar_now", [[]],
        );
        await this.model.load();
        if (action) {
            this.env.services.action.doAction(action);
        }
    },
});
