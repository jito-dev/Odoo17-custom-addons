/** @odoo-module **/

import publicWidget from '@web/legacy/js/public/public_widget';
import { _t } from '@web/core/l10n/translation';

// Long enough to be noticed by somebody looking at their banking app rather than at this page,
// short enough that a second copy does not feel blocked by the first.
const COPIED_MS = 2000;
const TOAST_MS = 1600;

/**
 * The bank transfer card.
 *
 * The customer is retyping a dozen values into their banking app, so every row is one click.
 * Rows and buttons are real `<button>` elements, which is where Enter, Space, the focus ring and
 * the accessible name come from - none of that is implemented here.
 *
 * What lands on the clipboard is `data-copy`, not what is on screen: a bank form refuses a
 * grouped IBAN and refuses an amount carrying its currency code.
 *
 * Folding is the browser's own `<details>`; this widget never touches it, except to force the
 * card open before printing.
 */
publicWidget.registry.JitoPortalPayment = publicWidget.Widget.extend({
    selector: '.jt-pay',
    events: {
        'click .jt-row': '_onCopyRow',
        'click .jt-amount': '_onCopyAmount',
        'click .jt-all': '_onCopyAll',
    },

    start() {
        this.timers = new Map();
        this.activeRow = null;
        this.toast = this.el.querySelector('.jt-toast');
        this.toastText = this.el.querySelector('.jt-toast-text');
        this.announcer = this.el.querySelector('.jt-sr');

        this.el.querySelectorAll('.jt-value[data-group]').forEach(el => this._group(el));

        // A closed <details> renders nothing at all, so a customer who folded the card and hit
        // print would be handed a header with no bank details under it.
        this._onBeforePrint = () => this._setPrintOpen(true);
        this._onAfterPrint = () => this._setPrintOpen(false);
        window.addEventListener('beforeprint', this._onBeforePrint);
        window.addEventListener('afterprint', this._onAfterPrint);

        return this._super(...arguments);
    },

    destroy() {
        this.timers.forEach(timer => clearTimeout(timer));
        this.timers.clear();
        window.removeEventListener('beforeprint', this._onBeforePrint);
        window.removeEventListener('afterprint', this._onAfterPrint);
        this._super(...arguments);
    },

    /**
     * Open every folded card for printing, and put back exactly what the customer had.
     *
     * @param {boolean} printing
     */
    _setPrintOpen(printing) {
        this.el.querySelectorAll('details').forEach(details => {
            if (printing) {
                if (!details.open) {
                    details.dataset.jtWasClosed = '1';
                    details.open = true;
                }
            } else if (details.dataset.jtWasClosed) {
                delete details.dataset.jtWasClosed;
                details.open = false;
            }
        });
    },

    /**
     * Show a monospace value in blocks, without putting a single space in the text.
     *
     * An IBAN is printed in fours and checked by eye in fours, but the spaces are refused by many
     * bank forms - so the blocks are separate spans held apart by a margin. Selecting the value
     * by hand then yields the same unbroken run of characters the copy button does.
     *
     * @param {HTMLElement} el
     */
    _group(el) {
        const size = parseInt(el.dataset.group || '0', 10);
        if (size <= 0) {
            return;
        }
        const bare = el.textContent.replace(/\s+/g, '');
        el.textContent = '';
        for (let i = 0; i < bare.length; i += size) {
            const span = document.createElement('span');
            span.className = 'jt-g';
            span.textContent = bare.slice(i, i + size);
            el.appendChild(span);
        }
    },

    /**
     * Put `text` on the clipboard.
     *
     * The Clipboard API needs a secure context, which an on-premise portal served over plain
     * HTTP is not; the textarea path covers that. When neither works the customer is told to
     * copy by hand, because silence would leave them wondering whether the click registered.
     *
     * @param {string} text
     * @returns {Promise<boolean>}
     */
    async _copy(text) {
        if (window.isSecureContext && navigator.clipboard) {
            try {
                await navigator.clipboard.writeText(text);
                return true;
            } catch {
                // Fall through to the textarea.
            }
        }
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
    },

    /** The toast is decoration for a screen reader; this is the announcement it cannot see. */
    _announce(message) {
        if (!this.announcer) {
            return;
        }
        this.announcer.textContent = '';
        setTimeout(() => { this.announcer.textContent = message; }, 60);
    },

    /**
     * @param {string} message Names what landed, not that something did: a click can miss by one
     *                         row, and "Copied" would not tell the customer that it had.
     */
    _toast(message) {
        this._announce(message);
        if (!this.toast || !this.toastText) {
            return;
        }
        this.toastText.textContent = message;
        this.toast.classList.add('jt-toast--on');
        clearTimeout(this.timers.get('toast'));
        this.timers.set('toast', setTimeout(
            () => this.toast.classList.remove('jt-toast--on'), TOAST_MS
        ));
    },

    _copyFailed() {
        this._toast(_t("Press Ctrl/Cmd+C to copy"));
    },

    /** Only ever one row lit: two of them would leave the customer unsure which one they took. */
    _markRow(row) {
        if (this.activeRow && this.activeRow !== row) {
            this.activeRow.classList.remove('jt-copied');
        }
        clearTimeout(this.timers.get('row'));
        this.activeRow = row;
        row.classList.add('jt-copied');
        this.timers.set('row', setTimeout(() => {
            row.classList.remove('jt-copied');
            if (this.activeRow === row) {
                this.activeRow = null;
            }
        }, COPIED_MS));
    },

    async _onCopyRow(ev) {
        const row = ev.currentTarget;
        if (!await this._copy(row.dataset.copy || '')) {
            this._copyFailed();
            return;
        }
        this._markRow(row);
        const label = row.querySelector('.jt-label-idle');
        this._toast(_t("%s copied", label ? label.textContent.trim() : _t("Value")));
    },

    /**
     * The amount and the "Copy details" button both sit inside the <summary>, where a click that
     * reaches the browser folds the card shut.
     */
    async _onCopyAmount(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        if (!await this._copy(ev.currentTarget.dataset.copy || '')) {
            this._copyFailed();
            return;
        }
        this._toast(_t("Amount copied"));
    },

    async _onCopyAll(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        const button = ev.currentTarget;
        if (!await this._copy(button.dataset.copyAll || '')) {
            this._copyFailed();
            return;
        }
        button.classList.add('jt-copied');
        clearTimeout(this.timers.get('all'));
        this.timers.set('all', setTimeout(
            () => button.classList.remove('jt-copied'), COPIED_MS
        ));
        this._toast(_t("All payment details copied"));
    },
});

export default publicWidget.registry.JitoPortalPayment;
