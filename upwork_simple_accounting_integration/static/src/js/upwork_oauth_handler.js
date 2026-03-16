/** @odoo-module **/

/**
 * After the Upwork OAuth popup closes it sends a postMessage('upwork_connected').
 * We reload the page so the main form reflects the freshly stored tokens and
 * the organizations that were auto-loaded server-side during the callback.
 */
window.addEventListener('message', (ev) => {
    if (ev.data === 'upwork_connected') {
        window.location.reload();
    }
});
