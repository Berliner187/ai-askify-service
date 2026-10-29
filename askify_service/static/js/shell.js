/* ==========================================================================
   Letychka · shell.js — остров, модалка выхода, слоты. Без зависимостей.
   API (совместим с прежним Island из demo-view):
     Island.notify(msg, type = 'success', icon = null, duration = 2600)
     Island.success / error / warn / info (msg, icon, duration)
     Island.dismiss()
     Island.onClick(fn)   — сделать остров кликабельным на время уведомления
   Кастомные состояния страницы (запись голоса, распознавание…) — внутри ТОГО ЖЕ острова:
     Island.layer(name, el)                 — регистрирует элемент как слой (переносится в остров)
     Island.show(name, {size, tone, lock, duration}) — показать слой; size: sm|md|lg, tone: info|warning|success
                                              lock:true — пока слой открыт, notify() не перебивает его
     Island.hide(name?)                     — вернуть шапку; Island.active() — имя открытого слоя или null
   type: success | error | warning (warn) | info. Красного нет: error рисуется янтарём.
   icon: имя из спрайта ('link', 'check', 'eye'…) или FA-имя 'fa-link' — оно будет сопоставлено.
   ========================================================================== */
(function () {
    'use strict';
    if (window.Island && window.Island.__shell) return;

    var $ = function (id) { return document.getElementById(id); };
    var DEFAULT_ICON = { success: 'check', error: 'warn', warning: 'warn', info: 'spark' };
    var FA_MAP = {
        'check': 'check', 'xmark': 'x', 'exclamation': 'warn', 'triangle-exclamation': 'warn', 'bolt': 'spark',
        'link': 'link', 'eye': 'eye', 'eye-slash': 'eye', 'pen': 'pen', 'pen-to-square': 'pen', 'pen-slash': 'pen',
        'floppy-disk': 'check', 'wand-magic-sparkles': 'spark', 'qrcode': 'qr', 'rotate': 'rotate', 'rotate-left': 'rotate',
        'copy': 'copy', 'plus': 'plus', 'x': 'x', 'warn': 'warn', 'spark': 'spark', 'qr': 'qr',
        'lock': 'lock', 'file': 'file', 'file-lines': 'file', 'file-circle-exclamation': 'file', 'file-arrow-up': 'file',
        'microphone': 'mic', 'microphone-slash': 'mic', 'mic': 'mic', 'ban': 'x', 'shield-halved': 'shield', 'shield': 'shield',
        'circle-info': 'spark', 'user': 'user', 'crown': 'spark'
    };
    function iconId(icon, type) {
        if (icon) {
            var n = String(icon).split(/\s+/).filter(function (c) { return c.indexOf('fa-') === 0 && c !== 'fa-solid' && c !== 'fa-spin'; })[0] || String(icon);
            n = n.replace(/^fa-/, '');
            if (FA_MAP[n]) return FA_MAP[n];
        }
        return DEFAULT_ICON[type] || 'check';
    }

    var island, timer, clickFn = null;
    var layers = {}, pendingLayers = [], activeName = null, activeOpts = null, layerTimer = null;
    function init() {
        island = $('dynamic-island');
        if (!island) return;
        var wrap = $('ls-island-wrap');

        // прогресс скролла (включается атрибутом data-progress="1")
        var prog = $('ls-isl-progress'), ticking = false;
        function onScroll() {
            if (ticking) return; ticking = true;
            requestAnimationFrame(function () {
                var y = window.scrollY;
                wrap.classList.toggle('is-scrolled', y > 24);
                if (wrap.dataset.progress === '1' && prog) {
                    var max = document.documentElement.scrollHeight - innerHeight;
                    prog.style.transform = 'scaleX(' + (max > 0 ? Math.min(1, y / max) : 0).toFixed(4) + ')';
                }
                ticking = false;
            });
        }
        addEventListener('scroll', onScroll, { passive: true }); onScroll();

        // слоты: <template data-ls-slot="right|title"> — перенос произвольной разметки в остров
        document.querySelectorAll('template[data-ls-slot]').forEach(function (t) {
            var slot = t.dataset.lsSlot, host = island.querySelector('[data-ls-slot-host="' + slot + '"]');
            if (!host) return;
            if (slot === 'title') host.innerHTML = '';
            host.appendChild(t.content.cloneNode(true));
        });

        island.addEventListener('click', function () { if (clickFn && island.classList.contains('is-notify')) clickFn(); });
        pendingLayers.splice(0).forEach(function (a) { layer(a[0], a[1]); });
    }

    /* ---------- Слои ---------- */
    function layer(name, el) {
        if (typeof el === 'string') el = $(el);
        if (!el) return;
        if (!island) { pendingLayers.push([name, el]); return; }
        el.hidden = false;
        el.classList.add('ls-isl-layer');
        el.setAttribute('data-layer', name);
        island.appendChild(el);
        layers[name] = el;
    }
    function show(name, opts) {
        var el = layers[name];
        if (!island || !el) return;
        opts = opts || {};
        clearTimeout(timer); clearTimeout(layerTimer);
        island.classList.remove('is-notify', 'is-clickable'); clickFn = null;
        if (activeName && layers[activeName] && activeName !== name) layers[activeName].classList.remove('on');
        activeName = name; activeOpts = opts;
        island.setAttribute('data-size', opts.size || 'md');
        island.setAttribute('data-type', opts.tone || 'info');
        island.classList.add('is-layer');
        el.classList.add('on');
        if (opts.duration) layerTimer = setTimeout(function () { hide(name); }, opts.duration);
    }
    function hide(name) {
        if (!island || !activeName) return;
        if (name && name !== activeName) return;
        clearTimeout(layerTimer);
        layers[activeName].classList.remove('on');
        activeName = null; activeOpts = null;
        island.classList.remove('is-layer');
        island.removeAttribute('data-size');
    }

    function notify(message, type, icon, duration) {
        if (!island || !message) return;
        type = type === 'warn' ? 'warning' : (type || 'success');
        if (activeOpts && activeOpts.lock) { if (window.console) console.warn('[Island]', message); return; }
        if (activeName) hide();
        clearTimeout(timer);
        $('island-text').textContent = message;
        $('island-icon-box').innerHTML = '<svg class="ls-icon"><use href="#ls-i-' + iconId(icon, type) + '"/></svg>';
        island.setAttribute('data-type', type);
        island.classList.add('is-notify');
        timer = setTimeout(dismiss, duration || 2600);
    }
    function dismiss() {
        if (!island) return;
        clearTimeout(timer);
        island.classList.remove('is-notify', 'is-clickable');
        clickFn = null;
    }

    window.Island = {
        __shell: true,
        notify: notify,
        dismiss: dismiss,
        success: function (m, i, d) { notify(m, 'success', i, d); },
        error: function (m, i, d) { notify(m, 'error', i, d); },
        warn: function (m, i, d) { notify(m, 'warning', i, d); },
        info: function (m, i, d) { notify(m, 'info', i, d); },
        onClick: function (fn) { clickFn = fn; if (island) island.classList.add('is-clickable'); },
        layer: layer,
        show: show,
        hide: hide,
        active: function () { return activeName; }
    };

    /* ---------- Модалки: LSModal.open(id|el) / .close() ----------
       Разметка:  <div class="ls-modal [ls-modal--sheet]" id="x"><div class="ls-panel" role="dialog" aria-modal="true">…</div></div>
       Триггер:   <button data-ls-open="x">  ·  закрытие: [data-ls-close], клик по подложке, Esc.
       События:   document 'ls:modal-open' (detail: {modal, trigger}) — чтобы наполнить содержимое. */
    var current = null, lastFocus = null;
    function open(m, trigger) {
        if (typeof m === 'string') m = $(m);
        if (!m) return;
        if (current && current !== m) close(current, true);
        lastFocus = trigger || document.activeElement;
        current = m;
        document.dispatchEvent(new CustomEvent('ls:modal-open', { detail: { modal: m, trigger: trigger || null } }));
        m.classList.add('on'); m.setAttribute('aria-hidden', 'false');
        document.body.classList.add('ls-lock');
        var p = m.querySelector('.ls-panel'); p.setAttribute('tabindex', '-1');
        setTimeout(function () { var f = m.querySelector('[data-ls-focus]'); (f || p).focus({ preventScroll: true }); }, 50);
    }
    function close(m, silent) {
        m = m || current; if (!m || !m.classList.contains('on')) return;
        m.classList.remove('on'); m.setAttribute('aria-hidden', 'true');
        if (current === m) current = null;
        if (!silent) {
            document.body.classList.remove('ls-lock');
            if (lastFocus && lastFocus.focus) lastFocus.focus({ preventScroll: true });
        }
    }
    window.LSModal = { open: open, close: close };
    window.openLogoutModal = function () { open('ls-logout-modal'); };   // обратная совместимость
    window.closeLogoutModal = function () { close($('ls-logout-modal')); };

    function initModals() {
        document.addEventListener('click', function (e) {
            var lo = e.target.closest('[data-ls-logout]');
            if (lo && $('ls-logout-modal')) { e.preventDefault(); open('ls-logout-modal', lo); return; }
            var o = e.target.closest('[data-ls-open]');
            if (o) { e.preventDefault(); open(o.dataset.lsOpen, o); return; }
            var m = e.target.closest('.ls-modal');
            if (m && (e.target === m || e.target.closest('[data-ls-close]'))) close(m);
        });
        document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
    }

    function boot() { init(); initModals(); }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();