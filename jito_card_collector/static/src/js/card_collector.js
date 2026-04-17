/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.CardCollectorGallery = publicWidget.Widget.extend({
    selector: '.cc-page',

    events: {
        'click .cc-card': '_onCardClick',
        'click .cc-overlay': '_onOverlayClick',
        'click .cc-download-btn': '_onDownloadClick',
        'click .cc-copy-link-btn': '_onCopyLinkClick',
        'click .cc-flip-btn': '_onFlipClick',
        'mousemove .cc-card-wrapper': '_onCardMouseMove',
        'mouseleave .cc-card-wrapper': '_onCardMouseLeave',
        'mouseenter .cc-card-wrapper': '_onCardMouseEnter',
    },

    start: function () {
        // Create the backdrop overlay (once)
        this.overlay = document.createElement('div');
        this.overlay.className = 'cc-overlay';
        this.el.appendChild(this.overlay);
        this.zoomedWrapper = null;
        return this._super.apply(this, arguments);
    },

    _onCardClick: function (ev) {
        // Ignore clicks on any action button
        if (ev.target.closest('.cc-card-btn')) return;
        ev.stopPropagation();

        var card = ev.currentTarget;
        var wrapper = card.closest('.cc-card-wrapper');

        // If the card is currently flipped (showing the back), clicking it
        // un-flips and un-zooms. Otherwise we open the fullscreen modal.
        if (card.classList.contains('is-flipped')) {
            this._unflip(wrapper);
            return;
        }
        this._openFullscreenFromWrapper(wrapper);
    },

    _onFlipClick: function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        var btn = ev.target.closest('.cc-flip-btn');
        if (!btn) return;
        var wrapper = btn.closest('.cc-card-wrapper');
        if (!wrapper) return;
        var card = wrapper.querySelector('.cc-card');
        if (!card) return;

        if (card.classList.contains('is-flipped')) {
            this._unflip(wrapper);
        } else {
            this._flip(wrapper);
        }
    },

    // ---- Flip / unflip helpers ----

    _flip: function (wrapper) {
        var card = wrapper.querySelector('.cc-card');
        var inner = card.querySelector('.cc-card-inner');

        // Close any other zoomed card first
        if (this.zoomedWrapper && this.zoomedWrapper !== wrapper) {
            var prevCard = this.zoomedWrapper.querySelector('.cc-card');
            if (prevCard) prevCard.classList.remove('is-flipped');
            this.zoomedWrapper.classList.remove('is-zoomed');
        }

        card.classList.add('is-flipped');
        wrapper.classList.add('is-zoomed');
        this.overlay.classList.add('is-active');
        this.zoomedWrapper = wrapper;

        if (inner) {
            inner.style.transform = '';
            inner.style.transition = 'transform 0.7s cubic-bezier(0.4, 0, 0.2, 1)';
        }
    },

    _unflip: function (wrapper) {
        var card = wrapper.querySelector('.cc-card');
        var inner = card.querySelector('.cc-card-inner');

        card.classList.remove('is-flipped');
        wrapper.classList.remove('is-zoomed');
        this.overlay.classList.remove('is-active');
        if (this.zoomedWrapper === wrapper) {
            this.zoomedWrapper = null;
        }
        if (inner) {
            inner.style.transform = '';
            inner.style.transition = 'transform 0.7s cubic-bezier(0.4, 0, 0.2, 1)';
        }
    },

    _onOverlayClick: function () {
        // Click on backdrop closes zoomed card
        if (!this.zoomedWrapper) return;
        var card = this.zoomedWrapper.querySelector('.cc-card');
        if (card) card.classList.remove('is-flipped');
        this.zoomedWrapper.classList.remove('is-zoomed');
        this.overlay.classList.remove('is-active');

        var inner = this.zoomedWrapper.querySelector('.cc-card-inner');
        if (inner) {
            inner.style.transform = '';
        }
        this.zoomedWrapper = null;
    },

    // ---- Download: render full card to canvas ----

    _onDownloadClick: function (ev) {
        ev.preventDefault();
        ev.stopPropagation();

        var btn = ev.target.closest('.cc-download-btn');
        var wrapper = btn.closest('.cc-card-wrapper');
        var imgEl = wrapper.querySelector('.cc-card-image');
        var nameEl = wrapper.querySelector('.cc-card-name');
        var cardName = nameEl ? nameEl.textContent.trim() : 'card';
        var self = this;

        // Load fresh copy to avoid tainted canvas
        var img = new Image();
        img.crossOrigin = 'anonymous';
        img.onload = function () {
            self._renderCardToCanvas(img, cardName);
        };
        img.onerror = function () {
            // Fallback: open the raw image in a new tab
            window.open(imgEl.src, '_blank');
        };
        img.src = imgEl.src;
    },

    _renderCardToCanvas: function (img, cardName) {
        var canvas = document.createElement('canvas');
        var ctx = canvas.getContext('2d');

        // 2x resolution for crisp output
        var W = 560, H = 800;
        var B = 12;   // border thickness
        var R = 32;   // corner radius
        var infoH = 70; // name bar height
        var pad = 20;   // image padding

        canvas.width = W;
        canvas.height = H;

        // 1. Silver gradient border
        var grad = ctx.createLinearGradient(0, 0, W, H);
        grad.addColorStop(0, '#707070');
        grad.addColorStop(0.25, '#b0b0b0');
        grad.addColorStop(0.5, '#ffffff');
        grad.addColorStop(0.75, '#b0b0b0');
        grad.addColorStop(1, '#707070');
        ctx.fillStyle = grad;
        this._roundRect(ctx, 0, 0, W, H, R);

        // 2. Inner dark background
        ctx.fillStyle = '#111118';
        this._roundRect(ctx, B, B, W - 2 * B, H - 2 * B, R - 4);

        // 3. Card image — centered, aspect-ratio preserved
        var imgAreaX = B + pad;
        var imgAreaY = B + pad;
        var imgAreaW = W - 2 * (B + pad);
        var imgAreaH = H - 2 * B - infoH - pad;

        var scale = Math.min(imgAreaW / img.naturalWidth, imgAreaH / img.naturalHeight);
        var dw = img.naturalWidth * scale;
        var dh = img.naturalHeight * scale;
        var dx = imgAreaX + (imgAreaW - dw) / 2;
        var dy = imgAreaY + (imgAreaH - dh) / 2;

        ctx.save();
        this._roundRect(ctx, dx, dy, dw, dh, 12, true);
        ctx.clip();
        ctx.drawImage(img, dx, dy, dw, dh);
        ctx.restore();

        // 4. Thin separator line
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
        ctx.lineWidth = 1;
        var lineY = H - B - infoH;
        ctx.beginPath();
        ctx.moveTo(B + 16, lineY);
        ctx.lineTo(W - B - 16, lineY);
        ctx.stroke();

        // 5. Card name text
        ctx.fillStyle = '#eeeeee';
        ctx.font = 'bold 24px sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        var nameY = H - B - infoH / 2;
        var maxTextW = W - 2 * (B + 24);
        var text = cardName;
        while (ctx.measureText(text).width > maxTextW && text.length > 3) {
            text = text.slice(0, -4) + '\u2026';
        }
        ctx.fillText(text, W / 2, nameY);

        // 6. Trigger download
        var fileName = cardName;
        canvas.toBlob(function (blob) {
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = fileName + '.png';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }, 'image/png');
    },

    _roundRect: function (ctx, x, y, w, h, r, clipOnly) {
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.lineTo(x + w - r, y);
        ctx.quadraticCurveTo(x + w, y, x + w, y + r);
        ctx.lineTo(x + w, y + h - r);
        ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
        ctx.lineTo(x + r, y + h);
        ctx.quadraticCurveTo(x, y + h, x, y + h - r);
        ctx.lineTo(x, y + r);
        ctx.quadraticCurveTo(x, y, x + r, y);
        ctx.closePath();
        if (!clipOnly) ctx.fill();
    },

    // ---- Copy share link ----

    _onCopyLinkClick: function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        var btn = ev.target.closest('.cc-copy-link-btn');
        if (!btn) return;
        var url = btn.getAttribute('data-share-url');
        if (!url) return;

        var self = this;
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(url).then(function () {
                self._showCopyFeedback(btn);
            }).catch(function () {
                self._fallbackCopy(url, btn);
            });
        } else {
            this._fallbackCopy(url, btn);
        }
    },

    _fallbackCopy: function (url, btn) {
        var ta = document.createElement('textarea');
        ta.value = url;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try {
            document.execCommand('copy');
            this._showCopyFeedback(btn);
        } catch (e) {
            // ignore
        }
        document.body.removeChild(ta);
    },

    _showCopyFeedback: function (btn) {
        btn.classList.add('is-copied');
        var icon = btn.querySelector('i');
        var oldClass = icon ? icon.className : null;
        if (icon) icon.className = 'fa fa-check';
        setTimeout(function () {
            btn.classList.remove('is-copied');
            if (icon && oldClass) icon.className = oldClass;
        }, 1500);
    },

    // ---- Fullscreen expand view ----

    _openFullscreenFromWrapper: function (wrapper) {
        if (!wrapper) return;
        var imgEl = wrapper.querySelector('.cc-card-image');
        var nameEl = wrapper.querySelector('.cc-card-name');

        var imgSrc = imgEl ? imgEl.src : '';
        var name = nameEl ? nameEl.textContent.trim() : '';
        // The description lives on the wrapper as a data attribute since the
        // card back no longer renders it visually.
        var desc = (wrapper.dataset.description || '').trim();

        this._openFullscreen(imgSrc, name, desc);
    },

    _openFullscreen: function (imgSrc, name, desc) {
        var modal = document.createElement('div');
        modal.className = 'cc-fullscreen-modal';

        // Content wrapper
        var content = document.createElement('div');
        content.className = 'cc-fs-content';

        // --- Card visual (reuse frame + image + name styling) ---
        var fsCard = document.createElement('div');
        fsCard.className = 'cc-fs-card';

        var frame = document.createElement('div');
        frame.className = 'cc-card-frame';

        var imgWrap = document.createElement('div');
        imgWrap.className = 'cc-card-image-wrapper';
        var img = document.createElement('img');
        img.src = imgSrc;
        img.alt = name;
        img.className = 'cc-card-image';
        imgWrap.appendChild(img);

        var info = document.createElement('div');
        info.className = 'cc-card-info';
        var nameH = document.createElement('h3');
        nameH.className = 'cc-card-name';
        nameH.textContent = name;
        info.appendChild(nameH);

        frame.appendChild(imgWrap);
        frame.appendChild(info);
        fsCard.appendChild(frame);

        // --- Info panel (title + divider + description) ---
        var infoPanel = document.createElement('div');
        infoPanel.className = 'cc-fs-info';

        var title = document.createElement('h2');
        title.className = 'cc-fs-title';
        title.textContent = name;
        infoPanel.appendChild(title);

        var divider = document.createElement('div');
        divider.className = 'cc-fs-divider';
        infoPanel.appendChild(divider);

        var descDiv = document.createElement('div');
        descDiv.className = 'cc-fs-description';
        if (desc) {
            descDiv.textContent = desc;
        } else {
            var em = document.createElement('em');
            em.textContent = 'No description';
            descDiv.appendChild(em);
        }
        infoPanel.appendChild(descDiv);

        content.appendChild(fsCard);
        content.appendChild(infoPanel);

        // Close button
        var closeBtn = document.createElement('button');
        closeBtn.className = 'cc-fs-close';
        closeBtn.textContent = '\u00D7';
        closeBtn.setAttribute('aria-label', 'Close');

        modal.appendChild(content);
        modal.appendChild(closeBtn);
        document.body.appendChild(modal);

        // Close handlers
        var escHandler;
        var close = function () {
            modal.classList.add('is-closing');
            setTimeout(function () {
                if (modal.parentNode) modal.parentNode.removeChild(modal);
            }, 200);
            document.removeEventListener('keydown', escHandler);
        };
        escHandler = function (e) {
            if (e.key === 'Escape') close();
        };
        closeBtn.addEventListener('click', close);
        modal.addEventListener('click', function (e) {
            if (e.target === modal) close();
        });
        document.addEventListener('keydown', escHandler);
    },

    // ---- Tilt / shimmer effects ----

    _onCardMouseMove: function (ev) {
        var wrapper = ev.currentTarget;
        // No tilt while zoomed/flipped
        if (wrapper.classList.contains('is-zoomed')) return;

        var card = wrapper.querySelector('.cc-card');
        var inner = card.querySelector('.cc-card-inner');
        var shimmer = wrapper.querySelector('.cc-shimmer');
        if (!inner || !shimmer) return;

        var rect = wrapper.getBoundingClientRect();
        var x = (ev.clientX - rect.left) / rect.width;
        var y = (ev.clientY - rect.top) / rect.height;

        var tiltY = (x - 0.5) * 16;
        var tiltX = (0.5 - y) * 12;

        inner.style.transform =
            'rotateX(' + tiltX + 'deg) rotateY(' + tiltY + 'deg)';

        shimmer.style.backgroundPosition = (x * 100) + '% 0';
        shimmer.style.opacity = '1';
    },

    _onCardMouseLeave: function (ev) {
        var wrapper = ev.currentTarget;
        if (wrapper.classList.contains('is-zoomed')) return;

        var inner = wrapper.querySelector('.cc-card-inner');
        var shimmer = wrapper.querySelector('.cc-shimmer');
        if (!inner) return;

        inner.style.transition = 'transform 0.5s cubic-bezier(0.4, 0, 0.2, 1)';
        inner.style.transform = '';

        setTimeout(function () {
            inner.style.transition = 'transform 0.7s cubic-bezier(0.4, 0, 0.2, 1)';
        }, 500);

        if (shimmer) {
            shimmer.style.opacity = '0';
        }
    },

    _onCardMouseEnter: function (ev) {
        var wrapper = ev.currentTarget;
        if (wrapper.classList.contains('is-zoomed')) return;

        var inner = wrapper.querySelector('.cc-card-inner');
        if (inner) {
            inner.style.transition = 'transform 0.15s ease-out';
        }
    },
});
