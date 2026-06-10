/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

/**
 * Confirmation modals for the recruitment interview confirmation page.
 *
 * The QWeb inherit (appointment_templates.xml) renders, for recruitment
 * bookings only, an action bar plus two hidden confirmation modals
 * (Cancel / Reschedule) inside ``.o_cs_appointment_actions``. The destructive
 * actions are NOT plain links anymore: their trigger buttons (``[data-cs-open]``)
 * just reveal the matching overlay; the actual cancel/reschedule navigation
 * lives on the ``<a>`` inside each modal, so nothing happens until the
 * candidate explicitly confirms.
 *
 * Everything is delegated within ``this.el`` (the overlays are children of the
 * bar wrapper), mirroring the native ``appointmentValidation`` widget.
 */
publicWidget.registry.callStageAppointmentConfirm = publicWidget.Widget.extend({
    selector: '.o_cs_appointment_actions',
    events: {
        'click [data-cs-open]': '_onOpen',
        'click [data-cs-close]': '_onClose',
        'click .o_appointment_modal_overlay': '_onOverlayClick',
    },

    /**
     * @override
     */
    start: function () {
        // Close on Escape — bound on the document (key events do not bubble
        // through the delegated map the way clicks do). Stored so destroy()
        // can detach it cleanly.
        this._onKeydown = (ev) => {
            if (ev.key === 'Escape') {
                this._closeAll();
            }
        };
        document.addEventListener('keydown', this._onKeydown);

        // Auto-open the matching modal when the candidate arrived from a
        // "Cancel"/"Reschedule" link in their calendar invite (those carry
        // ``?cs_action=cancel|reschedule``), so the link feels direct while the
        // confirmation step is preserved.
        const action = new URLSearchParams(window.location.search).get('cs_action');
        if (action === 'cancel' || action === 'reschedule') {
            const overlay = this.el.querySelector(`.o_appointment_modal_overlay[data-cs-modal="${action}"]`);
            if (overlay) {
                overlay.classList.add('active');
            }
        }
        return this._super(...arguments);
    },

    /**
     * @override
     */
    destroy: function () {
        if (this._onKeydown) {
            document.removeEventListener('keydown', this._onKeydown);
        }
        this._super(...arguments);
    },

    _closeAll: function () {
        this.el.querySelectorAll('.o_appointment_modal_overlay.active')
            .forEach((overlay) => overlay.classList.remove('active'));
    },

    _onOpen: function (ev) {
        ev.preventDefault();
        const which = ev.currentTarget.dataset.csOpen;
        const overlay = this.el.querySelector(`.o_appointment_modal_overlay[data-cs-modal="${which}"]`);
        if (overlay) {
            this._closeAll();
            overlay.classList.add('active');
        }
    },

    _onClose: function (ev) {
        ev.preventDefault();
        this._closeAll();
    },

    /**
     * Close only when the dimmed backdrop itself is clicked, never when the
     * click lands inside the modal box.
     */
    _onOverlayClick: function (ev) {
        if (ev.target === ev.currentTarget) {
            ev.currentTarget.classList.remove('active');
        }
    },
});

export default publicWidget.registry.callStageAppointmentConfirm;
