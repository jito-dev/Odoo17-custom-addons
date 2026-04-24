/** @odoo-module **/

import { registry } from "@web/core/registry";
import { QuickReportDialog } from "./quick_report_dialog";
import { loadJS } from "@web/core/assets";
import { whenReady } from "@odoo/owl";

const MAX_CONSOLE_ERRORS = 50;
const MAX_TEXT_LENGTH = 200;

// ---------------------------------------------------------------------------
// Console error ring buffer (module-level so it starts capturing immediately)
// ---------------------------------------------------------------------------
const consoleErrors = [];
const _origConsoleError = console.error;
const _origConsoleWarn = console.warn;

function _pushError(level, args) {
    consoleErrors.push({
        level,
        message: Array.from(args).map(String).join(" "),
        time: new Date().toISOString(),
    });
    if (consoleErrors.length > MAX_CONSOLE_ERRORS) {
        consoleErrors.shift();
    }
}

console.error = function (...args) {
    _pushError("error", args);
    return _origConsoleError.apply(console, args);
};
console.warn = function (...args) {
    _pushError("warn", args);
    return _origConsoleWarn.apply(console, args);
};

// ---------------------------------------------------------------------------
// Context capture helpers
// ---------------------------------------------------------------------------

/**
 * Walk up from the target element to find the closest Odoo field info.
 */
function _getFieldInfo(el) {
    const result = { fieldName: null, fieldLabel: null, fieldValue: null };
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return result;

    // Find closest .o_field_widget
    const fieldWidget = el.closest(".o_field_widget");
    if (fieldWidget) {
        result.fieldName = fieldWidget.getAttribute("name") || null;

        // Try to read displayed value
        const input = fieldWidget.querySelector("input, textarea, select");
        if (input) {
            result.fieldValue = input.value;
        } else {
            const span = fieldWidget.querySelector(".o_field_widget span, .o_stat_value");
            if (span) {
                result.fieldValue = span.textContent.trim();
            } else {
                // Use the widget's own text as fallback
                const text = fieldWidget.textContent.trim();
                if (text.length <= MAX_TEXT_LENGTH) {
                    result.fieldValue = text;
                }
            }
        }

        // Try to find label
        const fieldName = result.fieldName;
        if (fieldName) {
            const label = document.querySelector(
                `label[for="${fieldName}"], label.o_form_label[for="${fieldName}"]`
            );
            if (label) {
                result.fieldLabel = label.textContent.trim();
            }
        }
    }

    // Fallback: check if clicked element itself has a name attribute
    if (!result.fieldName) {
        const named = el.closest("[name]");
        if (named) {
            result.fieldName = named.getAttribute("name");
        }
    }

    // If target is an input/textarea/select directly, capture its value
    if (!result.fieldValue && el.matches("input, textarea, select")) {
        result.fieldValue = el.value;
    }

    return result;
}

/**
 * Read breadcrumb path from the DOM.
 */
function _getBreadcrumb() {
    const items = document.querySelectorAll(
        ".o_breadcrumb .breadcrumb-item, .o_control_panel_breadcrumbs .breadcrumb-item"
    );
    const parts = [];
    for (const item of items) {
        const text = item.textContent.trim();
        if (text) parts.push(text);
    }
    // Also grab the current page title if visible
    const title = document.querySelector(
        ".o_control_panel_breadcrumbs .o_last_breadcrumb_item, .o_form_view .oe_title .o_field_widget[name='name'] input, .o_form_view .oe_title .o_field_widget[name='name'] span"
    );
    if (title) {
        const text = (title.value || title.textContent || "").trim();
        if (text && !parts.includes(text)) {
            parts.push(text);
        }
    }
    return parts.join(" > ") || "Unknown page";
}

/**
 * Get current Odoo action context from URL hash.
 */
function _getOdooContext(env) {
    const result = { model: null, resId: null, viewType: null };
    try {
        const router = env.services.router;
        if (router && router.current) {
            const hash = router.current.hash;
            result.model = hash.model || null;
            result.resId = hash.id ? parseInt(hash.id, 10) : null;
            result.viewType = hash.view_type || null;
        }
    } catch {
        // Parse from URL as fallback
        const hash = window.location.hash;
        const modelMatch = hash.match(/model=([^&]+)/);
        const idMatch = hash.match(/[&?]id=(\d+)/);
        const viewMatch = hash.match(/view_type=([^&]+)/);
        if (modelMatch) result.model = modelMatch[1];
        if (idMatch) result.resId = parseInt(idMatch[1], 10);
        if (viewMatch) result.viewType = viewMatch[1];
    }
    return result;
}

/**
 * Capture full context from the click event.
 */
function captureContext(event, env) {
    // Ensure we have an Element (event.target can be a text node)
    const target = event.target.nodeType === Node.ELEMENT_NODE
        ? event.target
        : event.target.parentElement;
    const fieldInfo = _getFieldInfo(target);
    const odooCtx = _getOdooContext(env);
    const breadcrumb = _getBreadcrumb();

    // User info
    let userName = "";
    let userLogin = "";
    try {
        userName = env.services.user.name || "";
        userLogin = env.services.user.userName || "";
    } catch {
        // ignore
    }

    return {
        // Page context
        url: window.location.href,
        breadcrumb,
        model: odooCtx.model,
        resId: odooCtx.resId,
        viewType: odooCtx.viewType,

        // Clicked element
        element: {
            tag: target.tagName,
            className: (target.className || "").toString().substring(0, 300),
            text: (target.textContent || "").trim().substring(0, MAX_TEXT_LENGTH),
            fieldName: fieldInfo.fieldName,
            fieldLabel: fieldInfo.fieldLabel,
            fieldValue: fieldInfo.fieldValue
                ? String(fieldInfo.fieldValue).substring(0, MAX_TEXT_LENGTH)
                : null,
        },

        // Browser info
        userAgent: navigator.userAgent,
        screenWidth: window.screen.width,
        screenHeight: window.screen.height,
        windowWidth: window.innerWidth,
        windowHeight: window.innerHeight,

        // User
        userName,
        userLogin,

        // Console errors snapshot
        consoleErrors: consoleErrors.slice(),

        // Click coordinates (for screenshot marker)
        clickX: event.clientX,
        clickY: event.clientY,

        // Timestamp
        timestamp: new Date().toISOString(),
    };
}

// ---------------------------------------------------------------------------
// Screenshot capture
// ---------------------------------------------------------------------------

async function _captureViaScreenAPI() {
    const stream = await navigator.mediaDevices.getDisplayMedia({
        video: { mediaSource: "screen" },
    });
    const track = stream.getVideoTracks()[0];

    let canvas;
    if (typeof ImageCapture !== "undefined") {
        const imageCapture = new ImageCapture(track);
        const bitmap = await imageCapture.grabFrame();
        track.stop();
        canvas = document.createElement("canvas");
        canvas.width = bitmap.width;
        canvas.height = bitmap.height;
        canvas.getContext("2d").drawImage(bitmap, 0, 0);
    } else {
        const video = document.createElement("video");
        video.srcObject = stream;
        await video.play();
        await new Promise((resolve) => setTimeout(resolve, 200));
        canvas = document.createElement("canvas");
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        canvas.getContext("2d").drawImage(video, 0, 0);
        track.stop();
        video.remove();
    }
    return canvas.toDataURL("image/png").split(",")[1];
}

function _injectClickMarker(targetEl, clickX, clickY) {
    // Compute click position relative to the capture target element
    const rect = targetEl.getBoundingClientRect();
    const relX = clickX - rect.left + targetEl.scrollLeft;
    const relY = clickY - rect.top + targetEl.scrollTop;

    // Ensure the target has positioning context for the absolute marker
    const prevPosition = targetEl.style.position;
    if (getComputedStyle(targetEl).position === "static") {
        targetEl.style.position = "relative";
    }

    const marker = document.createElement("div");
    marker.className = "jito_qr_click_marker";
    marker.style.left = `${relX}px`;
    marker.style.top = `${relY}px`;
    targetEl.appendChild(marker);

    return { marker, prevPosition };
}

async function _captureViaDom(clickX, clickY) {
    await loadJS("/web_editor/static/lib/html2canvas.js");
    const targetEl = document.querySelector(".o_action_manager") || document.body;

    // Inject a visible marker at the click point inside the capture target
    let cleanup = null;
    if (clickX != null && clickY != null) {
        const { marker, prevPosition } = _injectClickMarker(targetEl, clickX, clickY);
        cleanup = () => {
            marker.remove();
            targetEl.style.position = prevPosition;
        };
    }

    try {
        const canvas = await window.html2canvas(targetEl, {
            logging: false,
            useCORS: true,
            scale: 1,
            ignoreElements: (el) =>
                el.classList &&
                (el.classList.contains("jito_qr_context_menu") ||
                 el.classList.contains("o_dialog")),
        });
        return canvas.toDataURL("image/png").split(",")[1];
    } finally {
        if (cleanup) {
            cleanup();
        }
    }
}

async function captureScreenshot(strategy, clickX, clickY) {
    if (strategy === "none") {
        return false;
    }

    if (strategy === "screen_capture") {
        try {
            return await _captureViaScreenAPI();
        } catch {
            return false;
        }
    }

    if (strategy === "dom_capture") {
        try {
            return await _captureViaDom(clickX, clickY);
        } catch {
            return false;
        }
    }

    // Default: "auto" — try screen capture, fallback to DOM
    try {
        return await _captureViaScreenAPI();
    } catch {
        // fall through
    }
    try {
        return await _captureViaDom(clickX, clickY);
    } catch {
        // fall through
    }
    return false;
}

// ---------------------------------------------------------------------------
// HTML description builder
// ---------------------------------------------------------------------------

function _escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text || "";
    return div.innerHTML;
}

function buildDescriptionHtml(userText, ctx) {
    let html = "";

    // User report
    if (userText) {
        html += `<p>${_escapeHtml(userText)}</p>`;
    }
    html += "<hr/>";

    // Page context
    html += "<h3>Page Context</h3><ul>";
    html += `<li><strong>URL:</strong> ${_escapeHtml(ctx.url)}</li>`;
    html += `<li><strong>Breadcrumb:</strong> ${_escapeHtml(ctx.breadcrumb)}</li>`;
    if (ctx.model) {
        html += `<li><strong>Model:</strong> ${_escapeHtml(ctx.model)}`;
        if (ctx.resId) {
            html += ` (ID: ${ctx.resId})`;
        }
        html += "</li>";
    }
    if (ctx.viewType) {
        html += `<li><strong>View Type:</strong> ${_escapeHtml(ctx.viewType)}</li>`;
    }
    html += "</ul>";

    // Clicked element
    html += "<h3>Clicked Element</h3><ul>";
    html += `<li><strong>Tag:</strong> ${_escapeHtml(ctx.element.tag)}</li>`;
    if (ctx.element.fieldName) {
        html += `<li><strong>Field Name:</strong> ${_escapeHtml(ctx.element.fieldName)}</li>`;
    }
    if (ctx.element.fieldLabel) {
        html += `<li><strong>Field Label:</strong> ${_escapeHtml(ctx.element.fieldLabel)}</li>`;
    }
    if (ctx.element.fieldValue) {
        html += `<li><strong>Field Value:</strong> ${_escapeHtml(ctx.element.fieldValue)}</li>`;
    }
    if (ctx.element.text) {
        html += `<li><strong>Text:</strong> ${_escapeHtml(ctx.element.text)}</li>`;
    }
    if (ctx.element.className) {
        html += `<li><strong>CSS Classes:</strong> <code>${_escapeHtml(ctx.element.className)}</code></li>`;
    }
    html += "</ul>";

    // Browser environment
    html += "<h3>Environment</h3><ul>";
    html += `<li><strong>Browser:</strong> ${_escapeHtml(ctx.userAgent)}</li>`;
    html += `<li><strong>Screen:</strong> ${ctx.screenWidth}x${ctx.screenHeight}</li>`;
    html += `<li><strong>Window:</strong> ${ctx.windowWidth}x${ctx.windowHeight}</li>`;
    html += `<li><strong>Reported by:</strong> ${_escapeHtml(ctx.userName)} (${_escapeHtml(ctx.userLogin)})</li>`;
    html += `<li><strong>Timestamp:</strong> ${_escapeHtml(ctx.timestamp)}</li>`;
    html += "</ul>";

    // Console errors
    if (ctx.consoleErrors.length > 0) {
        html += `<h3>Console Errors (${ctx.consoleErrors.length})</h3>`;
        const lines = ctx.consoleErrors.map(
            (e) => `[${e.time}] ${e.level}: ${e.message}`
        );
        html += `<pre>${_escapeHtml(lines.join("\n"))}</pre>`;
    }

    return html;
}

// ---------------------------------------------------------------------------
// Context menu DOM
// ---------------------------------------------------------------------------

let _activeMenu = null;
let _clickAwayHandler = null;

function removeContextMenu() {
    if (_activeMenu) {
        _activeMenu.remove();
        _activeMenu = null;
    }
    if (_clickAwayHandler) {
        document.removeEventListener("click", _clickAwayHandler, true);
        document.removeEventListener("contextmenu", _clickAwayHandler, true);
        document.removeEventListener("keydown", _escHandler, true);
        _clickAwayHandler = null;
    }
}

function _escHandler(ev) {
    if (ev.key === "Escape") {
        removeContextMenu();
    }
}

function showContextMenu(x, y, context, onReport) {
    removeContextMenu();

    const menu = document.createElement("div");
    menu.className = "jito_qr_context_menu";

    // Keep menu within viewport
    menu.style.left = `${Math.min(x, window.innerWidth - 200)}px`;
    menu.style.top = `${Math.min(y, window.innerHeight - 50)}px`;

    const item = document.createElement("div");
    item.className = "jito_qr_menu_item";
    item.innerHTML = '<i class="fa fa-bug me-2"></i>Report Issue';
    item.addEventListener("click", (ev) => {
        ev.stopPropagation();
        removeContextMenu();
        onReport(context);
    });

    menu.appendChild(item);
    document.body.appendChild(menu);
    _activeMenu = menu;

    // Dismiss on click-away or Escape
    _clickAwayHandler = (ev) => {
        if (!menu.contains(ev.target)) {
            removeContextMenu();
        }
    };
    // Use setTimeout so the current event doesn't immediately dismiss
    setTimeout(() => {
        document.addEventListener("click", _clickAwayHandler, true);
        document.addEventListener("contextmenu", _clickAwayHandler, true);
        document.addEventListener("keydown", _escHandler, true);
    }, 0);
}

// ---------------------------------------------------------------------------
// Service definition
// ---------------------------------------------------------------------------

export const quickReportService = {
    dependencies: ["dialog", "notification", "rpc"],

    start(env, { dialog, notification, rpc }) {
        // Cache the screenshot strategy; refreshed on each report
        let _cachedStrategy = null;

        async function getScreenshotStrategy() {
            try {
                const result = await rpc("/jito_helpdesk_quick_report/get_settings");
                _cachedStrategy = result.screenshot_strategy || "dom_capture";
            } catch {
                _cachedStrategy = "dom_capture";
            }
            return _cachedStrategy;
        }

        // Register global error listeners
        window.addEventListener("error", (ev) => {
            _pushError("error", [
                `${ev.message} (${ev.filename}:${ev.lineno}:${ev.colno})`,
            ]);
        });
        window.addEventListener("unhandledrejection", (ev) => {
            _pushError("error", [`Unhandled rejection: ${ev.reason}`]);
        });

        async function openReportDialog(context) {
            // Fetch current strategy setting, then capture screenshot
            // BEFORE opening the dialog so the dialog doesn't appear in it.
            const strategy = await getScreenshotStrategy();
            const screenshot = await captureScreenshot(strategy, context.clickX, context.clickY);

            dialog.add(QuickReportDialog, {
                defaultTitle: `Issue on ${context.breadcrumb || "page"}`,
                onSubmit: async ({ title, description }) => {
                    const html = buildDescriptionHtml(description, context);
                    const result = await rpc(
                        "/jito_helpdesk_quick_report/create_ticket",
                        {
                            name: title,
                            description: html,
                            screenshot_base64: screenshot,
                            priority: "1",
                        }
                    );
                    if (result.error) {
                        notification.add(result.error, {
                            type: "danger",
                            sticky: true,
                        });
                        return;
                    }
                    if (result.ticket_id) {
                        notification.add(
                            `Ticket ${result.ticket_ref} created successfully`,
                            { type: "success" }
                        );
                        window.open(
                            `/web#model=helpdesk.ticket&id=${result.ticket_id}&view_type=form`,
                            "_blank"
                        );
                    }
                },
            });
        }

        // Global context menu listener
        whenReady(() => {
            document.addEventListener("contextmenu", (event) => {
                if (!event.shiftKey) {
                    return; // Allow native context menu
                }
                event.preventDefault();
                event.stopPropagation();

                const context = captureContext(event, env);
                showContextMenu(
                    event.clientX,
                    event.clientY,
                    context,
                    openReportDialog
                );
            });
        });
    },
};

registry.category("services").add("quick_report", quickReportService);
