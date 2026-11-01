/* Letychka · site-chrome.js — остров: компакт, мобильное меню, прогресс чтения, «наверх». */
(function () {
    'use strict';
    var nav = document.getElementById('island-nav');
    if (!nav) return;
    var burger = document.getElementById('burger-btn');
    var menu = document.getElementById('island-menu');
    var scrim = document.getElementById('island-scrim');
    var progress = document.getElementById('island-progress');
    var toTop = document.getElementById('to-top');
    var target = document.querySelector('[data-progress-target]');
    var desktop = window.matchMedia('(min-width: 1024px)');

    var compact = false;
    function navState() {
        var y = window.scrollY;
        var next = compact ? y > 32 : y > 80;
        if (next !== compact) { compact = next; nav.classList.toggle('is-compact', compact); }
        if (target && progress) {
            var r = target.getBoundingClientRect();
            var top = r.top + y - 120;
            var end = r.top + y + r.height - window.innerHeight;
            var p = end > top ? (y - top) / (end - top) : 1;
            progress.style.transform = 'scaleX(' + Math.min(1, Math.max(0, p)).toFixed(4) + ')';
        }
        if (toTop) toTop.classList.toggle('is-on', y > 700);
    }

    var menuOpen = false;
    function setMenu(open) {
        if (open === menuOpen) return;
        menuOpen = open;
        nav.classList.toggle('is-open', open);
        scrim.classList.toggle('is-on', open);
        document.documentElement.classList.toggle('isl-lock', open);
        burger.setAttribute('aria-expanded', String(open));
        burger.setAttribute('aria-label', open ? 'Закрыть меню' : 'Открыть меню');
        if (open) menu.removeAttribute('inert'); else menu.setAttribute('inert', '');
    }
    burger.addEventListener('click', function () { setMenu(!menuOpen); });
    scrim.addEventListener('click', function () { setMenu(false); });
    menu.addEventListener('click', function (e) { if (e.target.closest('a')) setMenu(false); });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && menuOpen) { setMenu(false); burger.focus(); }
    });
    var onDesktop = function () { if (desktop.matches) setMenu(false); };
    if (desktop.addEventListener) desktop.addEventListener('change', onDesktop);
    else desktop.addListener(onDesktop);

    var ticking = false;
    function onScroll() {
        if (ticking) return;
        ticking = true;
        requestAnimationFrame(function () { ticking = false; navState(); });
    }
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll, { passive: true });
    navState();
})();
