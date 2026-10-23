/* ==========================================================
   Тактильный отклик кнопок — Летучка
   Сам находит кнопки по селекторам, ставит им классы и ведёт
   состояние нажатия. Обработчики оплаты не трогает: слушает
   события на document и ничего не добавляет внутрь кнопок.
   ========================================================== */
(function () {
    'use strict';

    // Что продавливается. Чтобы добавить любую другую кнопку, поставьте ей атрибут data-tactile
    var PRESS = '[data-tactile], #payment-button, .to-pay, .opt, .mode, .dock-btn, .dock-mobile a';
    // У кого есть волна
    var RIPPLE = '#payment-button, .to-pay, .dock-btn--primary, .dock-mobile .dock-plus';
    // Короткая вибрация при нажатии (работает на Android; на iPhone браузер её не поддерживает)
    var HAPTIC = '#payment-button, .to-pay, .opt, .mode';

    var MIN_PRESS = 110; // мс: даже очень короткий тап успевает «продавиться»
    var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function prep(el) {
        if (el.__tactile) return;
        el.__tactile = true;
        el.classList.add('tactile');
        if (el.matches(RIPPLE)) el.classList.add('tactile--ripple');
    }
    function prepAll() { document.querySelectorAll(PRESS).forEach(prep); }

    function isDisabled(el) {
        return el.disabled || el.getAttribute('aria-disabled') === 'true';
    }

    function ripple(el, x, y) {
        if (reduce || !el.classList.contains('tactile--ripple')) return;
        var r = el.getBoundingClientRect();
        var px = x == null ? r.width / 2 : x - r.left;
        var py = y == null ? r.height / 2 : y - r.top;
        var dx = Math.max(px, r.width - px), dy = Math.max(py, r.height - py);
        el.style.setProperty('--rx', px + 'px');
        el.style.setProperty('--ry', py + 'px');
        el.style.setProperty('--rs', (Math.sqrt(dx * dx + dy * dy) * 2) + 'px');
        el.classList.remove('is-rippling');
        void el.offsetWidth; // перезапуск анимации при быстрых повторных нажатиях
        el.classList.add('is-rippling');
    }

    var active = null, pressedAt = 0;

    function press(el, x, y) {
        if (isDisabled(el)) return;
        prep(el);
        if (active && active !== el) active.classList.remove('is-pressed');
        active = el;
        pressedAt = performance.now();
        el.classList.add('is-pressed');
        ripple(el, x, y);
    }
    function release() {
        if (!active) return;
        var el = active;
        active = null;
        var wait = Math.max(0, MIN_PRESS - (performance.now() - pressedAt));
        setTimeout(function () { el.classList.remove('is-pressed'); }, wait);
    }

    // Мышь, палец, стилус
    document.addEventListener('pointerdown', function (e) {
        if (e.pointerType === 'mouse' && e.button !== 0) return;
        var el = e.target.closest && e.target.closest(PRESS);
        if (el) press(el, e.clientX, e.clientY);
    }, { passive: true });
    document.addEventListener('pointerup', release, { passive: true });
    document.addEventListener('pointercancel', release, { passive: true }); // палец ушёл в прокрутку
    window.addEventListener('blur', release);

    // Клавиатура: Enter и пробел дают тот же отклик
    document.addEventListener('keydown', function (e) {
        if (e.repeat || (e.key !== 'Enter' && e.key !== ' ')) return;
        var el = e.target.closest && e.target.closest(PRESS);
        if (el) press(el);
    });
    document.addEventListener('keyup', function (e) {
        if (e.key === 'Enter' || e.key === ' ') release();
    });

    // Вибрация: браузер разрешает её только по клику, поэтому вешаем на click
    document.addEventListener('click', function (e) {
        if (!navigator.vibrate) return;
        var el = e.target.closest && e.target.closest(HAPTIC);
        if (el && !isDisabled(el)) { try { navigator.vibrate(8); } catch (err) {} }
    }, { passive: true });

    // Волна сама снимает свой класс, чтобы следующая запустилась чисто
    document.addEventListener('animationend', function (e) {
        if (e.animationName === 'tactile-ripple' && e.target.classList) e.target.classList.remove('is-rippling');
    });

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', prepAll);
    else prepAll();
})();