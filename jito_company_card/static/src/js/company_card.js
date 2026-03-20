(function () {
    'use strict';

    var initialized = false;

    function init() {
        if (initialized) return;
        var toast = document.getElementById('copyToast');
        if (!toast) return;
        initialized = true;

        var hideTimer = null;

        function showToast(message) {
            clearTimeout(hideTimer);
            toast.textContent = message || 'Copied!';
            toast.classList.add('o_visible');
            hideTimer = setTimeout(function () {
                toast.classList.remove('o_visible');
            }, 1400);
        }

        function copyText(text) {
            if (navigator.clipboard && window.isSecureContext) {
                return navigator.clipboard.writeText(text);
            }
            // Fallback for HTTP or older browsers
            var ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.left = '-9999px';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            try {
                document.execCommand('copy');
            } catch (e) {
                // ignore
            }
            document.body.removeChild(ta);
            return Promise.resolve();
        }

        function copyAndFlash(el, message) {
            var text = el.getAttribute('data-copy-value');
            if (!text) return;

            copyText(text).then(function () {
                el.classList.add('o_copied');
                showToast(message);
                setTimeout(function () {
                    el.classList.remove('o_copied');
                }, 1400);
            });
        }

        // Click-to-copy on individual copyable fields
        var copyables = document.querySelectorAll('.o_copyable');
        for (var i = 0; i < copyables.length; i++) {
            (function (el) {
                el.addEventListener('click', function (e) {
                    // Don't copy if user clicked a link (let the link work)
                    if (e.target.closest && e.target.closest('a')) return;
                    e.preventDefault();
                    copyAndFlash(el, 'Copied!');
                });
            })(copyables[i]);
        }

        // Copy All button
        var copyAllBtn = document.getElementById('copyAllBtn');
        if (copyAllBtn) {
            copyAllBtn.addEventListener('click', function (e) {
                e.preventDefault();
                copyAndFlash(copyAllBtn, 'All details copied!');
            });
        }
    }

    // Ensure init runs when DOM is ready
    if (document.readyState === 'complete' || document.readyState === 'interactive') {
        setTimeout(init, 0);
    } else {
        document.addEventListener('DOMContentLoaded', init);
    }
    // Safety net
    window.addEventListener('load', init);
})();
