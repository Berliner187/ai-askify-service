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

   Что нового внутри:
     · остров морфится через ширину фонового слоя .ls-isl-bg, а не через раскладку шапки;
     · ширина уведомления = ширине текста, смена уведомления без закрытия острова;
     · кольцо-таймер вокруг иконки; на наведении мыши показ ставится на паузу;
     · error — короткое покачивание.
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

    var SIZE = { sm: 380, md: 460, lg: 560 };
    var NOTE_MIN = 200, NOTE_MAX = 440;
    var reduce = !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);
    var canHover = !!(window.matchMedia && matchMedia('(hover: hover)').matches);

    var island, bg, note, textEl, iconBox, measure;
    var timer = null, deadline = 0, remaining = 0, hovering = false, noteSeq = 0, shakeT = null, clickFn = null;
    var layers = {}, pendingLayers = [], activeName = null, activeOpts = null, layerTimer = null;

    function setWidth(px) {
        if (!island) return;
        if (px == null) island.style.removeProperty('--bw'); else island.style.setProperty('--bw', px + 'px');
    }
    function avail() { return island.clientWidth || 360; }
    function noteWidth(text) {
        measure.textContent = text;
        var w = Math.ceil(measure.getBoundingClientRect().width) + 24 + 10 + 36 + 6;
        return Math.round(Math.min(Math.max(w, NOTE_MIN), NOTE_MAX, avail()));
    }
    function layerWidth(size) { return Math.round(Math.min(SIZE[size] || SIZE.md, avail())); }

    function init() {
        island = $('dynamic-island');
        if (!island) return;
        var wrap = $('ls-island-wrap');

        bg = island.querySelector('.ls-isl-bg');
        if (!bg) { bg = document.createElement('span'); bg.className = 'ls-isl-bg'; bg.setAttribute('aria-hidden', 'true'); island.insertBefore(bg, island.firstChild); }
        note = $('island-notice'); textEl = $('island-text'); iconBox = $('island-icon-box');
        measure = document.createElement('span'); measure.className = 'ls-isl-measure'; measure.setAttribute('aria-hidden', 'true');
        island.appendChild(measure);

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

        var rt = null;
        addEventListener('resize', function () {
            clearTimeout(rt);
            rt = setTimeout(function () {
                if (activeName) { var px = layerWidth(activeOpts && activeOpts.size); layers[activeName].style.setProperty('--lw', px + 'px'); setWidth(px); }
                else if (island.classList.contains('is-notify')) setWidth(noteWidth(textEl.textContent));
            }, 80);
        }, { passive: true });

        document.querySelectorAll('template[data-ls-slot]').forEach(function (t) {
            var slot = t.dataset.lsSlot, host = island.querySelector('[data-ls-slot-host="' + slot + '"]');
            if (!host) return;
            if (slot === 'title') host.innerHTML = '';
            host.appendChild(t.content.cloneNode(true));
        });

        island.addEventListener('click', function () { if (clickFn && island.classList.contains('is-notify')) clickFn(); });

        if (canHover) {
            island.addEventListener('mouseenter', function () {
                hovering = true;
                if (island.classList.contains('is-notify') && timer) { clearTimeout(timer); timer = null; remaining = Math.max(0, deadline - Date.now()); }
            });
            island.addEventListener('mouseleave', function () {
                hovering = false;
                if (island.classList.contains('is-notify') && !timer) { remaining = Math.max(remaining, 700); deadline = Date.now() + remaining; timer = setTimeout(dismiss, remaining); }
            });
        }
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
        clearTimeout(timer); timer = null; clearTimeout(layerTimer); noteSeq++;
        note.classList.remove('is-swap');
        island.classList.remove('is-notify', 'is-clickable'); clickFn = null;
        if (activeName && layers[activeName] && activeName !== name) layers[activeName].classList.remove('on');
        activeName = name; activeOpts = opts;
        var px = layerWidth(opts.size || 'md');
        el.style.setProperty('--lw', px + 'px');
        setWidth(px);
        island.setAttribute('data-size', opts.size || 'md');
        island.setAttribute('data-type', opts.tone || 'info');
        island.classList.add('is-layer');
        el.classList.add('on');
        if (opts.duration) layerTimer = setTimeout(function () { hide(name); }, opts.duration);
    }
    function closeLayer(keepWidth) {
        if (!activeName) return;
        clearTimeout(layerTimer);
        layers[activeName].classList.remove('on');
        activeName = null; activeOpts = null;
        island.classList.remove('is-layer');
        island.removeAttribute('data-size');
        if (!keepWidth) setWidth(null);
    }
    function hide(name) {
        if (!island || !activeName) return;
        if (name && name !== activeName) return;
        closeLayer(false);
    }

    /* ---------- Уведомления ---------- */
    function startTimer(ms) {
        clearTimeout(timer); timer = null;
        remaining = ms; deadline = Date.now() + ms;
        if (!hovering) timer = setTimeout(dismiss, ms);
    }
    function shake() {
        if (reduce) return;
        clearTimeout(shakeT);
        island.classList.remove('is-shake'); void island.offsetWidth; island.classList.add('is-shake');
        shakeT = setTimeout(function () { island.classList.remove('is-shake'); }, 480);
    }
    function notify(message, type, icon, duration) {
        if (!island || !message) return;
        type = type === 'warn' ? 'warning' : (type || 'success');
        if (activeOpts && activeOpts.lock) { if (window.console) console.warn('[Island]', message); return; }
        if (activeName) closeLayer(true);

        var dur = duration || 2600, ico = iconId(icon, type), seq = ++noteSeq;
        var live = island.classList.contains('is-notify');
        clearTimeout(timer); timer = null; clickFn = null; island.classList.remove('is-clickable');

        function apply() {
            if (seq !== noteSeq) return;
            textEl.textContent = message;
            iconBox.innerHTML = '<svg class="ls-icon"><use href="#ls-i-' + ico + '"/></svg>' +
                '<svg class="ls-isl-ring" viewBox="0 0 34 34" style="--dur:' + dur + 'ms" aria-hidden="true">' +
                '<circle class="trk" cx="17" cy="17" r="15.25"/><circle class="run" cx="17" cy="17" r="15.25" pathLength="100"/></svg>';
            note.classList.remove('is-swap');
            startTimer(dur);
        }

        island.setAttribute('data-type', type);
        setWidth(noteWidth(message));
        island.classList.add('is-notify');
        if (live && !reduce) { note.classList.add('is-swap'); setTimeout(apply, 110); } else apply();
        if (type === 'error') shake();
    }
    function dismiss() {
        if (!island) return;
        clearTimeout(timer); timer = null; noteSeq++;
        note.classList.remove('is-swap');
        island.classList.remove('is-notify', 'is-clickable');
        clickFn = null;
        if (!activeName) setWidth(null);
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