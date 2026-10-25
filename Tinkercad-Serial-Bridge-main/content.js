
'use strict';

/**
 * content.js — Tinkercad Serial Bridge
 *
 * Responsibilities:
 * 1. Read new Serial Monitor lines and forward them to background.js.
 * 2. Retrieve dashboard commands and submit them through the Serial Monitor.
 * 3. Maintain heartbeat and receive configuration updates.
 *
 * Existing telemetry format and Firebase bridge endpoints are preserved.
 */

const HEARTBEAT_MS = 2000;
const MUTATION_DEBOUNCE = 120;
const MAX_TRACKED_LINES = 400;

let cfg = {
    enabled: true,
    baseUrl: 'http://localhost:8080',
    uploadInterval: 800,
    cmdInterval: 2000,
    lineFilter: '',
    monitorSelector: '',
    inputSelector: '',
    sendSelector: ''
};

let lastLines = [];
let monitorEl = null;
let uploadTimer = null;
let cmdTimer = null;
let heartbeatTimer = null;
let debounceTimer = null;
let pushBusy = false;
let cmdBusy = false;
let lastInputEl = null;
let lastDeliveredCmd = '';

/* ------------------------- Document and element discovery */

function* documents() {
    yield document;

    for (const frame of document.querySelectorAll('iframe')) {
        try {
            if (frame.contentDocument) {
                yield frame.contentDocument;
            }
        } catch (e) {
            // Ignore cross-origin frames.
        }
    }
}

function deepQuery(selector) {
    if (!selector) return null;

    for (const doc of documents()) {
        try {
            const el = doc.querySelector(selector);
            if (el) return el;
        } catch (e) {
            // Ignore invalid selectors.
        }
    }

    return null;
}

const MONITOR_SELECTORS = [
    '[class*="serial-monitor"]',
    '[class*="SerialMonitor"]',
    '[class*="serial_monitor"]',
    '[class*="serialMonitor"]',
    '[data-testid*="serial-monitor"]',
    '[class*="monitor"]'
];

const INPUT_SELECTORS = [
    'input[class*="code_panel__serial__input"]',
    'input[class*="serial__input"]',
    'input[class*="serial-input"]',
    'input[class*="SerialInput"]'
];

const SEND_SELECTORS = [
    'a[data-event="serial-send"]',
    'button[data-event="serial-send"]',
    '[data-event="serial-send"]',
    'button[class*="serial__send"]',
    'button[class*="serial-send"]'
];

function pickFrom(list, custom) {
    if (custom) {
        const el = deepQuery(custom);
        if (el) return el;
    }

    for (const selector of list) {
        const el = deepQuery(selector);
        if (el) return el;
    }

    return null;
}

function guessSerialInput() {
    for (const doc of documents()) {
        const inputs = doc.querySelectorAll('input');

        for (const input of inputs) {
            if (input.type && input.type !== 'text') continue;
            if (input.disabled || input.readOnly) continue;

            const hint =
                (input.className || '') + ' ' +
                (input.placeholder || '') + ' ' +
                (input.getAttribute('aria-label') || '');

            if (/serial/i.test(hint)) return input;
        }
    }

    return null;
}

function findMonitor() {
    if (monitorEl && monitorEl.isConnected) {
        return monitorEl;
    }

    monitorEl = pickFrom(MONITOR_SELECTORS, cfg.monitorSelector);
    return monitorEl;
}

function findSerialInput() {
    const input =
        pickFrom(INPUT_SELECTORS, cfg.inputSelector) ||
        guessSerialInput();

    if (input) lastInputEl = input;

    return input;
}

/**
 * Prefer the Send button in the same document as the selected input.
 * This avoids clicking an unrelated button in another document.
 */
function findSendButton(input = null) {
    const doc = input?.ownerDocument || document;

    if (cfg.sendSelector) {
        try {
            const customButton = doc.querySelector(cfg.sendSelector);

            if (customButton && !customButton.disabled) {
                return customButton;
            }
        } catch (e) {
            console.warn(
                '[Solar Bridge] Invalid Send selector:',
                e
            );
        }
    }

    for (const selector of SEND_SELECTORS) {
        try {
            const buttons = doc.querySelectorAll(selector);

            for (const button of buttons) {
                if (!button.disabled && button.isConnected) {
                    return button;
                }
            }
        } catch (e) {
            console.warn(
                '[Solar Bridge] Send selector error:',
                selector,
                e
            );
        }
    }

    return null;
}

/* ------------------------- Serial Monitor telemetry */

function readLines(el) {
    const text = el.innerText || el.textContent || '';

    return text
        .split(/\r?\n/)
        .map(line => line.replace(/\s+$/, ''))
        .filter(line => line.length > 0);
}

function diffNewLines(prev, cur) {
    if (!prev.length) return cur;
    if (!cur.length) return [];

    const max = Math.min(prev.length, cur.length);

    for (let k = max; k > 0; k--) {
        let matched = true;

        for (let i = 0; i < k; i++) {
            if (prev[prev.length - k + i] !== cur[i]) {
                matched = false;
                break;
            }
        }

        if (matched) return cur.slice(k);
    }

    return cur;
}

function applyFilter(lines) {
    const filter = cfg.lineFilter;

    if (!filter) return lines;

    return lines.filter(line => line.includes(filter));
}

/* ------------------------- Background communication */

const BG_FAIL_THRESHOLD = 3;
const REQUEST_TIMEOUT = 5000;

let bgFailCount = 0;

function withTimeout(promise, ms) {
    return Promise.race([
        promise,
        new Promise((_, reject) => {
            setTimeout(
                () => reject(new Error('timeout')),
                ms
            );
        })
    ]);
}

async function askBackground(msg) {
    try {
        const res = await withTimeout(
            chrome.runtime.sendMessage(msg),
            REQUEST_TIMEOUT
        );

        bgFailCount = 0;
        return res;
    } catch (e) {
        bgFailCount++;
        console.warn(
            '[Solar Bridge] Background communication failed:',
            e.message
        );
        return null;
    }
}

function useDirect() {
    return bgFailCount >= BG_FAIL_THRESHOLD;
}

/* ------------------------- Telemetry upload */

async function pushLinesDirect(lines) {
    for (const line of lines) {
        try {
            const res = await fetch(
                `${cfg.baseUrl}/send?out=${encodeURIComponent(line)}`,
                {
                    method: 'GET',
                    signal: AbortSignal.timeout(REQUEST_TIMEOUT)
                }
            );

            if (!res.ok) {
                throw new Error('HTTP ' + res.status);
            }
        } catch (e) {
            console.error(
                '[Solar Bridge] Telemetry upload failed:',
                e
            );
            break;
        }
    }
}

/**
 * In direct mode, update background statistics without falsely
 * reporting a dashboard command as delivered.
 */
function reportToBackground(cmd, lines) {
    if (!useDirect()) return;

    askBackground({
        type: 'bridge:report',
        cmd: cmd || '',
        lines: lines || []
    });
}

async function pushLines(lines) {
    if (pushBusy || !lines.length) return;

    pushBusy = true;

    try {
        if (useDirect()) {
            await pushLinesDirect(lines);
            reportToBackground('', lines);
        } else {
            const res = await askBackground({
                type: 'bridge:push',
                lines
            });

            if (!res) {
                await pushLinesDirect(lines);
                reportToBackground('', lines);
            }
        }
    } finally {
        pushBusy = false;
    }
}

function uploadTick() {
    if (!cfg.enabled) return;

    const monitor = findMonitor();
    if (!monitor) return;

    const current = readLines(monitor);

    if (!current.length) {
        lastLines = [];
        return;
    }

    let fresh = diffNewLines(lastLines, current);

    lastLines = current.slice(-MAX_TRACKED_LINES);

    if (!fresh.length) return;

    if (fresh.length > 200) {
        fresh = fresh.slice(-200);
    }

    fresh = applyFilter(fresh);

    if (!fresh.length) return;

    pushLines(fresh);
}

/* ------------------------- Command delivery */

function setNativeValue(el, value) {
    const prototype = el instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype;

    const descriptor =
        Object.getOwnPropertyDescriptor(prototype, 'value');

    if (descriptor && descriptor.set) {
        descriptor.set.call(el, value);
    } else {
        el.value = value;
    }
}

const SEND_SETTLE_MS = 300;

function writeSerialInput(input, cmd) {
    if (!input || !input.isConnected) return false;
    if (input.disabled || input.readOnly) return false;

    try {
        setNativeValue(input, cmd);

        input.dispatchEvent(
            new Event('input', { bubbles: true })
        );

        input.dispatchEvent(
            new Event('change', { bubbles: true })
        );

        input.focus();

        console.log(
            '[Solar Bridge] Command placed in input:',
            cmd,
            'Current value:',
            input.value
        );

        return true;
    } catch (e) {
        console.error(
            '[Solar Bridge] Failed to write input:',
            e
        );

        return false;
    }
}

function clickSend(input) {
    if (!input || !input.isConnected) {
        console.error(
            '[Solar Bridge] Serial input is disconnected.'
        );

        return false;
    }

    const button = findSendButton(input);

    if (button) {
        if (button.disabled) {
            console.error(
                '[Solar Bridge] Send button is disabled.'
            );

            return false;
        }

        try {
            button.click();

            console.log(
                '[Solar Bridge] Send button clicked.'
            );

            return true;
        } catch (e) {
            console.error(
                '[Solar Bridge] Send button click failed:',
                e
            );

            return false;
        }
    }

    console.error(
        '[Solar Bridge] Send button not found in input document.'
    );

    return false;
}

/**
 * Schedules a command submission.
 *
 * The return value means the submission was scheduled.
 * It does NOT mean Arduino received the command.
 */
function deliverCommand(cmd) {
    const input = findSerialInput();

    if (!input) {
        console.error(
            '[Solar Bridge] Serial input not found:',
            cmd
        );

        return false;
    }

    if (!writeSerialInput(input, cmd)) {
        console.error(
            '[Solar Bridge] Could not write command:',
            cmd
        );

        return false;
    }

    setTimeout(() => {
        const currentInput = input.isConnected
            ? input
            : findSerialInput();

        if (!currentInput) {
            console.error(
                '[Solar Bridge] Input disappeared before send:',
                cmd
            );

            return;
        }

        // React may replace or clear the input during rendering.
        if (currentInput.value !== cmd) {
            if (!writeSerialInput(currentInput, cmd)) {
                console.error(
                    '[Solar Bridge] Could not restore command:',
                    cmd
                );

                return;
            }
        }

        setTimeout(() => {
            const latestInput = currentInput.isConnected
                ? currentInput
                : findSerialInput();

            if (!latestInput) {
                console.error(
                    '[Solar Bridge] Input lost before click:',
                    cmd
                );

                return;
            }

            if (latestInput.value !== cmd) {
                if (!writeSerialInput(latestInput, cmd)) {
                    console.error(
                        '[Solar Bridge] Final input write failed:',
                        cmd
                    );

                    return;
                }
            }

            const clicked = clickSend(latestInput);

            if (clicked) {
                lastDeliveredCmd = cmd;

                console.log(
                    '[Solar Bridge] Send clicked; awaiting Arduino ACK:',
                    cmd
                );
            }
        }, SEND_SETTLE_MS);
    }, SEND_SETTLE_MS);

    return true;
}

async function fetchCmdDirect() {
    const res = await fetch(`${cfg.baseUrl}/cmd`, {
        method: 'GET',
        signal: AbortSignal.timeout(REQUEST_TIMEOUT)
    });

    if (!res.ok) {
        throw new Error('HTTP ' + res.status);
    }

    return (await res.text()).trim();
}

async function cmdTick() {
    if (!cfg.enabled || cmdBusy) return;

    cmdBusy = true;

    try {
        let cmd = '';

        if (useDirect()) {
            cmd = await fetchCmdDirect().catch(error => {
                console.error(
                    '[Solar Bridge] Direct command fetch failed:',
                    error
                );

                return '';
            });
        } else {
            const res = await askBackground({
                type: 'bridge:pollCmd'
            });

            if (res) {
                // Respect leader-tab decisions from background.js.
                if (res.skipped) return;

                cmd = res.cmd
                    ? String(res.cmd).trim()
                    : '';
            } else {
                cmd = await fetchCmdDirect().catch(error => {
                    console.error(
                        '[Solar Bridge] Fallback command fetch failed:',
                        error
                    );

                    return '';
                });
            }
        }

        if (!cmd) return;

        console.log(
            '[Solar Bridge] Command received from bridge:',
            cmd
        );

        const scheduled = deliverCommand(cmd);

        if (!scheduled) {
            console.error(
                '[Solar Bridge] Command could not be scheduled:',
                cmd
            );
        }
    } finally {
        cmdBusy = false;
    }
}

/* ------------------------- Heartbeat and configuration */

async function heartbeat() {
    const res = await askBackground({
        type: 'bridge:hello',
        visible: document.visibilityState === 'visible'
    });

    if (res && res.cfg) {
        applyConfig(res.cfg);
    }
}

function applyConfig(next) {
    if (!next) return;

    const intervalChanged =
        next.uploadInterval !== cfg.uploadInterval ||
        next.cmdInterval !== cfg.cmdInterval;

    cfg = Object.assign({}, cfg, next);

    monitorEl = null;

    if (intervalChanged) {
        restartTimers();
    }
}

/* ------------------------- Timer management */

function clearTimer(timer) {
    if (timer) clearInterval(timer);
    return null;
}

function restartTimers() {
    uploadTimer = clearTimer(uploadTimer);
    cmdTimer = clearTimer(cmdTimer);

    uploadTimer = setInterval(
        uploadTick,
        Math.max(100, cfg.uploadInterval)
    );

    cmdTimer = setInterval(
        cmdTick,
        Math.max(100, cfg.cmdInterval)
    );
}

function scheduleDebouncedUpload() {
    if (debounceTimer) {
        clearTimeout(debounceTimer);
    }

    debounceTimer = setTimeout(() => {
        debounceTimer = null;
        uploadTick();
    }, MUTATION_DEBOUNCE);
}

/* ------------------------- Extension message listener */

chrome.runtime.onMessage.addListener(
    (msg, sender, sendResponse) => {
        if (!msg || !msg.type) return;

        if (msg.type === 'bridge:config') {
            applyConfig(msg.cfg);
            sendResponse({ ok: true });
        } else if (msg.type === 'bridge:diag') {
            const input = findSerialInput();

            sendResponse({
                ok: true,
                url: location.href,
                hasMonitor: Boolean(findMonitor()),
                hasInput: Boolean(input),
                hasSendButton: Boolean(findSendButton(input)),
                lastLines: lastLines.slice(-5),
                lastDeliveredCmd,
                transport: useDirect()
                    ? 'direct'
                    : 'background',
                bgFailCount
            });
        }

        return false;
    }
);

/* ------------------------- Startup */

(async function init() {
    const res = await askBackground({
        type: 'bridge:hello',
        visible: document.visibilityState === 'visible'
    });

    if (res && res.cfg) {
        cfg = Object.assign({}, cfg, res.cfg);
    }

    restartTimers();

    heartbeatTimer = setInterval(
        heartbeat,
        HEARTBEAT_MS
    );

    const observer = new MutationObserver(() => {
        if (!cfg.enabled) return;
        if (!findMonitor()) return;

        scheduleDebouncedUpload();
    });

    observer.observe(document.body, {
        childList: true,
        subtree: true,
        characterData: true
    });

    document.addEventListener(
        'visibilitychange',
        heartbeat
    );

    window.addEventListener('beforeunload', () => {
        observer.disconnect();

        if (heartbeatTimer) {
            clearInterval(heartbeatTimer);
        }

        if (debounceTimer) {
            clearTimeout(debounceTimer);
        }

        clearTimer(uploadTimer);
        clearTimer(cmdTimer);
    });

    console.log('[Solar Bridge] Content script initialized.');
})();
