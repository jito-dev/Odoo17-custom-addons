/** @odoo-module **/

// ============================================================================
//  Minimalist Appointment Theme — "Continue" step for time selection
//  ---------------------------------------------------------------------------
//  Stock `appointment` navigates straight to the Details page the instant a
//  time slot is clicked (see core `appointment_select_appointment_slot.js`,
//  `_onClickHoursSlot`: `document.location = url`). For recruitment Call Stage
//  bookings we want a softer flow: clicking a time only *selects* it and opens
//  a small themed summary card (day + time) with an explicit **Continue**
//  button. The user reviews the choice, then clicks Continue to proceed to the
//  same Details URL core would have navigated to.
//
//  Scope & safety
//  --------------
//  * The override is a no-op unless the page is a recruitment booking, detected
//    by the `.o_jito_minbook` class this module already puts on `#wrap`. On any
//    other appointment page `_super` runs and behaviour is byte-for-byte stock.
//  * Only the "direct navigate" branch is intercepted (user-based bookings,
//    which Call Stage always is). The resource/`time_resource` branch — which
//    already needs a Confirm step of its own — is left entirely to core.
//  * The target URL is built exactly like core, from the same hidden inputs and
//    the slot's `data-url-parameters`, so the destination is identical.
// ============================================================================

import publicWidget from "@web/legacy/js/public/public_widget";

const { DateTime } = luxon;

const SlotSelect = publicWidget.registry.appointmentSlotSelect;

SlotSelect.include({
    // Add a delegated handler for our Continue button on top of core's events.
    // Delegation is from the widget root (`.o_appointment`), so it keeps working
    // even though the card is injected into the dynamically-rebuilt `#slotsList`.
    events: Object.assign({}, SlotSelect.prototype.events, {
        "click .o_minbook_continue": "_onMinbookContinue",
    }),

    /**
     * True only on a recruitment Call Stage booking — i.e. when this module has
     * tagged the page `#wrap` with `o_jito_minbook`. Everywhere else this widget
     * must behave exactly like stock `appointment`.
     */
    _isMinbookBooking() {
        return !!this.el.closest(".o_jito_minbook");
    },

    /**
     * @override
     * On recruitment bookings, intercept the slot click: select the slot and
     * reveal a themed summary card with a Continue button instead of navigating
     * away immediately. All other cases fall through to core.
     */
    _onClickHoursSlot(ev) {
        if (!this._isMinbookBooking()) {
            return this._super(...arguments);
        }

        const assignMethod = this.$el.find("input[name='assign_method']").val();
        const scheduleBasedOn = this.$("input[name='schedule_based_on']").val();
        const directNavigate = assignMethod !== "time_resource" || scheduleBasedOn === "users";

        // Only the branch that core would navigate from is changed. The
        // resource-selection branch keeps its own Confirm flow untouched.
        if (!directNavigate) {
            return this._super(...arguments);
        }

        this.$(".o_slot_hours.o_slot_hours_selected").removeClass("o_slot_hours_selected active");
        this.$(ev.currentTarget).addClass("o_slot_hours_selected active");

        // Build the Details URL identically to core's `_onClickHoursSlot`.
        const appointmentTypeID = this.$("input[name='appointment_type_id']").val();
        const urlParameters = decodeURIComponent(this.$(".o_slot_hours_selected").data("urlParameters"));
        const url = new URL(
            `/appointment/${encodeURIComponent(appointmentTypeID)}/info?${urlParameters}`,
            location.origin
        );
        this._renderMinbookContinue(encodeURI(url.href), ev.currentTarget);
    },

    /**
     * Render (or refresh) the themed summary card under the slot list. Shows the
     * selected day and time and a Continue button that carries the target URL.
     * Re-rendered on every slot click so picking a different time just updates it.
     */
    _renderMinbookContinue(href, slotButton) {
        const slotDate = this.$(".o_slot_selected").data("slotDate");
        const dayLabel = slotDate ? DateTime.fromISO(slotDate).toFormat("cccc, dd MMMM yyyy") : "";
        const timeLabel = (slotButton.textContent || "").trim();

        this.$(".o_minbook_continue_wrap").remove();

        const $card = $(`
            <div class="o_minbook_continue_wrap mt-3">
                <div class="o_minbook_continue_card">
                    <span class="o_minbook_continue_kicker">Your appointment</span>
                    <div class="o_minbook_continue_row">
                        <i class="fa fa-calendar-o fa-fw" role="img" aria-label="Date"></i>
                        <span class="o_minbook_continue_day"></span>
                    </div>
                    <div class="o_minbook_continue_row">
                        <i class="fa fa-clock-o fa-fw" role="img" aria-label="Time"></i>
                        <span class="o_minbook_continue_time"></span>
                    </div>
                </div>
                <button type="button" class="o_minbook_continue btn btn-primary w-100 mt-3">Continue</button>
            </div>
        `);

        // Assign text via jQuery (never via innerHTML) so slot content can never
        // inject markup. The URL is held on a data attribute, read back on click.
        $card.find(".o_minbook_continue_day").text(dayLabel);
        $card.find(".o_minbook_continue_time").text(timeLabel);
        $card.find(".o_minbook_continue").attr("data-href", href);

        this.$slotsList.append($card);
    },

    /**
     * Continue button: navigate to the Details URL captured at slot-selection
     * time — the same destination stock `appointment` would have gone to.
     */
    _onMinbookContinue(ev) {
        const href = this.$(ev.currentTarget).attr("data-href");
        if (href) {
            document.location = href;
        }
    },
});
