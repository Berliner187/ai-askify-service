/* Letychka · blog.js — журнал: фильтр/поиск; статья: оглавление, «Летучка по статье», ссылка, счётчик. */
(function () {
    'use strict';

    /* ======================= ЖУРНАЛ ======================= */
    var list = document.getElementById('bl-list');
    var bar = document.getElementById('bl-bar');
    if (list && bar) {
        var items = [].slice.call(document.querySelectorAll('[data-item]'));
        var chips = [].slice.call(bar.querySelectorAll('.chip'));
        var input = document.getElementById('bl-q');
        var empty = document.getElementById('bl-empty');
        var rubric = '';

        function norm(s) { return (s || '').toLowerCase().replace(/ё/g, 'е').trim(); }

        var card = document.querySelector('.bl-lead');
        var leadRow = document.querySelector('[data-lead]');

        function apply() {
            var q = norm(input.value), filtered = !!(rubric || q), visible = 0;
            items.forEach(function (el) {
                if (el === card) return;
                var okR = !rubric || el.getAttribute('data-rubric') === rubric;
                var okQ = !q || norm(el.getAttribute('data-search')).indexOf(q) !== -1;
                el.hidden = !(okR && okQ);
                if (!el.hidden) visible++;
            });
            // без фильтров главный материал живёт карточкой, с фильтром — строкой ведомости
            if (card && leadRow) {
                card.hidden = filtered;
                if (!filtered) leadRow.hidden = true;
            }
            empty.hidden = visible !== 0;
        }

        function setRubric(name, push) {
            rubric = name;
            chips.forEach(function (c) { c.setAttribute('aria-pressed', String(c.getAttribute('data-rubric') === name)); });
            if (push) {
                try { history.replaceState(null, '', name ? '#r=' + encodeURIComponent(name) : location.pathname + location.search); } catch (e) {}
            }
            apply();
        }

        chips.forEach(function (c) {
            c.addEventListener('click', function () { setRubric(c.getAttribute('data-rubric'), true); });
        });
        input.addEventListener('input', apply);
        document.getElementById('bl-reset').addEventListener('click', function () {
            input.value = ''; setRubric('', true); input.focus();
        });
        document.addEventListener('keydown', function (e) {
            var t = e.target, typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable);
            if (e.key === '/' && !typing && !e.metaKey && !e.ctrlKey) { e.preventDefault(); input.focus(); }
            if (e.key === 'Escape' && t === input) { input.value = ''; apply(); input.blur(); }
        });

        var m = /#r=([^&]+)/.exec(location.hash);
        if (m) {
            var want = decodeURIComponent(m[1]);
            if (chips.some(function (c) { return c.getAttribute('data-rubric') === want; })) setRubric(want, false);
        }
        apply();
    }

    /* ======================= СТАТЬЯ ======================= */
    var body = document.body;
    if (!body.getAttribute('data-slug')) return;

    /* --- оглавление: открыто на десктопе, свёрнуто на мобиле; подсветка раздела --- */
    var toc = document.getElementById('bp-toc');
    if (toc) {
        var desktop = window.matchMedia('(min-width: 1024px)');
        var sync = function () { toc.open = desktop.matches; };
        sync();
        if (desktop.addEventListener) desktop.addEventListener('change', sync); else desktop.addListener(sync);
        toc.addEventListener('click', function (e) { if (e.target.closest('a') && !desktop.matches) toc.open = false; });

        var links = {};
        toc.querySelectorAll('a[href^="#"]').forEach(function (a) {
            links[decodeURIComponent(a.getAttribute('href').slice(1))] = a;
        });
        var heads = [].filter.call(document.querySelectorAll('.md h2[id], .md h3[id]'), function (h) { return links[h.id]; });
        var current = null, tick = false;
        var spy = function () {
            tick = false;
            if (!heads.length) return;
            var line = window.innerHeight * 0.3, active = null;
            for (var i = 0; i < heads.length; i++) {
                if (heads[i].getBoundingClientRect().top <= line) active = heads[i].id; else break;
            }
            if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) active = heads[heads.length - 1].id;
            if (active === current) return;
            if (current && links[current]) links[current].removeAttribute('aria-current');
            current = active;
            if (active) links[active].setAttribute('aria-current', 'true');
        };
        window.addEventListener('scroll', function () { if (!tick) { tick = true; requestAnimationFrame(spy); } }, { passive: true });
        spy();
    }

    /* --- копировать ссылку --- */
    var copy = document.getElementById('copy-link');
    if (copy) {
        copy.addEventListener('click', function () {
            var url = copy.getAttribute('data-url'), label = copy.querySelector('span');
            var done = function () {
                label.textContent = 'Ссылка скопирована';
                setTimeout(function () { label.textContent = 'Копировать ссылку'; }, 2200);
            };
            if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(url).then(done, function () {});
            else {
                var ta = document.createElement('textarea'); ta.value = url; document.body.appendChild(ta); ta.select();
                try { document.execCommand('copy'); done(); } catch (e) {} document.body.removeChild(ta);
            }
        });
    }

    /* --- счётчик просмотров: только живой читатель, после 4 секунд на странице --- */
    var beacon = body.getAttribute('data-beacon');
    if (beacon && navigator.sendBeacon) {
        var key = 'v:' + body.getAttribute('data-slug');
        var seen = false;
        try { seen = !!sessionStorage.getItem(key); } catch (e) {}
        if (!seen) {
            setTimeout(function () {
                if (document.visibilityState !== 'visible') return;
                navigator.sendBeacon(beacon);
                try { sessionStorage.setItem(key, '1'); } catch (e) {}
            }, 4000);
        }
    }

    /* --- «Летучка по статье» --- */
    var box = document.getElementById('qz'), dataEl = document.getElementById('qz-data');
    if (!box || !dataEl) return;
    var quiz;
    try { quiz = JSON.parse(dataEl.textContent); } catch (e) { return; }
    if (!quiz || !quiz.length) return;
    box.hidden = false;

    var root = document.getElementById('qz-body');
    var ICON = function (id) { return '<svg class="icon" aria-hidden="true"><use href="#i-' + id + '"/></svg>'; };
    var esc = function (s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); };
    var step = 0, score = 0, marks = [];

    function steps(now) {
        return '<ol class="qz-steps" aria-hidden="true">' + quiz.map(function (_, i) {
            var c = marks[i] === 1 ? 'is-ok' : marks[i] === 0 ? 'is-bad' : i === now ? 'is-now' : '';
            return '<li class="' + c + '"></li>';
        }).join('') + '</ol>';
    }

    function ask() {
        var q = quiz[step];
        root.innerHTML = steps(step) +
            '<p class="qz-q" id="qz-q" tabindex="-1">' + esc(q.q) + '</p>' +
            '<ul class="qz-opts">' + q.options.map(function (o, i) {
                return '<li><button type="button" class="qz-opt" data-i="' + i + '"><span class="qz-mark">' + ICON('check') + '</span><span>' + esc(o) + '</span></button></li>';
            }).join('') + '</ul>' +
            '<p class="qz-why" id="qz-why" hidden role="status"></p>' +
            '<div class="qz-foot"><button type="button" class="btn" id="qz-next" hidden></button></div>';

        var opts = [].slice.call(root.querySelectorAll('.qz-opt'));
        opts.forEach(function (b) {
            b.addEventListener('click', function () {
                var pick = +b.getAttribute('data-i'), ok = pick === q.answer;
                marks[step] = ok ? 1 : 0; if (ok) score++;
                opts.forEach(function (x, i) {
                    x.disabled = true;
                    if (i === q.answer) { x.classList.add('is-ok'); }
                    else if (i === pick) { x.classList.add('is-bad'); x.querySelector('.qz-mark').innerHTML = ICON('x'); }
                    else x.classList.add('is-dim');
                });
                root.querySelector('.qz-steps').outerHTML = steps(step + 1);
                var why = document.getElementById('qz-why');
                var text = (ok ? 'Верно. ' : 'Не совсем. ') + (q.why || '');
                why.textContent = text.trim(); why.hidden = false;
                var next = document.getElementById('qz-next');
                next.innerHTML = (step === quiz.length - 1 ? 'Узнать результат' : 'Дальше') + ICON('arrow');
                next.hidden = false; next.focus({ preventScroll: true });
                next.addEventListener('click', function () { step++; step < quiz.length ? ask() : finish(); });
            });
        });
        document.getElementById('qz-q').focus({ preventScroll: true });
    }

    function finish() {
        var n = quiz.length, msg;
        if (score === n) msg = 'Всё верно. Так же быстро Летучка соберёт тест по вашему тексту.';
        else if (score >= Math.ceil(n / 2)) msg = 'Хороший результат. Спорные места лучше перечитать, а свой тест по ним можно собрать за полминуты.';
        else msg = 'Стоит вернуться к тексту. Или сделайте тест по нему сами: так материал запоминается лучше.';
        root.innerHTML = steps(-1) +
            '<div class="qz-res"><p class="qz-score" tabindex="-1" id="qz-score">' + score + '<span> из ' + n + '</span></p>' +
            '<p class="qz-msg">' + msg + '</p>' +
            '<div class="qz-acts"><a class="btn" href="/create">Сделать тест по своему тексту' + ICON('arrow') + '</a>' +
            '<button type="button" class="btn btn--ghost" id="qz-again">Пройти ещё раз</button></div></div>';
        document.getElementById('qz-again').addEventListener('click', function () { step = 0; score = 0; marks = []; ask(); });
        document.getElementById('qz-score').focus({ preventScroll: true });
    }

    ask();
})();
