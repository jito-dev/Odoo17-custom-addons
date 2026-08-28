/** @odoo-module **/

import publicWidget from '@web/legacy/js/public/public_widget';
import { _t } from '@web/core/l10n/translation';

/**
 * Copying on the bank transfer card.
 *
 * The customer is retyping a dozen values into their bank; every one of them is one click away,
 * and the whole card is one more. What lands on the clipboard is not always what is on screen —
 * `data-copy` carries the machine form (an amount without grouping, an IBAN without spaces),
 * because that is what a bank form accepts.
 */
publicWidget.registry.TransferDetailsCard = publicWidget.Widget.extend({
    selector: '.o_transfer_section',
    events: {
        'click .o_transfer_row': '_onCopyValue',
        'click .o_transfer_pill': '_onCopyValue',
        'click .o_transfer_copy_all': '_onCopyAll',
    },

    start() {
        this.announcer = this.el.querySelector('.o_transfer_sr');
        this.timers = new Map();
        return this._super(...arguments);
    },

    destroy() {
        this.timers.forEach(timer => clearTimeout(timer));
        this._super(...arguments);
    },

    /**
     * Put `text` on the clipboard, falling back to a hidden textarea.
     *
     * The Clipboard API needs a secure context and is refused outright in some embedded ones. The
     * fallback still works there, and when neither does the customer is told to copy by hand
     * rather than left wondering whether the click registered.
     */
    async _copy(text) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch {
            const helper = document.createElement('textarea');
            helper.value = text;
            helper.setAttribute('readonly', '');
            helper.style.position = 'fixed';
            helper.style.opacity = '0';
            document.body.appendChild(helper);
            helper.select();
            let copied = false;
            try {
                copied = document.execCommand('copy');
            } catch {
                copied = false;
            }
            document.body.removeChild(helper);
            return copied;
        }
    },

    /** Announce to a screen reader; the visual confirmation is the green tile. */
    _announce(message) {
        if (!this.announcer) {
            return;
        }
        this.announcer.textContent = '';
        setTimeout(() => { this.announcer.textContent = message; }, 60);
    },

    /** Show the copied state for `duration`, restarting the timer if it is clicked again. */
    _flash(element, duration) {
        clearTimeout(this.timers.get(element));
        element.classList.add('o_transfer_is_copied');
        this.timers.set(element, setTimeout(
            () => element.classList.remove('o_transfer_is_copied'), duration
        ));
    },

    async _onCopyValue(ev) {
        const element = ev.currentTarget;
        if (!await this._copy(element.dataset.copy || '')) {
            this._announce(_t("Could not copy. Select the value and copy it manually."));
            return;
        }
        this._flash(element, 1500);
        const label = element.querySelector('.o_transfer_idle');
        this._announce(_t("%s copied", label ? label.textContent.trim() : _t("Value")));
    },

    async _onCopyAll(ev) {
        const button = ev.currentTarget;
        if (!await this._copy(button.dataset.copyAll || '')) {
            this._announce(_t("Could not copy. Select the details and copy them manually."));
            return;
        }
        this._flash(button, 1800);
        this._announce(_t("All payment details copied"));
    },
});

export default publicWidget.registry.TransferDetailsCard;
