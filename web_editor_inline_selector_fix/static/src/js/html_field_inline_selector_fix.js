/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { HtmlField } from "@web_editor/js/backend/html_field";
import { getCSSRules } from "@web_editor/js/backend/convert_inline";

/**
 * `getCSSRules()` reads every stylesheet of the document, including the ones a
 * browser ad-blocker injects into the page. It splits each `selectorText` with
 * `RE_COMMAS_OUTSIDE_PARENTHESES` (convert_inline.js), a regex that ignores
 * commas in parentheses but not commas inside quotes. A cosmetic rule such as
 *
 *   div[style*="background-image: url(data:image/gif;base64,"][style$="position: absolute;"]
 *
 * is therefore torn in two syntactically invalid halves, and `classToStyle()`
 * throws a `SyntaxError` on `editable.querySelectorAll(rule.selector)`, which
 * rejects the `_toInline` promise and blocks the user from sending the message.
 *
 * `toInline()` uses `wysiwyg._rulesCache` when it is filled, so seeding that
 * cache with validated rules keeps the broken selectors away from
 * `querySelectorAll` without touching the page or any foreign stylesheet.
 */

// A selector without a quote cannot be a fragment of a torn quoted selector:
// skipping those keeps the check cheap on the ~10k rules of the Odoo assets.
const RE_QUOTE = /["']/;
const validatorEl = document.createElement("div");

/**
 * @param {string} selector
 * @returns {boolean} whether `querySelectorAll(selector)` is safe to call
 */
function isValidSelector(selector) {
    if (!RE_QUOTE.test(selector)) {
        return true;
    }
    try {
        validatorEl.querySelector(selector);
        return true;
    } catch {
        return false;
    }
}

patch(HtmlField.prototype, {
    /**
     * Seed the wysiwyg's CSS rules cache with validated rules so that
     * `toInline()` never computes - and never applies - a broken selector.
     *
     * @override
     */
    async _toInline() {
        try {
            const wysiwyg = this.wysiwyg;
            if (wysiwyg && !wysiwyg._rulesCache) {
                const editable = wysiwyg.getEditable()[0];
                const doc = editable && editable.ownerDocument;
                if (doc) {
                    const cssRules = getCSSRules(doc);
                    const validRules = cssRules.filter((rule) => isValidSelector(rule.selector));
                    const dropped = cssRules.length - validRules.length;
                    if (dropped) {
                        console.warn(
                            `[web_editor_inline_selector_fix] Ignored ${dropped} invalid CSS ` +
                            `selector(s) while inlining styles. They come from a stylesheet ` +
                            `that is not Odoo's (usually a browser ad-blocker).`
                        );
                    }
                    wysiwyg._rulesCache = validRules;
                }
            }
        } catch (error) {
            // Never let this safety net be the reason a message cannot be sent.
            console.warn("[web_editor_inline_selector_fix] Could not pre-compute CSS rules", error);
        }
        return super._toInline(...arguments);
    },
});
