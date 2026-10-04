/* =========================================================================
   ProviderHealth — модалка «Здоровье AI-провайдеров»
   Полное управление ключами + статистика расхода/запросов.
   ========================================================================= */
(function () {
  'use strict';

  const RANGES = ['7D', '14D', '30D', '90D'];

  const fmt = (n) => Number(n || 0).toLocaleString('ru-RU');

  const compact = (n) => {
    const v = Number(n || 0);
    if (v >= 1e9) return (v / 1e9).toFixed(2) + 'B';
    if (v >= 1e6) return (v / 1e6).toFixed(2) + 'M';
    if (v >= 1e3) return (v / 1e3).toFixed(1) + 'K';
    return String(v);
  };

  const money = (n) => {
    const v = Number(n || 0);
    if (!v) return '$0';
    if (v < 0.001) return '<$0.001';
    return '$' + v.toFixed(v < 1 ? 4 : 3);
  };

  const esc = (s) =>
    String(s == null ? '' : s).replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
    );

  const relTime = (days, never) => {
    if (never || days == null) return '<span class="text-slate-500">никогда</span>';
    if (days === 0) return '<span class="text-emerald-400">сегодня</span>';
    if (days === 1) return '<span class="text-slate-300">вчера</span>';
    if (days > 30) return '<span class="text-rose-400">' + days + ' дн. назад</span>';
    if (days > 7) return '<span class="text-amber-400">' + days + ' дн. назад</span>';
    return '<span class="text-slate-300">' + days + ' дн. назад</span>';
  };

  const statusMeta = (p) => {
    if (!p.is_active) return { dot: 'bg-slate-500', text: 'text-slate-400', label: 'Paused' };
    if (p.success_rate >= 90) return { dot: 'bg-emerald-400', text: 'text-emerald-400', label: 'Healthy' };
    if (p.success_rate > 0) return { dot: 'bg-amber-400', text: 'text-amber-400', label: 'Degraded' };
    return { dot: 'bg-rose-400', text: 'text-rose-400', label: 'No calls' };
  };

  const kpi = (label, value, sub, accent) => `
    <div class="rounded-xl bg-canvas border border-borderSubtle px-3.5 py-3">
      <div class="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">${esc(label)}</div>
      <div class="text-lg font-bold font-mono ${accent || 'text-white'} mt-1">${value}</div>
      ${sub ? `<div class="text-[10px] text-slate-500 font-mono mt-0.5">${sub}</div>` : ''}
    </div>`;

  const purposeBadge = (purpose) => {
    const colors = {
      SURVEY: 'bg-blue-500/10 text-blue-300 border-blue-500/25',
      FEEDBACK: 'bg-violet-500/10 text-violet-300 border-violet-500/25',
      AD: 'bg-amber-500/10 text-amber-300 border-amber-500/25',
      CHAT: 'bg-cyan-500/10 text-cyan-300 border-cyan-500/25',
      EMBEDDING: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/25',
      OTHER: 'bg-slate-500/10 text-slate-300 border-slate-500/25',
    };
    return `<span class="inline-flex px-1.5 py-0.5 rounded text-[10px] font-semibold border ${colors[purpose] || colors.OTHER}">${esc(purpose)}</span>`;
  };

  const ProviderHealth = {
    data: null,
    range: '14D',
    activeProvider: null,
    loading: false,
    formOpen: false,
    editingId: null,
    chart: null,

    // ---------- public ----------
    open(provider) {
      if (provider) this.activeProvider = provider;
      const modal = document.getElementById('ph-modal');
      if (!modal) return;
      modal.classList.remove('hidden');
      modal.classList.add('flex');
      document.body.style.overflow = 'hidden';
      this.load();
    },

    close() {
      const modal = document.getElementById('ph-modal');
      if (!modal) return;
      modal.classList.add('hidden');
      modal.classList.remove('flex');
      document.body.style.overflow = '';
      if (this.chart) { try { this.chart.destroy(); } catch (e) {} this.chart = null; }
      this.formOpen = false;
      this.editingId = null;
    },

    setRange(range) {
      if (RANGES.indexOf(range) === -1) return;
      this.range = range;
      document.querySelectorAll('.ph-range').forEach((b) => {
        const on = b.dataset.range === range;
        b.className = 'ph-range px-2.5 py-1 text-[11px] font-medium rounded-md btn-spring ' +
          (on ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200');
      });
      this.load();
    },

    selectProvider(name) {
      this.activeProvider = name || null;
      this.formOpen = false;
      this.editingId = null;
      this.render();
    },

    async load() {
      this.loading = true;
      const tabs = document.getElementById('ph-tabs');
      const body = document.getElementById('ph-body');
      if (tabs) tabs.innerHTML = '';
      if (body) body.innerHTML = '<div class="py-16 text-center text-xs font-mono text-slate-500"><i class="fa-solid fa-spinner fa-spin mr-2"></i>Собираю статистику провайдеров…</div>';
      try {
        const res = await fetch('/api/admin/providers/health/?range=' + encodeURIComponent(this.range), {
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        this.data = await res.json();
        this.loading = false;
        this.renderTabs();
        this.render();
      } catch (e) {
        this.loading = false;
        if (body) body.innerHTML = '<div class="py-16 text-center text-xs font-mono text-rose-400">Не удалось загрузить данные: ' + esc(e.message) + '</div>';
      }
    },

    // ---------- tabs ----------
    renderTabs() {
      const el = document.getElementById('ph-tabs');
      if (!el || !this.data) return;
      const providers = this.data.providers || [];
      const allActive = !this.activeProvider;
      const allCalls = providers.reduce((s, p) => s + (p.calls_period || 0), 0);
      const parts = [];
      parts.push(tabBtn('', 'Все провайдеры', allCalls, null, allActive));
      providers.forEach((p) => {
        const meta = statusMeta(p);
        parts.push(tabBtn(p.provider, p.provider, p.calls_period, meta, this.activeProvider === p.provider, p.stale_keys));
      });
      el.innerHTML = parts.join('');
    },

    // ---------- main render ----------
    render() {
      const body = document.getElementById('ph-body');
      if (!body || !this.data) return;
      this.updateTotalsHeader();
      let html = '';
      html += this.renderForm();
      if (this.activeProvider) {
        const p = (this.data.providers || []).find((x) => x.provider === this.activeProvider);
        html += p ? this.renderProvider(p) : this.renderOverview();
      } else {
        html += this.renderOverview();
      }
      body.innerHTML = html;
      this.bindInputs();
      this.drawChart();
    },

    updateTotalsHeader() {
      const el = document.getElementById('ph-totals');
      if (!el || !this.data) return;
      const t = this.data.totals || {};
      el.innerHTML =
        '<span class="text-slate-300">' + fmt(t.active_keys) + '</span>/' + fmt(t.keys) + ' ключей · ' +
        '<span class="text-slate-300">' + fmt(t.calls_period) + '</span> запросов · ' +
        '<span class="text-amber-300">' + compact(t.tokens_period) + '</span> токенов · ' +
        '<span class="text-emerald-300">' + money(t.cost_period) + '</span>' +
        (t.errors_period ? ' · <span class="text-rose-400">' + fmt(t.errors_period) + ' ошибок</span>' : '');
    },

    // ---------- overview ----------
    renderOverview() {
      const d = this.data;
      const t = d.totals || {};
      const providers = d.providers || [];
      const stale = d.stale_keys || 0;

      let html = '';
      html += '<div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">';
      html += kpi('Провайдеры', fmt(providers.length), fmt(t.keys) + ' ключей');
      html += kpi('Запросы', fmt(t.calls_period), 'за период', 'text-blue-300');
      html += kpi('Токены', compact(t.tokens_period), '≈ расход', 'text-amber-300');
      html += kpi('Расход (est.)', money(t.cost_period), 'USD, оценка', 'text-emerald-300');
      html += '</div>';

      if (stale > 0) {
        html += `<div class="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-500/25 bg-amber-500/5 px-4 py-3">
          <div class="text-xs text-amber-200"><i class="fa-solid fa-broom mr-1.5"></i>
            Найдено <b>${stale}</b> неиспользуемых ключей (>30 дней или ни разу не использовались).</div>
          <div class="flex items-center gap-2">
            <button onclick="ProviderHealth.cleanup('deactivate')" class="btn-spring text-[11px] font-semibold text-amber-300 bg-amber-500/10 border border-amber-500/25 hover:bg-amber-500/20 rounded-lg px-2.5 py-1">Отключить</button>
            <button onclick="ProviderHealth.cleanup('delete')" class="btn-spring text-[11px] font-semibold text-rose-300 bg-rose-500/10 border border-rose-500/25 hover:bg-rose-500/20 rounded-lg px-2.5 py-1">Удалить</button>
          </div>
        </div>`;
      }

      html += '<div class="rounded-xl bg-canvas border border-borderSubtle p-4 mb-4"><div class="h-44"><canvas id="ph-chart"></canvas></div></div>';

      html += `<div class="flex items-center justify-between mb-2">
        <div class="text-xs font-bold text-white">Провайдеры</div>
        <button onclick="ProviderHealth.openForm()" class="btn-spring inline-flex items-center gap-1.5 text-[11px] font-semibold text-blue-300 bg-blue-500/10 border border-blue-500/25 hover:bg-blue-500/20 rounded-lg px-2.5 py-1"><i class="fa-solid fa-plus text-[9px]"></i> Добавить ключ</button>
      </div>`;

      if (!providers.length) {
        html += '<div class="text-xs text-slate-500 py-12 text-center font-mono">Провайдеров пока нет — добавьте первый ключ.</div>';
        return html;
      }

      html += '<div class="overflow-x-auto rounded-xl border border-borderSubtle"><table class="w-full text-left font-mono text-xs">';
      html += `<thead class="bg-surfaceElevated/40"><tr class="text-[10px] uppercase tracking-wider text-slate-400">
        <th class="px-3 py-2.5 font-semibold">Провайдер</th>
        <th class="px-3 py-2.5 font-semibold">Статус</th>
        <th class="px-3 py-2.5 font-semibold">Ключи</th>
        <th class="px-3 py-2.5 font-semibold">Запросы</th>
        <th class="px-3 py-2.5 font-semibold">Токены</th>
        <th class="px-3 py-2.5 font-semibold">Расход</th>
        <th class="px-3 py-2.5 font-semibold">Успех</th>
        <th class="px-3 py-2.5 font-semibold">Ср. ответ</th>
        <th class="px-3 py-2.5 font-semibold">Последний</th>
      </tr></thead><tbody class="divide-y divide-borderSubtle/60">`;
      providers.forEach((p) => {
        const meta = statusMeta(p);
        html += `<tr class="hover:bg-surfaceElevated/50 transition-colors cursor-pointer" onclick="ProviderHealth.selectProvider(decodeURIComponent('${encodeURIComponent(p.provider)}'))">
          <td class="px-3 py-2.5">
            <div class="font-sans font-semibold text-white flex items-center gap-2">${esc(p.provider)}
              ${p.stale_keys ? '<span class="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20">' + p.stale_keys + ' stale</span>' : ''}
            </div>
            <div class="text-[10px] text-slate-500">${esc((p.models || []).slice(0, 2).join(', ') || '—')}</div>
          </td>
          <td class="px-3 py-2.5"><span class="inline-flex items-center gap-1.5 ${meta.text}"><span class="w-1.5 h-1.5 rounded-full ${meta.dot}"></span>${meta.label}</span></td>
          <td class="px-3 py-2.5 text-slate-300">${p.active_keys}/${p.keys_count}</td>
          <td class="px-3 py-2.5 text-blue-300 font-semibold">${fmt(p.calls_period)}</td>
          <td class="px-3 py-2.5 text-amber-300">${compact(p.tokens_period)}</td>
          <td class="px-3 py-2.5 text-emerald-300 font-semibold">${money(p.cost_period)}</td>
          <td class="px-3 py-2.5 text-slate-200">${p.success_rate}%</td>
          <td class="px-3 py-2.5 text-slate-400">${p.avg_response_ms} ms</td>
          <td class="px-3 py-2.5 text-slate-400">${esc(p.last_used || '—')}</td>
        </tr>`;
      });
      html += '</tbody></table></div>';
      return html;
    },

    // ---------- provider detail ----------
    renderProvider(p) {
      const meta = statusMeta(p);
      let html = '';
      html += `<div class="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div class="flex items-center gap-3">
          <button onclick="ProviderHealth.selectProvider(null)" class="btn-spring text-slate-400 hover:text-white w-7 h-7 rounded-lg bg-canvas border border-borderSubtle"><i class="fa-solid fa-arrow-left text-xs"></i></button>
          <div>
            <div class="text-base font-bold text-white flex items-center gap-2">${esc(p.provider)}
              <span class="inline-flex items-center gap-1.5 text-[11px] ${meta.text}"><span class="w-1.5 h-1.5 rounded-full ${meta.dot}"></span>${meta.label}</span>
            </div>
            <div class="text-[10px] text-slate-500 font-mono">${p.keys_count} ключей · ${p.active_keys} активных · ${esc((p.models || []).join(', ') || 'модели не заданы')}</div>
          </div>
        </div>
        <div class="flex items-center gap-2">
          <button onclick="ProviderHealth.openForm()" class="btn-spring inline-flex items-center gap-1.5 text-[11px] font-semibold text-blue-300 bg-blue-500/10 border border-blue-500/25 hover:bg-blue-500/20 rounded-lg px-2.5 py-1"><i class="fa-solid fa-plus text-[9px]"></i> Добавить ключ</button>
        </div>
      </div>`;

      html += '<div class="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">';
      html += kpi('Запросы', fmt(p.calls_period), 'за период', 'text-blue-300');
      html += kpi('Токены', compact(p.tokens_period), 'за период', 'text-amber-300');
      html += kpi('Расход (est.)', money(p.cost_period), 'USD', 'text-emerald-300');
      html += kpi('Успешность', p.success_rate + '%', p.calls_period + ' запросов');
      html += kpi('Ср. ответ', p.avg_response_ms + ' ms', 'последний: ' + esc(p.last_used || '—'));
      html += '</div>';

      const periodCalls = p.series.calls.reduce((s, v) => s + v, 0);
      const periodCost = p.series.cost.reduce((s, v) => s + v, 0);
      html += '<div class="flex flex-wrap items-center justify-between mb-2">';
      html += '<div class="text-xs font-bold text-white">Динамика за ' + esc(this.data.range) + '</div>';
      html += '<div class="text-[10px] font-mono text-slate-500">' + fmt(periodCalls) + ' запросов · ' + money(periodCost) + '</div>';
      html += '</div>';
      html += '<div class="rounded-xl bg-canvas border border-borderSubtle p-4 mb-4"><div class="h-40"><canvas id="ph-chart"></canvas></div></div>';

      html += this.renderKeysTable(p.keys, p.provider);
      return html;
    },

    renderKeysTable(keys, provider) {
      let html = '<div class="overflow-x-auto rounded-xl border border-borderSubtle"><table class="w-full text-left font-mono text-xs min-w-[980px]">';
      html += `<thead class="bg-surfaceElevated/40"><tr class="text-[10px] uppercase tracking-wider text-slate-400">
        <th class="px-3 py-2.5 font-semibold">Ключ</th>
        <th class="px-3 py-2.5 font-semibold">Назначение</th>
        <th class="px-3 py-2.5 font-semibold">Модель</th>
        <th class="px-3 py-2.5 font-semibold">Запросы</th>
        <th class="px-3 py-2.5 font-semibold">Токены</th>
        <th class="px-3 py-2.5 font-semibold">Расход</th>
        <th class="px-3 py-2.5 font-semibold">Успех</th>
        <th class="px-3 py-2.5 font-semibold">Использован</th>
        <th class="px-3 py-2.5 font-semibold text-right">Действия</th>
      </tr></thead><tbody class="divide-y divide-borderSubtle/60">`;
      keys.forEach((k) => {
        const active = k.is_active;
        html += `<tr class="${active ? 'bg-emerald-500/[0.03]' : ''} hover:bg-surfaceElevated/40 transition-colors">
          <td class="px-3 py-2.5 max-w-[220px]">
            <div class="flex items-center gap-1.5">
              <span class="font-sans font-semibold text-white truncate" title="${esc(k.name)}">${esc(k.name)}</span>
              ${k.is_system ? '<span class="text-[9px] px-1 py-0.5 rounded bg-violet-500/10 text-violet-300 border border-violet-500/25" title="Ключ из .env">.env</span>' : ''}
              ${k.stale ? '<span class="text-[9px] px-1 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/25">stale</span>' : ''}
            </div>
            <div class="text-[10px] text-slate-500 truncate" title="${esc(k.masked_key)}">
              ${esc(k.masked_key)}
              ${k.base_url ? ' · <span class="text-slate-600">' + esc(k.base_url.replace(/^https?:\/\//, '')) + '</span>' : ''}
            </div>
          </td>
          <td class="px-3 py-2.5">${purposeBadge(k.purpose)}</td>
          <td class="px-3 py-2.5 text-slate-300 max-w-[160px] truncate" title="${esc(k.model_name)}">${esc(k.model_name || '—')}</td>
          <td class="px-3 py-2.5 text-blue-300">${fmt(k.calls_period)}<span class="text-slate-600"> / ${fmt(k.calls_total)}</span></td>
          <td class="px-3 py-2.5 text-amber-300">${compact(k.tokens_period)}<span class="text-slate-600"> / ${compact(k.tokens_total)}</span></td>
          <td class="px-3 py-2.5 text-emerald-300 font-semibold">${money(k.cost_period)}<div class="text-[9px] text-slate-600 font-normal">@ ${money(k.price_per_1m)}/1M</div></td>
          <td class="px-3 py-2.5 ${k.calls_period && k.success_rate < 90 ? 'text-rose-400' : 'text-slate-200'}">${k.calls_period ? k.success_rate + '%' : '—'}</td>
          <td class="px-3 py-2.5 text-[10px]">${relTime(k.days_since_used, k.never_used)}${k.expires_at ? '<div class="text-slate-600">до ' + esc(k.expires_at) + '</div>' : ''}</td>
          <td class="px-3 py-2.5">
            <div class="flex items-center justify-end gap-1">
              <button title="${active ? 'Отключить' : 'Сделать активным'}" onclick="ProviderHealth.toggle(${k.id})"
                class="btn-spring w-7 h-7 rounded-lg border ${active ? 'text-emerald-300 bg-emerald-500/10 border-emerald-500/25' : 'text-slate-400 bg-canvas border-borderSubtle hover:text-white'}">
                <i class="fa-solid fa-power-off text-[11px]"></i></button>
              <button title="Проверить ключ" onclick="ProviderHealth.test(${k.id})"
                class="btn-spring w-7 h-7 rounded-lg text-blue-300 bg-blue-500/10 border border-blue-500/25 hover:bg-blue-500/20">
                <i class="fa-solid fa-bolt text-[11px]"></i></button>
              <button title="Редактировать" onclick="ProviderHealth.openForm(${k.id})"
                class="btn-spring w-7 h-7 rounded-lg text-slate-300 bg-canvas border border-borderSubtle hover:text-white">
                <i class="fa-solid fa-pen text-[11px]"></i></button>
              ${k.is_system ? '' : `<button title="Удалить" onclick="ProviderHealth.remove(${k.id})"
                class="btn-spring w-7 h-7 rounded-lg text-rose-300 bg-rose-500/10 border border-rose-500/25 hover:bg-rose-500/20">
                <i class="fa-solid fa-trash text-[11px]"></i></button>`}
            </div>
          </td>
        </tr>`;
      });
      html += '</tbody></table></div>';
      return html;
    },

    // ---------- add / edit form ----------
    renderForm() {
      if (!this.formOpen) return '';
      const d = this.data || {};
      const presets = d.presets || {};
      const pricing = d.pricing || {};
      const editing = this.editingId
        ? this.findKey(this.editingId)
        : null;
      const k = editing || {};

      const providerNames = Object.keys(presets);
      (d.providers || []).forEach((p) => {
        if (providerNames.indexOf(p.provider.toLowerCase()) === -1 && providerNames.indexOf(p.provider) === -1) {
          providerNames.push(p.provider);
        }
      });

      const modelList = Array.from(new Set(
        providerNames.flatMap((name) => (presets[name] && presets[name].models) || [])
          .concat(Object.keys(pricing))
      ));

      const purposes = d.purposes || ['SURVEY', 'FEEDBACK', 'AD', 'CHAT', 'EMBEDDING', 'OTHER'];
      const providerValue = k.provider || this.activeProvider || '';
      const isSystem = !!k.is_system;

      let html = `<div class="rounded-xl border border-blue-500/25 bg-blue-500/[0.04] p-4 mb-4">
        <div class="flex items-center justify-between mb-3">
          <div class="text-xs font-bold text-white"><i class="fa-solid fa-key text-blue-400 mr-1.5"></i>${editing ? 'Редактирование ключа' : 'Новый ключ'}</div>
          <button onclick="ProviderHealth.closeForm()" class="text-slate-400 hover:text-white"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
          <label class="block">
            <span class="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Название</span>
            <input id="ph-f-name" value="${esc(k.name || '')}" placeholder="Например: GPT-4o main"
              class="mt-1 w-full rounded-lg bg-canvas border border-borderSubtle px-3 py-2 text-xs text-white outline-none focus:border-blue-500/50">
          </label>
          <label class="block">
            <span class="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Провайдер</span>
            <input id="ph-f-provider" list="ph-providers" value="${esc(providerValue)}" oninput="ProviderHealth.onProviderInput()"
              placeholder="openai / gemini / openrouter"
              class="mt-1 w-full rounded-lg bg-canvas border border-borderSubtle px-3 py-2 text-xs text-white outline-none focus:border-blue-500/50">
            <datalist id="ph-providers">${providerNames.map((n) => '<option value="' + esc(n) + '"></option>').join('')}</datalist>
          </label>
          <label class="block">
            <span class="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Назначение</span>
            <select id="ph-f-purpose" class="mt-1 w-full rounded-lg bg-canvas border border-borderSubtle px-3 py-2 text-xs text-white outline-none focus:border-blue-500/50">
              ${purposes.map((p) => '<option value="' + esc(p) + '"' + (k.purpose === p ? ' selected' : '') + '>' + esc(p) + '</option>').join('')}
            </select>
          </label>
          <label class="block md:col-span-2">
            <span class="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Base URL <span class="text-slate-600 normal-case">(необязательно)</span></span>
            <input id="ph-f-baseurl" value="${esc(k.base_url || '')}" placeholder="https://api.openai.com/v1"
              class="mt-1 w-full rounded-lg bg-canvas border border-borderSubtle px-3 py-2 text-xs text-white font-mono outline-none focus:border-blue-500/50">
          </label>
          <label class="block">
            <span class="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Модель</span>
            <input id="ph-f-model" list="ph-models" value="${esc(k.model_name || '')}" placeholder="gpt-4o-mini"
              class="mt-1 w-full rounded-lg bg-canvas border border-borderSubtle px-3 py-2 text-xs text-white font-mono outline-none focus:border-blue-500/50">
            <datalist id="ph-models">${modelList.map((n) => '<option value="' + esc(n) + '"></option>').join('')}</datalist>
          </label>
          <label class="block md:col-span-2">
            <span class="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">API-ключ ${editing ? '(оставьте пустым, чтобы не менять)' : ''}</span>
            <div class="relative mt-1">
              <input id="ph-f-key" type="password" autocomplete="new-password" ${isSystem ? 'disabled placeholder="Используется OPENAI_API_KEY из .env"' : 'placeholder="sk-…"'}
                class="w-full rounded-lg bg-canvas border border-borderSubtle px-3 py-2 pr-9 text-xs text-white font-mono outline-none focus:border-blue-500/50 disabled:opacity-50">
              <button type="button" onclick="ProviderHealth.revealKey()" class="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"><i class="fa-regular fa-eye text-xs"></i></button>
            </div>
          </label>
          <label class="block">
            <span class="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Тариф, $/1M токенов</span>
            <input id="ph-f-cost" type="number" step="0.0001" min="0" value="${k.cost_per_1m_tokens ? k.cost_per_1m_tokens : ''}"
              placeholder="авто по модели"
              class="mt-1 w-full rounded-lg bg-canvas border border-borderSubtle px-3 py-2 text-xs text-white font-mono outline-none focus:border-blue-500/50">
          </label>
          <label class="block">
            <span class="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Истекает</span>
            <input id="ph-f-expires" type="date" value="${esc(k.expires_at || '')}"
              class="mt-1 w-full rounded-lg bg-canvas border border-borderSubtle px-3 py-2 text-xs text-white font-mono outline-none focus:border-blue-500/50">
          </label>
          <div class="flex items-end gap-4">
            <label class="inline-flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
              <input id="ph-f-active" type="checkbox" ${editing ? (k.is_active ? 'checked' : '') : 'checked'} class="accent-blue-500">
              Сделать активным
            </label>
            ${isSystem ? '<span class="text-[10px] text-violet-300">системный .env</span>' : `
            <label class="inline-flex items-center gap-2 text-xs text-slate-300 cursor-pointer" title="Ключ будет читаться из OPENAI_API_KEY">
              <input id="ph-f-env" type="checkbox" class="accent-violet-500"> из .env
            </label>`}
          </div>
        </div>
        <div class="flex items-center justify-end gap-2 mt-4">
          <button onclick="ProviderHealth.closeForm()" class="btn-spring text-xs text-slate-400 hover:text-white px-3 py-1.5 rounded-lg bg-canvas border border-borderSubtle">Отмена</button>
          <button onclick="ProviderHealth.save()" class="btn-spring text-xs font-semibold text-white bg-blue-600 hover:bg-blue-500 px-4 py-1.5 rounded-lg">
            <i class="fa-solid fa-floppy-disk mr-1"></i>${editing ? 'Сохранить' : 'Добавить ключ'}
          </button>
        </div>
      </div>`;
      return html;
    },

    // ---------- form helpers ----------
    openForm(id, provider) {
      this.formOpen = true;
      this.editingId = id || null;
      if (!id && provider) this.activeProvider = provider;
      this.render();
      const el = document.getElementById('ph-f-name');
      if (el) el.focus();
    },

    closeForm() {
      this.formOpen = false;
      this.editingId = null;
      this.render();
    },

    onProviderInput() {
      const input = document.getElementById('ph-f-provider');
      if (!input || !this.data) return;
      const preset = (this.data.presets || {})[input.value.trim().toLowerCase()];
      if (!preset) return;
      const url = document.getElementById('ph-f-baseurl');
      const model = document.getElementById('ph-f-model');
      if (url && !url.value && preset.base_url) url.value = preset.base_url;
      if (model && !model.value && preset.models && preset.models.length) model.value = preset.models[0];
    },

    revealKey() {
      const el = document.getElementById('ph-f-key');
      if (el) el.type = el.type === 'password' ? 'text' : 'password';
    },

    bindInputs() {
      const provider = document.getElementById('ph-f-provider');
      if (provider && !provider.value) this.onProviderInput();
    },

    async save() {
      const val = (id) => {
        const el = document.getElementById(id);
        return el ? el.value.trim() : '';
      };
      const checked = (id) => {
        const el = document.getElementById(id);
        return el ? el.checked : false;
      };
      const body = {
        name: val('ph-f-name'),
        provider: val('ph-f-provider'),
        purpose: val('ph-f-purpose') || 'SURVEY',
        base_url: val('ph-f-baseurl'),
        model_name: val('ph-f-model'),
        key: val('ph-f-key'),
        cost_per_1m_tokens: val('ph-f-cost') || null,
        expires_at: val('ph-f-expires'),
        is_active: checked('ph-f-active'),
        use_env: checked('ph-f-env'),
      };
      if (this.editingId) body.id = this.editingId;
      if (!body.name || !body.provider) { toast('Укажите название и провайдера', 'error'); return; }
      if (!this.editingId && !body.key && !body.use_env) { toast('Нужно значение ключа или галочка «из .env»', 'error'); return; }
      const r = await postJSON('/api/admin/api-keys/save/', body);
      if (r.ok) {
        toast((r.created ? 'Ключ добавлен' : 'Ключ обновлён') + ' · тариф ' + money(r.price_per_1m) + '/1M', 'ok');
        this.formOpen = false;
        this.editingId = null;
        await this.load();
      } else {
        toast(r.error || 'Ошибка сохранения', 'error');
      }
    },

    async toggle(id) {
      const r = await postJSON('/api/admin/api-keys/' + id + '/toggle/', {});
      if (r.ok) { toast(r.is_active ? 'Ключ активирован' : 'Ключ отключён', 'ok'); await this.load(); }
      else toast(r.error || 'Ошибка', 'error');
    },

    async test(id) {
      const k = this.findKey(id);
      toast('Проверяю ' + (k ? k.name : 'ключ') + '…', 'ok');
      try {
        const res = await fetch('/api/admin/api-keys/' + id + '/test/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
          body: '{}',
        });
        const r = await res.json();
        if (r.ok) toast('OK · ' + r.response_ms + ' ms · ' + r.model, 'ok');
        else toast('Ошибка проверки: ' + (r.error || 'unknown'), 'error');
        await this.load();
      } catch (e) {
        toast('Ошибка сети: ' + e.message, 'error');
      }
    },

    async remove(id) {
      const k = this.findKey(id);
      if (!k) return;
      if (!confirm('Удалить ключ «' + k.name + '»? Статистика использования тоже удалится.')) return;
      const r = await postJSON('/api/admin/api-keys/' + id + '/delete/', {});
      if (r.ok) { toast('Ключ «' + r.deleted + '» удалён', 'ok'); await this.load(); }
      else toast(r.error || 'Ошибка удаления', 'error');
    },

    async cleanup(mode) {
      const daysRaw = prompt('Считать неиспользуемыми ключи без запросов дольше N дней (по умолчанию 30):', '30');
      if (daysRaw === null) return;
      const days = parseInt(daysRaw, 10) || 30;
      const verb = mode === 'delete' ? 'УДАЛИТЬ' : 'отключить';
      if (!confirm('Точно ' + verb + ' ключи без запросов > ' + days + ' дн.?')) return;
      const r = await postJSON('/api/admin/api-keys/cleanup/', { mode: mode, days: days });
      if (r.ok) {
        toast((mode === 'delete' ? 'Удалено' : 'Отключено') + ': ' + r.count + (r.names && r.names.length ? ' (' + r.names.slice(0, 3).join(', ') + (r.names.length > 3 ? '…' : '') + ')' : ''), 'ok');
        await this.load();
      } else toast(r.error || 'Ошибка чистки', 'error');
    },

    findKey(id) {
      if (!this.data) return null;
      for (const p of this.data.providers || []) {
        const found = (p.keys || []).find((k) => k.id === id);
        if (found) return found;
      }
      return null;
    },

    // ---------- chart ----------
    drawChart() {
      if (!window.Chart) return;
      const canvas = document.getElementById('ph-chart');
      if (!canvas) return;
      if (this.chart) { try { this.chart.destroy(); } catch (e) {} this.chart = null; }

      let labels = [];
      let calls = [];
      let tokens = [];
      let cost = [];
      if (this.activeProvider) {
        const p = (this.data.providers || []).find((x) => x.provider === this.activeProvider);
        if (!p) return;
        labels = p.series.labels; calls = p.series.calls; tokens = p.series.tokens; cost = p.series.cost;
      } else {
        (this.data.providers || []).forEach((p, idx) => {
          if (idx === 0) { labels = p.series.labels.slice(); tokens = p.series.tokens.slice(); cost = p.series.cost.slice(); }
          p.series.calls.forEach((v, i) => { calls[i] = (calls[i] || 0) + v; });
        });
      }

      const gridColor = 'rgba(255,255,255,0.04)';
      try {
        this.chart = new Chart(canvas.getContext('2d'), {
          data: {
            labels: labels,
            datasets: [
              { type: 'bar', label: 'Запросы', data: calls, backgroundColor: '#3B82F6', borderRadius: 4, yAxisID: 'y', order: 3 },
              { type: 'line', label: 'Токены', data: tokens, borderColor: '#F59E0B', backgroundColor: '#F59E0B18', fill: true, tension: 0.4, pointRadius: 0, borderWidth: 2, yAxisID: 'y1', order: 1 },
              { type: 'line', label: 'Расход, $', data: cost, borderColor: '#10B981', backgroundColor: '#10B98118', fill: false, tension: 0.4, pointRadius: 0, borderWidth: 2, yAxisID: 'y2', order: 0 },
            ],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
              legend: { labels: { color: '#94A3B8', font: { size: 10 }, boxWidth: 8 } },
              tooltip: {
                backgroundColor: '#090A0F', borderColor: 'rgba(255,255,255,0.08)', borderWidth: 1,
                titleColor: '#F8FAFC', bodyColor: '#94A3B8', padding: 10, cornerRadius: 8,
                callbacks: {
                  label: (ctx) => {
                    if (ctx.dataset.label === 'Расход, $') return ' ' + ctx.dataset.label + ': ' + money(ctx.parsed.y);
                    return ' ' + ctx.dataset.label + ': ' + fmt(ctx.parsed.y);
                  },
                },
              },
            },
            scales: {
              x: { grid: { display: false }, ticks: { color: '#64748B', font: { size: 10, family: 'JetBrains Mono' }, maxTicksLimit: 14 } },
              y: { position: 'left', beginAtZero: true, grid: { color: gridColor }, ticks: { color: '#3B82F6', font: { size: 9, family: 'JetBrains Mono' } } },
              y1: { position: 'right', beginAtZero: true, grid: { display: false }, ticks: { color: '#F59E0B', font: { size: 9, family: 'JetBrains Mono' }, callback: (v) => compact(v) } },
              y2: { display: false, beginAtZero: true },
            },
          },
        });
      } catch (e) { console.warn('ProviderHealth chart', e); }
    },
  };

  function tabBtn(value, label, calls, meta, active, stale) {
    const base = 'ph-tab btn-spring inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium border ';
    const on = 'bg-surfaceElevated text-white border-borderHover';
    const off = 'text-slate-400 border-transparent hover:text-white hover:bg-surfaceElevated/60';
    const dot = meta ? ('<span class="w-1.5 h-1.5 rounded-full ' + meta.dot + '"></span>') : '<i class="fa-solid fa-layer-group text-[10px] text-slate-500"></i>';
    return '<button data-tab="' + esc(value) + '" onclick="ProviderHealth.selectProvider(' + (value ? "decodeURIComponent('" + encodeURIComponent(value) + "')" : 'null') + ')" class="' + base + (active ? on : off) + '">' +
      dot + esc(label) +
      (calls ? '<span class="font-mono text-[10px] text-slate-500">' + fmt(calls) + '</span>' : '') +
      (stale ? '<span class="text-[9px] px-1 rounded bg-amber-500/15 text-amber-300">' + stale + '</span>' : '') +
      '</button>';
  }

  window.ProviderHealth = ProviderHealth;

  document.addEventListener('DOMContentLoaded', function () {
    const modal = document.getElementById('ph-modal');
    if (modal) {
      modal.addEventListener('click', function (e) {
        if (e.target === modal) ProviderHealth.close();
      });
    }
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && modal && !modal.classList.contains('hidden')) ProviderHealth.close();
    });
  });
})();
