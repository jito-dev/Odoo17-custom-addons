/** @odoo-module **/

import publicWidget from '@web/legacy/js/public/public_widget';
import { _t } from '@web/core/l10n/translation';

const COPIED_MS = 1700;
const CASCADE_MS = 55;
const TOAST_MS = 2200;

const ICON_COPY =
    '<svg class="jt-ico-copy" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<rect x="9" y="9" width="12" height="12" rx="2"/>' +
    '<path d="M5 15V5a2 2 0 0 1 2-2h8"/></svg>';

const ICON_DONE =
    '<svg class="jt-ico-done" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M4 12.5l5.5 5.5L20 7"/></svg>';

/**
 * The bank transfer card.
 *
 * The customer is retyping a dozen values into their banking app, so every row is one click —
 * and one Enter, and one Space, because a finance person on a keyboard should not have to reach
 * for the mouse. What lands on the clipboard is `data-copy`, not what is on screen: a bank form
 * refuses a grouped IBAN and refuses an amount carrying its currency code.
 */
publicWidget.registry.JitoPortalPayment = publicWidget.Widget.extend({
    selector: '.jt-pay',
    events: {
        'click .jt-row': '_onCopyRow',
        'keydown .jt-row': '_onKeyRow',
        'click .jt-all': '_onCopyAll',
    },

    start() {
        this.timers = new Map();
        this.card = this.el.querySelector('.jt-card');
        this.announcer = this.el.querySelector('.jt-sr');

        this.el.querySelectorAll('.jt-copy').forEach(slot => {
            slot.innerHTML = ICON_COPY + ICON_DONE;
        });
        this.el.querySelectorAll('.jt-value--mono').forEach(el => this._group(el));

        return this._super(...arguments);
    },

    destroy() {
        this.timers.forEach(timer => clearTimeout(timer));
        this.timers.clear();
        this._super(...arguments);
    },

    /**
     * Split a monospace value into the blocks that light up in sequence.
     *
     * An IBAN is grouped by four because that is how it is printed and how it is checked by eye;
     * everything else lights as one block, so the effect stays a punctuation mark rather than a
     * light show.
     */
    _group(el) {
        const size = parseInt(el.dataset.group || '0', 10);
        const text = el.textContent;
        const chunks = [];
        if (size > 0) {
            const bare = text.replace(/\s+/g, '');
            for (let i = 0; i < bare.length; i += size) {
                chunks.push(bare.slice(i, i + size));
            }
        } else {
            chunks.push(text);
        }
        el.textContent = '';
        chunks.forEach((chunk, index) => {
            const span = document.createElement('span');
            span.className = 'jt-g';
            span.textContent = chunk;
            span.style.transitionDelay = `${index * 45}ms`;
            el.appendChild(span);
            if (size > 0 && index < chunks.length - 1) {
                el.appendChild(document.createTextNode(' '));
            }
        });
    },

    /**
     * Put `text` on the clipboard.
     *
     * The Clipboard API needs a secure context; the textarea path covers the rest. When neither
     * works the customer is told to copy by hand — silence would leave them wondering whether
     * the click registered at all.
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

    _announce(message) {
        if (!this.announcer) {
            return;
        }
        this.announcer.textContent = '';
        setTimeout(() => { this.announcer.textContent = message; }, 60);
    },

    /** Run the copied state on a row, restarting it cleanly when the row is clicked again. */
    _flash(row, delay = 0) {
        const run = () => {
            clearTimeout(this.timers.get(row));
            row.classList.remove('jt-copied');
            void row.offsetWidth;  // Reflow, so the keyframes start over rather than continue.
            row.classList.add('jt-copied');
            this.timers.set(row, setTimeout(() => row.classList.remove('jt-copied'), COPIED_MS));
        };
        if (delay) {
            const key = `${row.dataset.copy}-cascade`;
            clearTimeout(this.timers.get(key));
            this.timers.set(key, setTimeout(run, delay));
        } else {
            run();
        }
    },

    async _onCopyRow(ev) {
        const row = ev.currentTarget;
        if (!await this._copy(row.dataset.copy || '')) {
            this._announce(_t("Could not copy. Select the value and copy it manually."));
            return;
        }
        this._flash(row);
        const label = row.querySelector('.jt-label-idle');
        this._announce(_t("%s copied", label ? label.textContent.trim() : _t("Value")));
    },

    _onKeyRow(ev) {
        if (ev.key !== 'Enter' && ev.key !== ' ' && ev.key !== 'Spacebar') {
            return;
        }
        ev.preventDefault();  // Space would scroll the page out from under the customer.
        this._onCopyRow(ev);
    },

    async _onCopyAll(ev) {
        if (!await this._copy(ev.currentTarget.dataset.copyAll || '')) {
            this._announce(_t("Could not copy. Select the details and copy them manually."));
            return;
        }
        this.el.querySelectorAll('.jt-row').forEach(
            (row, index) => this._flash(row, index * CASCADE_MS)
        );
        this.card.classList.add('jt-toasting');
        clearTimeout(this.timers.get('toast'));
        this.timers.set('toast', setTimeout(
            () => this.card.classList.remove('jt-toasting'), TOAST_MS
        ));
        this._announce(_t("All payment details copied"));
    },
});

export default publicWidget.registry.JitoPortalPayment;
