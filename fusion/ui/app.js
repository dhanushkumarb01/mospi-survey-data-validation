/* MoSPI survey data validation — supervisor workspace.
 *
 * Every value shown comes from the local API, which reads stored validation
 * runs.  Nothing here computes or invents evidence; the only arithmetic is
 * formatting and simple shares of stored counts.
 *
 * Workflow: overview -> worklist (by FSU and household) -> case (what was
 * recorded, the comparisons, what to check) -> decision -> next case.
 * Technical details stay one click away, behind "Technical details".
 *
 * A hosted instance can be review-only (no batch can start) and audit read-only
 * (no decision can be recorded); /api/deployment says so and the server enforces
 * both, so the UI only explains them. */

const app = document.querySelector('#app');
const runSelect = document.querySelector('#runSelect');
const reviewerInput = document.querySelector('#reviewer');
const PAGE_SIZE = 50;
const S = { runs: [], run: null, labels: null, filters: {}, page: 1, user: null, ov: null, deploy: { review_only: false, audit_writable: true } };
const nf = new Intl.NumberFormat('en-IN');

const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]));
const n = v => (v == null || Number.isNaN(Number(v)) ? '—' : nf.format(v));
const pct = (part, whole) => (whole ? `${((part / whole) * 100).toFixed(1)}%` : '—');
const when = iso => { try { return new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }); } catch { return iso || ''; } };
const store = {
  get(k, fallback) { try { const v = (k.startsWith('s:') ? sessionStorage : localStorage).getItem(k.slice(2)); return v == null ? fallback : JSON.parse(v); } catch { return fallback; } },
  set(k, v) { try { (k.startsWith('s:') ? sessionStorage : localStorage).setItem(k.slice(2), JSON.stringify(v)); } catch { /* storage unavailable */ } },
};
function money(v) { return v == null ? '—' : `₹${nf.format(Math.round(Number(v)))}`; }

/* ------------------------------------------------------------ API */

function authToken() { return store.get('s:MoSPI.token', ''); }
async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (authToken()) headers.Authorization = `Bearer ${authToken()}`;
  const r = await fetch(path, { ...options, headers });
  if (r.status === 401) { store.set('s:MoSPI.token', ''); await signIn(); return api(path, options); }
  if (!r.ok) { let d = r.statusText; try { d = (await r.json()).detail || d; } catch { /* not JSON */ } throw Object.assign(new Error(d), { status: r.status }); }
  return r.json();
}
function url(path, params = {}) {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''));
  return q.toString() ? `${path}?${q}` : path;
}
function notice(text, kind = '') {
  const el = document.querySelector('#notice');
  el.textContent = text || ''; el.className = `notice ${kind}`; el.classList.toggle('hidden', !text);
}
function reviewer() { return reviewerInput.value.trim(); }
function runLabel(r) { return `PLFS ${String(r.release || '').replace('_', '–')} · ${r.observation === 'first_visit' ? 'first visit' : r.observation} · ${String(r.fusion_version || '').includes('lanes') ? 'current method' : 'superseded method'} (${r.directory})`; }
function currentRun() { return S.runs.find(r => r.directory === S.run) || {}; }
const isLanes = () => String(currentRun().fusion_version || '').includes('lanes');
function crumbs(parts) { document.title = [...parts.slice().reverse(), 'MoSPI'].join(' · '); }
function empty(text) { return `<div class="empty">${esc(text)}</div>`; }

/* Small stroke icons (decorative; always next to a text label). */
const ICON_PATHS = {
  alert: '<path d="M12 3 2 20h20L12 3z"/><path d="M12 10v4M12 17h.01"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  group: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  check: '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
  arrow: '<path d="M7 17 17 7M9 7h8v8"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  map: '<path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2z"/><path d="M9 4v14M15 6v14"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5h.01"/>',
  play: '<circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4z"/>',
  back: '<path d="M15 18 9 12l6-6"/>',
};
const icon = name => `<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON_PATHS[name] || ''}</svg>`;
function pageHead({ eyebrow = '', title, lede = '', actions = '' }) {
  return `<div class="page-head"><div>${eyebrow ? `<p class="eyebrow">${esc(eyebrow)}</p>` : ''}<h1>${esc(title)}</h1>${lede ? `<p class="lede">${lede}</p>` : ''}</div>${actions ? `<div class="page-actions">${actions}</div>` : ''}</div>`;
}
const panelHead = (title, iconName = '', right = '') => `<div class="panel-head"><h2>${iconName ? icon(iconName) : ''}${esc(title)}</h2>${right}</div>`;
const meter = (part, whole) => `<div class="meter" role="img" aria-label="${n(part)} of ${n(whole)}"><i style="width:${whole ? Math.min(100, (part / whole) * 100) : 0}%"></i></div>`;
const infoBox = (html, tone = '') => `<div class="info ${tone}">${icon('info')}<div>${html}</div></div>`;
function pager(prev, next, label = '') {
  return prev || next || label ? `<div class="pager">${label ? `<span>${label}</span>` : ''}${prev || ''}${next || ''}</div>` : '';
}

/* ------------------------------------------------------------ small renderers */

const TIER_CHIP = { CHECK_NOW: 'red', CHECK_IF_TIME: 'amber', NOT_FLAGGED: '', NOT_ASSESSABLE: '', CRITICAL: 'red', HIGH: 'amber' };
const DECISION_CHIP = { CONFIRMED_ERROR: 'red', VALID_BUT_UNUSUAL: 'green', NEEDS_FIELD_VERIFICATION: 'amber', CANNOT_VERIFY: '', ESCALATE: 'amber', UNREVIEWED: '' };
const chip = (text, tone = '') => `<span class="chip ${tone}">${esc(text)}</span>`;
const bandChip = code => chip(S.labels.bands[code] || code, TIER_CHIP[code] || '');
const decisionChip = code => chip(S.labels.decisions[code] || code, DECISION_CHIP[code] || '');
const laneChips = r => (r.lane_labels || []).map(l => chip(l, /rule/i.test(l) ? 'red' : 'blue')).join('') || '';
const bar = (value, max, tone = '') => `<div class="bar ${tone}" title="${n(value)}"><i style="width:${max ? Math.min(100, (value / max) * 100) : 0}%"></i></div>`;
function kv(items) { return `<dl class="kv">${items.map(i => `<dt>${esc(i.label)}</dt><dd>${esc(i.value)}</dd>`).join('')}</dl>`; }
function tech(data, label = 'Technical details') { return data ? `<details><summary>${esc(label)}</summary><pre>${esc(JSON.stringify(data, null, 2))}</pre></details>` : ''; }
function table(headers, rows, { empty: none = 'Nothing to show.' } = {}) {
  if (!rows.length) return empty(none);
  return `<div class="table-wrap"><table><thead><tr>${headers.map(h => `<th class="${h.num ? 'num' : ''}">${esc(h.label ?? h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
}
async function overviewData(force = false) {
  if (!force && S.ov && S.ov.run === S.run) return S.ov.data;
  S.ov = { run: S.run, data: await api(url('/api/overview', { run: S.run })) };
  return S.ov.data;
}
function supersededBanner() {
  return isLanes() ? '' : `<div class="panel warn"><b>Superseded method.</b> This run was produced by the earlier V2.0 priority (average of ranks × influence), which was replaced because it lost evidence and over-reviewed small UTs. It is kept for the record; select a current-method run for review work.</div>`;
}

/* ------------------------------------------------------------ routing */

const routes = { overview, worklist, cases, case: casePage, groups, group: groupPage, areas, reviewed, technical, batch: id => (id ? batchJob(id) : batch()) };
async function route() {
  const [path, query] = location.hash.replace(/^#\/?/, '').split('?');
  const [name, ...rest] = path.split('/');
  const page = routes[name] ? name : 'overview';
  document.querySelectorAll('#nav a').forEach(a => {
    const on = a.dataset.route === (page === 'case' ? 'cases' : page === 'group' ? 'groups' : page);
    if (page !== 'batch') stopBatchTimer();
    a.classList.toggle('active', on);
    if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  notice(S.flash?.text || '', S.flash?.kind || ''); S.flash = null;
  app.innerHTML = '<div class="loading">Loading…</div>';
  try { await routes[page](decodeURIComponent(rest.join('/')), new URLSearchParams(query || '')); }
  catch (e) {
    app.innerHTML = `<div class="panel red error-state"><h2>This page could not be loaded</h2><p>${esc(e.message)}</p><button class="secondary" id="retry">Try again</button></div>`;
    document.querySelector('#retry').onclick = route;
  }
  window.scrollTo(0, 0);
}
window.addEventListener('hashchange', route);
function go(hash) { if (location.hash === hash) route(); else location.hash = hash; }

/* ------------------------------------------------------------ overview */

async function overview() {
  crumbs(['Overview']);
  const [o, rev, grp] = await Promise.all([overviewData(true), api(url('/api/reviews', { run: S.run })),
    api(url('/api/groups', { run: S.run, band: 'ALERTS', limit: 5 })).catch(() => ({ rows: [], total: 0 }))]);
  const bands = Object.fromEntries(o.bands.map(b => [b.band, b]));
  const lanes = isLanes();
  const now = bands[lanes ? 'CHECK_NOW' : 'CRITICAL'] || { records: 0, reviewed: 0 };
  const later = bands[lanes ? 'CHECK_IF_TIME' : 'HIGH'] || { records: 0, reviewed: 0 };
  const groups = Object.fromEntries(o.groups.map(g => [g.band, g.groups]));
  const r = o.review;
  const budget = o.budget || {};
  const burden = o.burden || {};
  const reasons = o.highest_reasons || {};
  const states = o.highest_by_state || [];
  const maxState = Math.max(1, ...states.map(s => s.highest));
  const alertFsus = (groups.HIGH || 0) + (groups.MEDIUM || 0);
  const left = Math.max(0, (now.records || 0) - (now.reviewed || 0));
  const nowLabel = lanes ? S.labels.bands.CHECK_NOW : 'highest priority';
  const laterLabel = lanes ? S.labels.bands.CHECK_IF_TIME : 'high priority';
  const metric = ({ dot = '', label, value, sub, href }) => `<a class="metric" href="${href}"><span class="m-label"><span class="dot ${dot}"></span>${esc(label)}</span>
    <span class="m-value">${value}</span><span class="m-sub">${sub}</span></a>`;
  const maxReason = Math.max(1, ...Object.values(reasons));
  const run = currentRun();
  const startHref = `#/worklist${left ? '' : '?tier=B'}`;
  app.innerHTML = `${supersededBanner()}
    ${pageHead({ eyebrow: 'Selected validation run', title: 'Overview', lede: `${esc(runLabel(run).replace(/ \([^)]*\)$/, ''))}<code class="run-id">${esc(run.directory || '')}</code>`,
      actions: `<a class="btn secondary" href="#/reviewed">Decisions</a><a class="btn secondary" href="${lanes ? '#/worklist' : '#/cases'}">${icon('list')}Open ${lanes ? 'worklist' : 'case list'}</a>` })}
    <section class="summary" aria-label="Review queue">
      <div class="metric lead">
        <span class="m-label"><span class="dot red"></span>${lanes ? `Needs a decision · “${esc(nowLabel)}”` : 'Highest priority, not yet decided'}</span>
        <span class="m-value">${n(left)}</span>
        <span class="m-sub">${n(now.records)} ${now.records === 1 ? 'case' : 'cases'} in the list · ${n(now.reviewed)} decided</span>
        ${meter(now.reviewed, now.records)}
        <div class="m-foot">${lanes && now.records ? `<p>${left ? 'Cases are grouped by FSU and household, so one visit or call can settle several.' : `Every “${esc(nowLabel)}” case has a decision. Continue with “${esc(laterLabel)}”.`}</p>
          <a class="btn cta" href="${startHref}">${left ? 'Start reviewing' : `Open “${esc(laterLabel)}”`}</a>`
          : `<p>${lanes ? 'No case is in this list.' : 'Decisions are recorded on current-method runs.'}</p>`}</div>
      </div>
      ${metric({ dot: 'amber', label: lanes ? laterLabel : 'High priority', value: n(later.records), sub: `${n(later.reviewed)} decided · review when possible`, href: lanes ? '#/cases?tier=B' : '#/cases' })}
      ${metric({ dot: 'violet', label: 'FSU group alerts', value: n(alertFsus), sub: 'context about whole FSUs', href: '#/groups' })}
      ${metric({ label: 'Records in batch', value: n(o.records_processed), sub: lanes ? `${n(o.household_rule_cases ?? 0)} ${o.household_rule_cases === 1 ? 'household breaks' : 'households break'} a rule${o.aggregate_alerts == null ? '' : ` · ${n(o.aggregate_alerts)} unusual area ${o.aggregate_alerts === 1 ? 'change' : 'changes'}`}` : 'all records of the run', href: '#/cases' })}
      ${metric({ dot: 'green', label: 'Decided so far', value: n(r.decided), sub: `${n(r.opened_without_decision || 0)} opened without a decision`, href: '#/reviewed' })}
    </section>
    <div class="ov-grid">
      <div>
        <div class="panel">${panelHead(`Why cases are in ${lanes ? '“Check now”' : 'the highest group'}`, 'alert', '<span class="small muted">a case can have more than one reason</span>')}
          ${table(['Reason', '', { label: 'Cases', num: true }], Object.entries(reasons).filter(([, v]) => v > 0).map(([k, v]) =>
            `<tr><td><a href="#/cases?lane=${esc(k.toUpperCase())}&tier=A">${esc(S.labels.lanes[k.toUpperCase()] || k)}</a></td><td class="barcell">${bar(v, maxReason, 'red')}</td><td class="num">${n(v)}</td></tr>`), { empty: 'No case is in this group.' })}</div>
        <div class="panel">${panelHead(`Where the ${lanes ? '“Check now”' : 'highest-priority'} cases are`, 'map', '<span class="small muted">top 10 States/UTs</span>')}
          ${table(['State/UT', '', { label: 'Cases', num: true }, { label: 'Records', num: true }], states.map(s =>
            `<tr><td><a href="#/worklist?state=${esc(s.state)}">${esc(s.label)}</a></td><td class="barcell">${bar(s.highest, maxState)}</td><td class="num">${n(s.highest)}</td><td class="num">${n(s.records)}</td></tr>`))}
        </div>
      </div>
      <div>
        <div class="panel">${panelHead('Decisions', 'check', '<a class="small" href="#/reviewed">All decisions</a>')}
          ${table(['Decision', { label: 'Cases', num: true }], Object.entries(r.decisions).map(([k, v]) => `<tr><td>${decisionChip(k)}</td><td class="num">${n(v)}</td></tr>`))}
          ${rev.rows.length ? `<h3>Most recent</h3>${table(['Case', 'By', 'When'], rev.rows.slice(0, 5).map(x =>
            `<tr><td><a href="#/case/${encodeURIComponent(x.case_id)}">${esc(x.record_label)}</a><div>${decisionChip(x.decision)}</div></td><td>${esc(x.actor)}${x.actor_verified ? '' : ' <span class="small muted">(unverified)</span>'}</td><td class="small">${esc(when(x.decided_at_utc))}</td></tr>`))}` : ''}
        </div>
        <div class="panel violet">${panelHead('Strongest group alerts', 'group', '<a class="small" href="#/groups">All</a>')}
          ${table(['FSU', 'What differs'], grp.rows.map(g => `<tr><td><a href="#/group/${encodeURIComponent(g.fsu)}?state=${encodeURIComponent(g.state)}">${esc(g.fsu)}</a><div class="small muted">${esc(g.location_label)}</div></td><td>${esc(g.patterns?.[0]?.text || g.strongest_statement || '')}</td></tr>`), { empty: 'No FSU-level group alert.' })}
          <p class="small">Group alerts describe an FSU as a whole. They do not mean that any person's answers are wrong and never move a case in the list.</p></div>
      </div>
    </div>
    ${lanes ? `<details class="panel legend-panel"><summary>How to read the lists and the review budget</summary><div class="readguide">
      <div>${chip(S.labels.bands.CHECK_NOW, 'red')}<p>Review first: a questionnaire rule is not met, or the evidence is rare enough to fit this batch's review budget.</p></div>
      <div>${chip(S.labels.bands.CHECK_IF_TIME, 'amber')}<p>Review when possible: soft checks and evidence that is weaker or did not fit the budget.</p></div>
      <div>${chip('FSU group alert', 'violet')}<p>Context about a whole FSU. Never proof about a person, and never moves a case.</p></div>
      <div>${chip(S.labels.bands.NOT_FLAGGED)}<p>No current alert. Unusual is not the same as wrong, and not flagged is not a guarantee.</p></div></div>
      <div class="budget-note">${icon('info')}<div><b>Review budget for this batch:</b> ${n(budget.budget_cases)} cases (${((budget.review_budget_share || 0) * 100).toFixed(1)}% of records — default until HSD sets supervisor capacity),
      of which up to ${n(budget.coding_budget)} occupation-code checks; at most ${n(budget.per_fsu_cap)} value checks per FSU in “Check now”.
      A case is in “Check now” only if its evidence is rare enough; a quiet batch gives a shorter list.</div></div></details>` : ''}
    ${lanes && burden.value_threshold ? `<details class="panel"><summary>Calibration check on this batch (technical)</summary>
      <p>Released PLFS files are post-scrutiny. If the evidence is calibrated, the share of records whose value check is at or below the threshold should be close to the nominal rate.</p>
      ${kv([{ label: 'Value-check threshold (tail probability)', value: burden.value_threshold },
            { label: 'Nominal alerts per 1,000 records if all were clean', value: Number(burden.nominal_value_alerts_per_1000_if_all_clean).toFixed(2) },
            { label: 'Observed alerts per 1,000 records', value: Number(burden.observed_value_alerts_per_1000).toFixed(2) },
            { label: 'Highest / median State “Check now” rate', value: burden.check_now_state_rate_max_over_median == null ? '—' : Number(burden.check_now_state_rate_max_over_median).toFixed(2) }])}
      <p class="small muted">${esc(burden.note || '')} This is a structural check, not a validation against confirmed errors.</p></details>` : ''}`;
}

/* ------------------------------------------------------------ worklist: by FSU and household */

async function worklist(_, params) {
  crumbs(['Worklist']);
  if (!isLanes()) { app.innerHTML = `${supersededBanner()}${pageHead({ eyebrow: 'Review', title: 'Worklist by FSU' })}<div class="panel">The worklist is available for current-method runs only.</div>`; return; }
  const f = { state: params.get('state') || '', district: params.get('district') || '', tier: params.get('tier') || 'A' };
  const page = Number(params.get('page') || 1);
  const data = await api(url('/api/worklist', { run: S.run, ...f, offset: (page - 1) * 20, limit: 20 }));
  const states = Object.entries(S.labels.states).map(([c, l]) => `<option value="${c}" ${f.state === c ? 'selected' : ''}>${esc(l)}</option>`).join('');
  const tierName = { A: 'Check now', B: 'Check if time', AB: 'Check now and Check if time' }[f.tier] || f.tier;
  app.innerHTML = `${pageHead({ eyebrow: 'Review', title: 'Worklist by FSU',
      lede: 'Cases are grouped by FSU and household, because verification is done per household visit or call. FSUs are in queue order.' })}
    <form class="filters toolbar" id="wf">
      <label>List <select name="tier"><option value="A" ${f.tier === 'A' ? 'selected' : ''}>Check now</option><option value="B" ${f.tier === 'B' ? 'selected' : ''}>Check if time</option><option value="AB" ${f.tier === 'AB' ? 'selected' : ''}>Both</option></select></label>
      <label>State/UT <select name="state"><option value="">All</option>${states}</select></label>
      <label>District code <input name="district" value="${esc(f.district)}" size="6" inputmode="numeric"></label>
      <div class="actions"><button>Show</button></div></form>
    <div class="result-head"><span class="count">${n(data.total)} ${data.total === 1 ? 'FSU' : 'FSUs'} with cases <span>· ${esc(tierName)}${data.total > 20 ? ` · page ${page} of ${Math.ceil(data.total / 20)}` : ''}</span></span></div>
    ${data.rows.map(g => `<div class="panel fsu-card">
      <div class="fsu-head"><div>
        <div class="fsu-title"><b>FSU ${esc(g.fsu)}</b>${g.fsu_alert ? chip('FSU group alert (context)', 'violet') : ''}</div>
        <div class="fsu-meta"><span>${esc(g.location_label)}</span><span>${n(g.cases)} ${g.cases === 1 ? 'case' : 'cases'} · ${n(g.decided)} decided</span>
          <span class="fsu-progress">${meter(g.decided, g.cases)}</span></div></div>
        <a href="#/group/${encodeURIComponent(g.fsu)}?state=${encodeURIComponent(g.state)}" class="btn secondary">About this FSU</a></div>
      ${g.households.map(h => `<div class="hh"><div class="hh-title">Household ${esc(h.household)}</div>
        ${table([{ label: '#', num: true }, 'Case', 'Why it is listed', 'Status', ''], h.cases.map(c => `<tr class="${c.review_status !== 'UNREVIEWED' ? 'done' : ''}">
          <td class="num">${n(c.queue_position)}</td><td>${c.case_level === 'HOUSEHOLD' ? 'Whole household' : `Person ${esc(String(c.source_observation_id).split('|person=')[1] || '')}`}</td>
          <td>${laneChips(c)} ${esc(c.tier_reason || '')}</td><td>${decisionChip(c.review_status)}</td>
          <td class="num"><a href="#/case/${encodeURIComponent(c.case_id)}?from=worklist">${c.review_status === 'UNREVIEWED' ? 'Review' : 'Open'}</a></td></tr>`))}</div>`).join('')}
    </div>`).join('') || empty('No cases in this list.')}
    ${pager(page > 1 ? `<a class="btn secondary" href="#/worklist?${new URLSearchParams({ ...f, page: page - 1 })}">Previous</a>` : '',
      page * 20 < data.total ? `<a class="btn secondary" href="#/worklist?${new URLSearchParams({ ...f, page: page + 1 })}">Next</a>` : '')}`;
  document.querySelector('#wf').onsubmit = e => { e.preventDefault(); go(`#/worklist?${new URLSearchParams(Object.fromEntries(new FormData(e.target)))}`); };
}

/* ------------------------------------------------------------ all cases */

const CASE_FILTERS = ['tier', 'lane', 'case_level', 'state', 'sector', 'review_status', 'q', 'priority_band', 'fsu'];
async function cases(_, params) {
  crumbs(['All cases']);
  if ([...params.keys()].length) { S.filters = Object.fromEntries(CASE_FILTERS.map(k => [k, params.get(k) || ''])); S.page = Number(params.get('page') || 1); }
  const f = S.filters;
  const data = await api(url('/api/cases', { run: S.run, ...f, offset: (S.page - 1) * PAGE_SIZE, limit: PAGE_SIZE, summaries: true }));
  const opt = (name, values) => values.map(([v, l]) => `<option value="${esc(v)}" ${f[name] === v ? 'selected' : ''}>${esc(l)}</option>`).join('');
  const lanes = isLanes();
  const states = [['', 'All'], ...Object.entries(S.labels.states)];
  const pages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
  app.innerHTML = `${supersededBanner()}${pageHead({ eyebrow: 'Review', title: 'All cases',
      lede: 'Every case of the selected run in queue order. Filter by list, reason, area or review status, or search for an FSU or record.' })}
    <form class="filters toolbar" id="cf">
      ${lanes ? `<label>List <select name="tier">${opt('tier', [['', 'All'], ['A', 'Check now'], ['B', 'Check if time'], ['NONE', 'Not flagged'], ['NOT_ASSESSABLE', 'No check possible']])}</select></label>
      <label>Reason <select name="lane">${opt('lane', [['', 'Any'], ...Object.entries(S.labels.lanes)])}</select></label>
      <label>Level <select name="case_level">${opt('case_level', [['', 'All'], ['PERSON', 'Person'], ['HOUSEHOLD', 'Household']])}</select></label>`
      : `<label>Priority <select name="priority_band">${opt('priority_band', [['', 'All'], ['CRITICAL', 'Highest'], ['HIGH', 'High'], ['MEDIUM', 'Medium'], ['LOW', 'Low']])}</select></label>`}
      <label>State/UT <select name="state">${opt('state', states)}</select></label>
      <label>Sector <select name="sector">${opt('sector', [['', 'All'], ['1', 'Rural'], ['2', 'Urban']])}</select></label>
      <label>Review <select name="review_status">${opt('review_status', [['', 'All'], ['UNREVIEWED', 'Not yet reviewed'], ['REVIEWED', 'Reviewed'], ...Object.entries(S.labels.decisions).filter(([k]) => k !== 'UNREVIEWED')])}</select></label>
      <label>FSU <input name="fsu" value="${esc(f.fsu || '')}" size="7"></label>
      <label class="grow">Search <input name="q" value="${esc(f.q || '')}" placeholder="FSU, case or record key" type="search"></label>
      <div class="actions"><button>Apply</button></div></form>
    <div class="result-head"><span class="count">${n(data.total)} ${data.total === 1 ? 'case' : 'cases'} <span>· in queue order · page ${S.page} of ${pages}</span></span>
      ${S.deploy.audit_writable ? `<a class="btn secondary" href="${url('/api/export/queue', { run: S.run, ...f })}" id="export">Export CSV</a>`
        : '<span class="small muted" title="Exports are logged in the audit trail, which is read-only on this instance.">CSV export is not available on this instance</span>'}</div>
    ${table([{ label: '#', num: true }, 'List', 'Reason', 'Finding', 'Area', 'Record', 'Status'], data.rows.map(r => `<tr class="${r.review_status !== 'UNREVIEWED' ? 'done' : ''}">
      <td class="num">${n(r.position)}</td><td>${bandChip(r.priority_band)}</td><td>${laneChips(r)}</td>
      <td><a href="#/case/${encodeURIComponent(r.case_id)}?pos=${r.position}">${esc(r.unusual || '')}</a>${(r.why || []).map(w => `<div class="small muted">${esc(w)}</div>`).join('')}</td>
      <td>${esc(r.location_label || '')}</td><td class="small">${esc(r.record_label || '')}</td><td>${decisionChip(r.review_status)}</td></tr>`), { empty: 'No cases match these filters.' })}
    ${pager(S.page > 1 ? '<button class="secondary" id="prev">Previous</button>' : '',
      S.page * PAGE_SIZE < data.total ? '<button class="secondary" id="next">Next</button>' : '', `Page ${S.page} of ${pages}`)}`;
  const reload = () => go(`#/cases?${new URLSearchParams({ ...Object.fromEntries(Object.entries(S.filters).filter(([, v]) => v)), page: S.page })}`);
  document.querySelector('#cf').onsubmit = e => { e.preventDefault(); S.filters = Object.fromEntries(new FormData(e.target)); S.page = 1; reload(); };
  document.querySelector('#prev')?.addEventListener('click', () => { S.page -= 1; reload(); });
  document.querySelector('#next')?.addEventListener('click', () => { S.page += 1; reload(); });
  const exportLink = document.querySelector('#export');
  if (exportLink) exportLink.onclick = async e => {
    if (!authToken()) return;   // without sign-in the plain link works
    e.preventDefault();
    const r = await fetch(e.target.href, { headers: { Authorization: `Bearer ${authToken()}` } });
    if (!r.ok) { notice('Your role cannot export case lists.', 'error'); return; }
    const blob = await r.blob(); const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'mospi-review-queue.csv'; a.click();
  };
}

/* ------------------------------------------------------------ case page */

function comparisonHtml(c) {
  const strength = c.strength ? ` ${chip(c.strength.label, c.strength.level === 'very' || c.strength.level === 'high' ? 'red' : c.strength.level === 'some' ? 'amber' : '')}` : '';
  return `<div class="cmp"><b>${esc(c.title)}</b>${strength}<p>${esc(c.text)}</p>${c.facts?.length ? kv(c.facts) : ''}</div>`;
}
function sectionHtml(s) {
  if (s.source === 'value') {
    return `<div class="panel evidence ${s.lead ? 'red' : ''}"><h3>${esc(s.title)} ${chip(s.strength.label + (s.strength.plain ? ` — ${s.strength.plain}` : ''), s.strength.level === 'very' || s.strength.level === 'high' ? 'red' : s.strength.level === 'some' ? 'amber' : '')}</h3>
      <div class="recorded"><span class="lbl">Recorded</span><span class="val">${esc(s.observed)}</span></div>${(s.comparisons || []).map(comparisonHtml).join('')}
      ${s.hints?.length ? `<p><b>Possible recording slips to check:</b></p><ul class="checks">${s.hints.map(h => `<li>${esc(h)}</li>`).join('')}</ul>` : ''}${tech(s.technical)}</div>`;
  }
  if (s.source === 'pattern') return '';   // shown in the FSU block
  return `<div class="panel evidence ${s.source === 'rules' ? 'red' : ''}"><h3>${esc(s.title)} ${s.strength ? chip(s.strength.label, s.source === 'rules' ? 'red' : '') : ''}</h3>
    ${s.observed ? `<div class="recorded"><span class="lbl">Recorded</span><span class="val">${esc(s.observed)}</span></div>` : ''}${s.comparison ? `<p>${esc(s.comparison)}</p>` : ''}
    ${s.facts?.length ? kv(s.facts) : ''}${s.meaning ? `<p>${esc(s.meaning)}</p>` : ''}${s.matters ? `<p class="small muted">${esc(s.matters)}</p>` : ''}${tech(s.technical)}</div>`;
}
function groupHtml(g, fsu, state) {
  if (!g) return '';
  return `<div class="panel violet"><h3>${esc(g.title)} ${chip(g.strength.label, 'violet')}</h3>
    ${g.observed ? `<p>${esc(g.observed)}</p>` : ''}${(g.items || []).map(i => `<p>• ${esc(i.text)}</p>`).join('')}
    <p><b>${esc(g.meaning)}</b></p><a class="small" href="#/group/${encodeURIComponent(fsu)}?state=${encodeURIComponent(state)}">About this FSU</a>${tech(g.technical)}</div>`;
}
function decisionForm(d) {
  const options = obj => Object.entries(obj).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join('');
  return `<form class="decision" id="decide">
    <label>Decision <select name="decision" required><option value="">Choose…</option>${options(Object.fromEntries(Object.entries(S.labels.decisions).filter(([k]) => k !== 'UNREVIEWED')))}</select></label>
    <label>Reason <select name="reason_code" required><option value="">Choose a decision first</option></select></label>
    <label>How it was verified <select name="verification_source" required><option value="">Choose…</option>${options(S.labels.verification_sources)}</select></label>
    <div id="corr" class="hidden"><label>Item corrected <input name="corrected_field" maxlength="200" placeholder="e.g. salaried earnings"></label>
      <label>Correct value (if known) <input name="corrected_value" maxlength="200"></label></div>
    <label>Note <textarea name="comment" rows="2" maxlength="2000" placeholder="Optional: what was checked and with whom"></textarea></label>
    <button class="lg block cta">Save decision</button>
    <p class="small muted" id="who">${S.user ? `Saving as ${esc(S.user.name)} (signed in).` : reviewer() ? `Saving as ${esc(reviewer())} — not signed in, so the name is recorded as unverified.` : 'Add your name at the top so the audit trail shows who decided.'}</p>
  </form>`;
}

async function casePage(caseId, params) {
  crumbs(['Case']);
  const opened = new Date().toISOString();
  const d = await api(url(`/api/cases/${encodeURIComponent(caseId)}`, { run: S.run }));
  if (S.deploy.audit_writable) {
    api(url(`/api/cases/${encodeURIComponent(caseId)}/events`, { run: S.run }), { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_type: 'CASE_VIEWED', actor: reviewer() || 'local-supervisor' }) }).catch(() => {});
  }
  // The last decision this page has seen; the server refuses a decision if someone else decided since (no silent overwrite).
  const lastDecision = (d.audit_history || []).filter(e => e.event_type === 'DECISION_MADE').map(e => e.event_id).pop() ?? null;
  const s = d.story || {};
  const pos = Number(params.get('pos') || d.queue_position || 0);
  const lanes = s.method === 'lanes';
  const record = s.record || {};
  const evidence = (s.evidence || []).map(sectionHtml).join('');
  const fromWorklist = params.get('from') === 'worklist';
  app.innerHTML = `${s.superseded_method ? supersededBanner() : ''}
    <a class="back" href="${fromWorklist ? '#/worklist' : '#/cases'}">${icon('back')}${fromWorklist ? 'Worklist by FSU' : 'All cases'}</a>
    <div class="case-head"><div><h1>${esc(record.title || d.case_id)}</h1>
      <div class="case-tags">${lanes ? `${bandChip(d.priority_band)} ${(s.queue?.lanes || []).map(l => chip(l.label, /rule/i.test(l.label) ? 'red' : 'blue')).join('')} <span>· position ${n(d.queue_position)}</span>` : bandChip(d.priority_band)} <span>·</span> ${decisionChip(d.review_status)}</div></div>
      <div class="page-actions">${pos > 1 ? `<button class="secondary" id="prevCase">${icon('back')}Previous case</button>` : ''} ${lanes ? '<button class="secondary jump" id="toDecision">Go to decision</button>' : ''} <button class="secondary" id="nextCase">Next case</button></div></div>
    <div class="panel headline"><span class="stat-badge">${icon('alert')}</span><div><p class="eyebrow" style="margin-bottom:2px">Why this case is listed</p><b>${esc(s.headline || '')}</b>${s.queue?.reason ? `<p class="muted" style="margin:4px 0 0">${esc(s.queue.reason)}</p>` : ''}</div></div>
    <div class="case-cols"><div>
      <div class="panel"><h2>What was recorded</h2>${kv([...(record.location || []), ...(record.survey || [])])}${record.person?.length ? `<h3>${record.level === 'household' ? 'Household' : 'Person'}</h3>${kv(record.person)}` : ''}</div>
      ${evidence}
      ${groupHtml(s.group || (s.evidence || []).find(e => e.source === 'pattern'), d.fsu, d.state)}
      ${s.unavailable?.length ? `<div class="panel"><h2>What could not be checked</h2><ul class="checks">${s.unavailable.map(u => `<li><b>${esc(u.title)}:</b> ${esc(u.text)}</li>`).join('')}</ul></div>` : ''}
      <div class="panel flat tight">${tech({ case: Object.fromEntries(Object.entries(d).filter(([k]) => !['story', 'audit_history', 'evidence_card'].includes(k))), source_runs: s.source_runs }, 'Technical details (stored case fields)')}</div>
    </div><div class="case-side">
      <div class="panel">${panelHead('What to check', 'list')}${s.checks?.length ? `<ul class="checks">${s.checks.map(c => `<li>${esc(c.text)}${c.detail ? `<div class="small muted">${esc(c.detail)}</div>` : ''}</li>`).join('')}</ul>` : empty('No specific check.')}</div>
      <div class="panel decision-panel">${panelHead('Your decision', 'check')}${!lanes ? '<p class="muted">Decisions are recorded on current-method runs.</p>'
        : S.deploy.audit_writable ? decisionForm(d) : `<div class="readonly-note">${infoBox(`<b>Decisions cannot be recorded here.</b> ${esc(S.deploy.audit_reason || '')}`, 'accent')}<span class="small muted">Current status: ${decisionChip(d.review_status)}</span></div>`}</div>
      <div class="panel"><h2>Importance</h2><p>${esc(s.importance?.plain || s.importance?.summary || '')}</p><p class="small muted">${esc(s.importance?.explanation || '')}</p></div>
      <div class="panel"><h2>Audit history</h2>${table(['When', 'What', 'By'], (d.audit_history || []).slice(-10).map(e =>
        `<tr><td class="small">${esc(when(e.event_timestamp_utc))}</td><td>${esc(e.event_type === 'DECISION_MADE' ? `${S.labels.decisions[e.decision] || e.decision}${e.reason_code ? ` — ${S.labels.reason_codes?.[e.decision]?.[e.reason_code] || e.reason_code}` : ''}` : e.event_type === 'CASE_VIEWED' ? 'Opened' : e.event_type)}${e.comment ? `<div class="small muted">${esc(e.comment)}</div>` : ''}</td>
        <td>${esc(e.actor)}${e.actor_authenticated ? '' : ' <span class="small muted">(unverified)</span>'}</td></tr>`), { empty: 'No events yet.' })}</div>
      <p class="small muted">${esc(s.caveat || '')}</p>
    </div></div>`;
  const nextPos = d.review_status === 'UNREVIEWED' && S.filters.review_status === 'UNREVIEWED' ? pos : pos + 1;
  const openPos = async p => {
    const r = await api(url('/api/queue/position', { run: S.run, ...S.filters, position: Math.max(1, p) }));
    if (r.case_id) go(`#/case/${encodeURIComponent(r.case_id)}?pos=${Math.max(1, p)}`); else notice('No more cases in this list.', 'ok');
  };
  document.querySelector('#nextCase').onclick = () => openPos(pos ? nextPos : 1);
  document.querySelector('#prevCase')?.addEventListener('click', () => openPos(pos - 1));
  document.querySelector('#toDecision')?.addEventListener('click', () => document.querySelector('.decision-panel').scrollIntoView({ block: 'start' }));
  const form = document.querySelector('#decide');
  if (!form) return;
  const reasonData = S.labels.reason_codes;
  form.decision.onchange = () => {
    const codes = reasonData[form.decision.value] || {};
    form.reason_code.innerHTML = '<option value="">Choose…</option>' + Object.entries(codes).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join('');
    document.querySelector('#corr').classList.toggle('hidden', form.decision.value !== 'CONFIRMED_ERROR');
  };
  form.onsubmit = async e => {
    e.preventDefault();
    const body = { event_type: 'DECISION_MADE', actor: reviewer() || 'local-supervisor', opened_at_utc: opened, expected_last_decision_id: lastDecision,
      ...Object.fromEntries(new FormData(form)) };
    try {
      await api(url(`/api/cases/${encodeURIComponent(caseId)}/events`, { run: S.run }), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      S.ov = null; S.flash = { text: 'Decision saved to the audit trail.', kind: 'ok' };
      await openPos(pos ? nextPos : 1);
    } catch (err) {
      if (err.status === 409) { S.flash = { text: err.message, kind: 'error' }; route(); return; }   // reload to show the other decision
      notice(err.message, 'error');
    }
  };
}

/* ------------------------------------------------------------ groups */

async function groups(_, params) {
  crumbs(['Group alerts']);
  const page = Number(params.get('page') || 1);
  const band = params.get('band') || 'ALERTS';
  const data = await api(url('/api/groups', { run: S.run, band, offset: (page - 1) * 50, limit: 50 }));
  app.innerHTML = `${supersededBanner()}${pageHead({ eyebrow: 'Context', title: 'Group alerts (FSU)',
      lede: 'FSUs whose answers, taken together, differ clearly from comparable FSUs. Use them as background when reviewing cases — they are not findings about any person.' })}
    <details class="panel violet"><summary>How FSU group alerts are produced</summary>These checks compare each FSU with comparable FSUs of the same State/UT, sector and stratum: the mix of activity status (after allowing for age and sex), typical earnings and hours, age heaping, how much answers vary, interview durations, interview dates, response codes and near-identical answer sets across households. An FSU is an alert when its combined evidence passes a false-discovery-rate control across all FSUs. <b>An alert describes the FSU as a whole; it does not mean any person's answers are wrong, and it is not about an enumerator</b> (no enumerator code exists in the released data).</details>
    ${infoBox('<b>An alert describes the FSU as a whole.</b> It does not mean any person’s answers are wrong and never moves a case in the review list.', 'violet')}
    <form class="filters toolbar" id="gf"><label>Show <select name="band"><option value="ALERTS" ${band === 'ALERTS' ? 'selected' : ''}>FSUs with an alert</option><option value="HIGH" ${band === 'HIGH' ? 'selected' : ''}>Clear difference</option><option value="LOW" ${band === 'LOW' ? 'selected' : ''}>No notable difference</option></select></label><div class="actions"><button>Show</button></div></form>
    <div class="result-head"><span class="count">${n(data.total)} ${data.total === 1 ? 'FSU' : 'FSUs'}${data.total > 50 ? ` <span>· page ${page} of ${Math.ceil(data.total / 50)}</span>` : ''}</span></div>
    ${table(['FSU', 'Area', 'Alert', 'What differs', { label: 'Cases in queue', num: true }], data.rows.map(g =>
      `<tr><td><a href="#/group/${encodeURIComponent(g.fsu)}?state=${encodeURIComponent(g.state)}">${esc(g.fsu)}</a></td><td>${esc(g.location_label)}</td><td>${chip(g.band_label, 'violet')}</td>
       <td>${(g.patterns || []).map(p => `<div>${esc(p.text)}</div>`).join('') || esc(g.strongest_statement || '')}</td><td class="num">${n((g.check_now_cases || 0) + (g.check_if_time_cases || 0))}</td></tr>`))}
    ${pager(page > 1 ? `<a class="btn secondary" href="#/groups?band=${band}&page=${page - 1}">Previous</a>` : '', page * 50 < data.total ? `<a class="btn secondary" href="#/groups?band=${band}&page=${page + 1}">Next</a>` : '')}`;
  document.querySelector('#gf').onsubmit = e => { e.preventDefault(); go(`#/groups?band=${e.target.band.value}`); };
}

async function groupPage(fsu, params) {
  crumbs([`FSU ${fsu}`]);
  const state = params.get('state') || '';
  const [g, list] = await Promise.all([api(url(`/api/groups/${encodeURIComponent(fsu)}`, { run: S.run, state })), api(url('/api/cases', { run: S.run, fsu, state, limit: 100, summaries: true }))]);
  const grp = g.group;
  app.innerHTML = `<a class="back" href="#/groups">${icon('back')}Group alerts (FSU)</a>
    ${pageHead({ eyebrow: 'About this FSU', title: `FSU ${fsu}`, lede: esc(grp.location_label) })}
    <div class="panel violet">${panelHead(grp.band_label, 'group')}
      ${table(['Check', 'Result', 'Strength', 'Basis'], g.patterns.map(p => `<tr><td>${esc(p.title)}</td><td>${esc(p.text)}</td><td>${esc(p.strength.label)}</td><td class="small">${esc(p.basis)}</td></tr>`), { empty: 'No assessable FSU check.' })}
      <p><b>This describes the FSU as a whole. It does not mean that any answer of any person is wrong.</b></p></div>
    <div class="panel">${panelHead('Records of this FSU', 'list', `<span class="small muted">${list.total > list.rows.length ? `first ${n(list.rows.length)} of ${n(list.total)} cases` : `${n(list.rows.length)} ${list.rows.length === 1 ? 'case' : 'cases'}`}</span>`)}
      ${table(['List', 'Reason', 'Finding', 'Record', 'Status'], list.rows.map(r => `<tr><td>${bandChip(r.priority_band)}</td><td>${laneChips(r)}</td>
        <td><a href="#/case/${encodeURIComponent(r.case_id)}">${esc(r.unusual || '')}</a></td><td class="small">${esc(r.record_label || '')}</td><td>${decisionChip(r.review_status)}</td></tr>`))}</div>`;
}

/* ------------------------------------------------------------ areas */

const INDICATOR_UNIT = { lfpr_cws_15plus: 'share', wpr_cws_15plus: 'share', ur_cws_15plus: 'share', median_salaried_earnings: 'rupees', mean_day7_hours_workers: 'hours' };
function indicatorValue(indicator, v) {
  if (v == null) return '—';
  const u = INDICATOR_UNIT[indicator];
  return u === 'share' ? `${(v * 100).toFixed(1)}%` : u === 'rupees' ? money(v) : `${Number(v).toFixed(1)} h`;
}
async function areas(_, params) {
  crumbs(['Area trends']);
  const level = params.get('level') || 'state';
  const indicator = params.get('indicator') || 'ur_cws_15plus';
  const data = await api(url('/api/aggregates', { run: S.run, level, indicator, limit: 5000 }));
  const head = pageHead({ eyebrow: 'Context', title: 'Area trends',
    lede: 'Weighted current-weekly-status indicators from first-visit records, and the period-on-period changes that stand out. Screening values, not official PLFS estimates.' });
  if (!data.available) { app.innerHTML = head + empty('No historical run is attached to this survey round.'); return; }
  const periods = [...new Set(data.rows.map(r => r.period_label))];
  const last = periods[periods.length - 1];
  const rows = data.rows.filter(r => r.period_label === last);
  app.innerHTML = `${head}
    <div class="panel">${panelHead('Unusual period-on-period changes', 'alert', `<span class="small muted">${n(data.notable.length)} ${data.notable.length === 1 ? 'change' : 'changes'}${data.notable.length > 100 ? ' · first 100 shown' : ''}</span>`)}
      <p class="small muted">A change is shown when it stands out from the other areas' changes in the same period <i>and</i> exceeds three standard errors of the change. Changes listed by HSD as known events are marked as expected instead.</p>
      ${table(['Area', 'Indicator', 'Period', { label: 'Before', num: true }, { label: 'Now', num: true }, { label: 'Change / SE', num: true }], data.notable.slice(0, 100).map(a =>
        `<tr><td>${esc(a.area_label)}</td><td>${esc(a.indicator_label)}</td><td>${esc(a.period_label)}</td><td class="num">${esc(indicatorValue(a.indicator, a.previous_value))}</td><td class="num">${esc(indicatorValue(a.indicator, a.value))}</td><td class="num">${a.change_over_design_se == null ? '—' : Number(a.change_over_design_se).toFixed(1)}</td></tr>`), { empty: 'No unusual change.' })}</div>
    <div class="panel">${panelHead(`${(data.indicators.find(i => i.indicator === indicator) || {}).indicator_label || indicator} — ${last || ''}`, 'map')}
      <form class="filters" id="af" style="margin-bottom:14px"><label>Level <select name="level">${['national', 'state', 'district'].map(l => `<option value="${l}" ${l === level ? 'selected' : ''}>${l[0].toUpperCase() + l.slice(1)}</option>`).join('')}</select></label>
        <label>Indicator <select name="indicator">${data.indicators.map(i => `<option value="${esc(i.indicator)}" ${i.indicator === indicator ? 'selected' : ''}>${esc(i.indicator_label)}</option>`).join('')}</select></label><div class="actions"><button>Show</button></div></form>
      ${table(['Area', { label: 'Value', num: true }, { label: 'Design SE', num: true }, { label: 'Design effect', num: true }, { label: 'Change', num: true }, { label: 'Persons 15+', num: true }], rows.map(r =>
        `<tr><td>${esc(r.area_label)}</td><td class="num">${esc(indicatorValue(indicator, r.value))}</td><td class="num">${esc(indicatorValue(indicator, r.design_standard_error ?? r.srs_standard_error))}</td>
         <td class="num">${r.design_effect == null ? '—' : Number(r.design_effect).toFixed(2)}</td><td class="num">${r.change == null ? '—' : esc(indicatorValue(indicator, r.change))}</td><td class="num">${n(r.persons_15plus)}</td></tr>`))}
      <p class="small muted">Standard errors are design-based (FSU as primary sampling unit within strata).</p>
      ${(data.limitations || []).map(l => `<p class="small muted">${esc(l)}</p>`).join('')}</div>`;
  document.querySelector('#af').onsubmit = e => { e.preventDefault(); go(`#/areas?${new URLSearchParams(Object.fromEntries(new FormData(e.target)))}`); };
}

/* ------------------------------------------------------------ decisions */

async function reviewed(_, params) {
  crumbs(['Decisions']);
  const decision = params.get('decision') || '';
  const data = await api(url('/api/reviews', { run: S.run, decision }));
  app.innerHTML = `${pageHead({ eyebrow: 'Audit trail', title: 'Decisions',
      lede: 'Every decision recorded for the selected run, newest first. Decisions are appended to a hash-chained audit trail and never overwrite survey data.' })}
    <form class="filters toolbar" id="rf"><label>Decision <select name="decision"><option value="">All</option>${Object.entries(S.labels.decisions).filter(([k]) => k !== 'UNREVIEWED').map(([k, v]) => `<option value="${k}" ${k === decision ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></label><div class="actions"><button>Show</button></div></form>
    <div class="result-head"><span class="count">${n(data.rows.length)} ${data.rows.length === 1 ? 'decision' : 'decisions'}</span></div>
    ${table(['Case', 'Area', 'Decision', 'Reason', 'Verified by', 'Correction', 'By', 'When', { label: 'Minutes on case', num: true }], data.rows.map(x =>
      `<tr><td><a href="#/case/${encodeURIComponent(x.case_id)}">${esc(x.record_label)}</a></td><td>${esc(x.location_label)}</td><td>${decisionChip(x.decision)}</td><td>${esc(x.reason_label || '')}${x.comment ? `<div class="small muted">${esc(x.comment)}</div>` : ''}</td>
       <td>${esc(S.labels.verification_sources[x.verification_source] || x.verification_source || '')}</td><td>${esc([x.corrected_field, x.corrected_value].filter(Boolean).join(': '))}</td>
       <td>${esc(x.actor)}${x.actor_verified ? '' : ' <span class="small muted">(unverified)</span>'}</td><td class="small">${esc(when(x.decided_at_utc))}</td><td class="num">${x.seconds_on_case == null ? '—' : (x.seconds_on_case / 60).toFixed(1)}</td></tr>`), { empty: 'No decisions recorded.' })}`;
  document.querySelector('#rf').onsubmit = e => { e.preventDefault(); go(`#/reviewed?decision=${e.target.decision.value}`); };
}

/* ------------------------------------------------------------ technical reference */

const DESIGN_LABEL = { D_value_lane: 'Full value check (current method)', E6_operational_queue: 'Review list order (current method)', A0_superseded_v2_0: 'Superseded V2.0 priority',
  E1_current_peers: 'Current comparable people only', E2_earlier_periods: 'Earlier periods only', E4_expected_value_model: 'Expected-value model only',
  B_references_only: 'Current + earlier references', E3_coding_lane: 'Occupation coding check' };
function evaluationHtml(evaluation) {
  const runs = evaluation.protocol_v1 || [];
  const pc = v => (v == null ? '—' : `${(v * 100).toFixed(1)}%`);
  const intro = `<p>Controlled-injection evaluation (evaluation/PROTOCOL.md): known errors are inserted into a copy of the released data and each method's list is scored on the records that CAPI rules would pass. Injected errors are stylised, so these figures are necessary evidence, not proof of real-world accuracy.</p>`;
  if (!runs.length) return `${intro}<p>The current method has <b>not been evaluated yet</b>.</p>${evaluation.available ? tech(evaluation.results, 'Stored results (superseded method)') : ''}`;
  const names = Object.keys(DESIGN_LABEL).filter(k => runs.some(r => r.recall_at_1pct[k] != null));
  const confirmation = runs.filter(r => r.kind === 'confirmation').length;
  return `${intro}<p>${n(runs.length)} run(s): ${n(runs.length - confirmation)} development, ${n(confirmation)} confirmation (the protocol asks for 15 confirmation seeds per release). Share of injected errors found in the top 1% of records:</p>
    ${table(['Method', ...runs.map(r => `${String(r.release).replace('_', '–')} · ${r.kind} · seed ${r.seed}`)], names.map(k => `<tr><td>${esc(DESIGN_LABEL[k])}</td>${runs.map(r => `<td class="num">${pc(r.recall_at_1pct[k])}</td>`).join('')}</tr>`))}
    ${tech(runs, 'Technical details (paired differences, FSU level, rule list)')}${evaluation.available ? tech(evaluation.results, 'Stored results (superseded method)') : ''}`;
}

async function technical() {
  crumbs(['Technical reference']);
  const [summary, integrity, feedback, chain, evaluation] = await Promise.all([api(url('/api/summary', { run: S.run })), api(url('/api/integrity', { run: S.run })),
    api(url('/api/feedback', { run: S.run })).catch(() => ({ available: false })), api(url('/api/audit/verify', { run: S.run })), api('/api/evaluation')]);
  const m = summary.metadata, rep = summary.report;
  app.innerHTML = `${pageHead({ eyebrow: 'For technical staff', title: 'Technical reference',
      lede: 'Run provenance, audit-trail integrity, questionnaire rules, evaluation results and a single-record check. Not needed for everyday review.' })}
    <div class="panel"><h2>Run and method</h2>${kv([{ label: 'Fusion run', value: summary.run }, { label: 'Method', value: m.fusion_version },
      { label: 'Preparation run', value: m.input_preprocessing_run_id }, ...Object.entries(m.source_runs || {}).map(([k, v]) => ({ label: `${k} run`, value: v }))])}
      ${tech(m.parameters, 'Parameters')}${tech(rep, 'Run report')}</div>
    <div class="grid2">
      <div class="panel"><h2>Audit trail</h2><p>Hash chain: ${chip(chain.status, chain.status === 'INTACT' ? 'green' : chain.status === 'BROKEN' ? 'red' : '')} · ${n(chain.events)} events${chain.first_bad_event_id ? ` · first inconsistent event ${n(chain.first_bad_event_id)}` : ''}</p>
        <p class="small muted">Each event carries the hash of the previous one; edits, insertions or deletions break the chain. Updates and deletions are also refused by the database.</p></div>
      <div class="panel"><h2>Feedback from decisions</h2>${feedback.available ? `${table(['Reason', 'List', { label: 'Decided', num: true }, { label: 'Confirmed errors', num: true }, 'Share (95% CI)', 'Proposal'], (feedback.by_lane_and_tier || []).map(g =>
        `<tr><td>${esc(S.labels.lanes[g.lane] || g.lane)}</td><td>${esc(g.tier)}</td><td class="num">${n(g.decided)}</td><td class="num">${n(g.confirmed_error)}</td>
         <td>${g.confirmed_share_of_resolved == null ? '—' : `${(g.confirmed_share_of_resolved * 100).toFixed(0)}% (${(g.confirmed_share_ci95[0] * 100).toFixed(0)}–${(g.confirmed_share_ci95[1] * 100).toFixed(0)}%)`}</td><td class="small">${esc(g.proposal || '')}</td></tr>`), { empty: 'No decisions yet.' })}
        <p class="small muted">${esc(feedback.note || '')}</p>` : empty(feedback.reason || 'Not available.')}</div>
    </div>
    <div class="panel"><h2>Integrity rules</h2>${integrity.available ? `<p>Rule set ${esc(integrity.rule_set_version)} · ${n(integrity.records_checked)} persons and ${n(integrity.households_checked)} households checked.</p>
      ${table(['Rule', 'Level', 'Type', 'Severity', 'Status', 'Source'], (integrity.rules || []).map(r => `<tr><td>${esc(r.id)} v${esc(r.version)}</td><td>${esc(r.level || 'person')}</td><td>${esc(r.type)}</td><td>${esc(r.severity)}</td>
        <td>${esc(r.approval_status || 'approved')}${r.active === false ? ' (inactive)' : ''}</td><td class="small">${esc(r.source)}</td></tr>`))}` : empty('No integrity run.')}</div>
    <div class="panel"><h2>Evaluation</h2>${evaluationHtml(evaluation)}</div>
    <div class="panel"><h2>Check one submitted record</h2><p class="small muted">Checks documented rules and the stored comparison groups; nothing is stored.</p>
      <form class="filters" id="vf">${['cws_status', 'age', 'state', 'sector', 'earnings_salaried', 'earnings_self_employed', 'day7_hours', 'occupation_code', 'education', 'industry_code'].map(k => `<label>${k}<input name="${k}" size="9"></label>`).join('')}<button>Check</button></form>
      <div id="vr"></div></div>`;
  document.querySelector('#vf').onsubmit = async e => {
    e.preventDefault();
    const record = Object.fromEntries([...new FormData(e.target)].filter(([, v]) => v !== ''));
    const result = await api(url('/api/validate/record', { run: S.run }), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ record }) });
    document.querySelector('#vr').innerHTML = `<pre>${esc(JSON.stringify(result, null, 2))}</pre>`;
  };
}

/* ------------------------------------------------------------ batch validation */

const JOB_CHIP = { COMPLETED: 'green', RUNNING: 'blue', STARTING: 'blue', FAILED: 'red', FAILED_QA_GATE: 'red', INTERRUPTED: 'amber' };
const JOB_LABEL = { COMPLETED: 'Completed', RUNNING: 'Running', STARTING: 'Starting', FAILED: 'Failed', FAILED_QA_GATE: 'Stopped by a quality check', INTERRUPTED: 'Interrupted' };
const STAGE_LABEL = { peer: 'Comparison groups', statistical: 'Current-round comparison', contextual: 'Occupation coding', ml: 'Expected-value models', pattern: 'FSU patterns',
  historical: 'Earlier-period comparison', integrity: 'Questionnaire rules', fusion: 'Review list' };
const jobChip = s => chip(JOB_LABEL[s] || s, JOB_CHIP[s] || '');
const duration = (a, b) => { const s = (new Date(b || Date.now()) - new Date(a)) / 1000; return Number.isFinite(s) ? (s < 90 ? `${Math.round(s)} s` : `${Math.round(s / 60)} min`) : '—'; };
const roundName = r => `PLFS ${String(r).replace('_', '–')}`;
let batchTimer = null;
function stopBatchTimer() { if (batchTimer) { clearTimeout(batchTimer); batchTimer = null; } }

async function openRun(directory, page = 'overview') {
  S.runs = await api('/api/runs');
  runSelect.innerHTML = S.runs.map(r => `<option value="${esc(r.directory)}" ${r.directory === directory ? 'selected' : ''}>${esc(runLabel(r))}</option>`).join('');
  S.run = directory; S.filters = {}; S.page = 1; S.ov = null; store.set('l:MoSPI.run', S.run);
  go(`#/${page}`);
}

async function batch() {
  crumbs(['Batch validation']);
  if (S.deploy.review_only) { batchReviewOnly(); return; }
  const [info, list] = await Promise.all([api('/api/batch/inputs'), api('/api/batch')]);
  const available = info.inputs.filter(i => i.available);
  const active = list.jobs.find(j => ['STARTING', 'RUNNING'].includes(j.status));
  const step = (k, title) => `<div class="panel-head"><h2><span class="step-num">${k}</span>${esc(title)}</h2></div>`;
  app.innerHTML = `${pageHead({ eyebrow: 'Operations', title: 'Batch validation',
      lede: 'Runs every validation check on a prepared survey delivery and produces a new review list. Earlier runs and their decisions are kept unchanged.' })}
    ${active ? `<div class="callout"><div class="txt"><b>A batch is running: ${esc(roundName(active.release))} · ${esc(active.label)}</b><span>This page refreshes every 5 seconds. You can leave and come back.</span></div><a class="btn lg" href="#/batch/${active.job_id}">Follow progress</a></div>` : ''}
    <div class="panel">${step(1, 'Survey data available on this server')}
      ${table(['Survey round', 'Data file', { label: 'Persons', num: true }, 'Compared with', 'Runs already made', 'Available'], info.inputs.map(i =>
        `<tr><td>${esc(roundName(i.release))}${i.includes_revisit ? ' <span class="small muted">(with revisit)</span>' : ''}</td><td class="small">${esc(i.preparation_run)}/${esc(i.prepared_file)}</td>
         <td class="num">${n(i.records)}</td><td>${i.history_releases ? 'previous release and earlier periods' : 'earlier periods of the same round'}</td>
         <td class="small">${esc((i.existing_labels || []).join(', ') || '—')}</td><td>${i.available ? chip('Yes', 'green') : `${chip('No', 'amber')} <span class="small muted">${esc(i.reason || '')}</span>`}</td></tr>`))}
      ${infoBox(`<b>Uploading files from the browser is not available.</b> ${esc(info.upload.reason)}`)}</div>
    <div class="panel">${step(2, 'Start a batch')}
      ${!info.can_start ? infoBox('Only an administrator can start a batch validation. You can follow the progress of batches below.', 'amber')
        : active ? `<p>A batch is already running (${esc(roundName(active.release))}, label ${esc(active.label)}). Only one batch runs at a time. <a href="#/batch/${active.job_id}">Follow its progress</a>.</p>`
        : !available.length ? empty('No prepared survey data is available on this server.')
        : `<form id="bf" class="filters">
          <label>Survey round <select name="release" required>${available.map(i => `<option value="${esc(i.release)}">${esc(roundName(i.release))}</option>`).join('')}</select></label>
          <label>Run label <input name="label" required pattern="[a-z0-9][a-z0-9_]{0,23}" size="16" placeholder="e.g. oct_2026" title="Lower-case letters, digits and underscores"></label>
          <button id="bstart" class="lg">${icon('play')}Start batch validation</button></form>
          <p class="small muted" style="margin-top:10px">Run label: lower-case letters, digits and underscores (up to 24). A full batch takes roughly 15 minutes (2024) to an hour (2025) on this server. This page shows its progress; you can leave and come back.</p>
          <details><summary>Advanced: recompute only some steps (technical staff)</summary>
            <p class="small muted">Reuse the results of an earlier run of the same survey round for every step not ticked here. Use this after a change to one method; the ticked steps are recomputed under the new label.</p>
            <div class="filters"><label>Reuse earlier run <select id="breuse"><option value="">No — run every step</option></select></label></div>
            <div class="checkgrid">${info.stages.map(s => `<label><input type="checkbox" class="bstage" value="${s}" ${['ml', 'fusion'].includes(s) ? 'checked' : ''}> ${esc(STAGE_LABEL[s] || s)}</label>`).join('')}</div></details>`}</div>
    <div class="panel">${step(3, 'Batches')}
      ${table(['Survey round', 'Label', 'Status', 'Started by', 'Started', 'Duration', 'Result'], list.jobs.map(j =>
        `<tr><td>${esc(roundName(j.release))}</td><td><a href="#/batch/${j.job_id}">${esc(j.label)}</a>${j.reuse_label ? ` <span class="small muted">(reuses ${esc(j.reuse_label)})</span>` : ''}</td><td>${jobChip(j.status)}</td>
         <td>${esc(j.actor || '—')}${j.actor_verified ? '' : ' <span class="small muted">(unverified)</span>'}</td><td class="small">${esc(when(j.created_utc))}</td>
         <td>${duration(j.started_utc || j.created_utc, j.finished_utc)}</td>
         <td>${j.status === 'COMPLETED' ? `<button class="secondary" data-open="${esc(j.fusion_run)}">Open review list</button>` : (j.error ? `<a href="#/batch/${j.job_id}">See why</a>` : '')}</td></tr>`), { empty: 'No batch has been started from this workspace yet.' })}</div>`;
  app.querySelectorAll('[data-open]').forEach(b => { b.onclick = () => openRun(b.dataset.open, 'worklist'); });
  stopBatchTimer();
  if (active) batchTimer = setTimeout(() => { if (location.hash === '#/batch') route(); }, 5000);
  const form = document.querySelector('#bf');
  if (!form) return;
  const reuse = document.querySelector('#breuse');
  const fillReuse = () => {
    const chosen = info.inputs.find(i => i.release === form.release.value) || {};
    reuse.innerHTML = '<option value="">No — run every step</option>' + (chosen.existing_labels || []).map(l => `<option value="${esc(l)}">${esc(l)}</option>`).join('');
  };
  form.release.onchange = fillReuse; fillReuse();
  form.onsubmit = async e => {
    e.preventDefault();
    const body = { release: form.release.value, label: form.label.value.trim(), actor: reviewer() };
    if (reuse.value) { body.reuse_label = reuse.value; body.rerun = [...document.querySelectorAll('.bstage:checked')].map(c => c.value); }
    document.querySelector('#bstart').disabled = true;
    try {
      const job = await api('/api/batch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      S.flash = { text: `Batch validation started for ${roundName(job.release)} (label ${job.label}).`, kind: 'ok' };
      go(`#/batch/${job.job_id}`);
    } catch (err) { notice(err.message, 'error'); document.querySelector('#bstart').disabled = false; }
  };
}

function batchReviewOnly() {
  stopBatchTimer();
  app.innerHTML = `${pageHead({ eyebrow: 'Operations', title: 'Batch validation',
      lede: 'Validation runs are performed separately, on the processing machine, and cannot be started from this instance.' })}
    ${infoBox(esc(S.deploy.batch_reason || ''), 'accent')}
    <div class="panel">${panelHead('How a new review list reaches this instance', 'list')}
      <div class="steps-off">
        <div><b>1 · Run the batch</b>An administrator runs the unchanged validation pipeline on the processing machine (Batch validation page of the local workspace, or <code>python -m pipeline.run</code>). Every check and quality gate runs there.</div>
        <div><b>2 · Approve and export</b>The finished run is exported with the serving-data script. Unit-level PLFS results are hosted only with the approval required for that data.</div>
        <div><b>3 · Publish</b>The exported run is deployed to this instance. It then appears in the survey-round selector above; earlier runs stay unchanged.</div>
      </div></div>`;
}

async function batchJob(id) {
  crumbs(['Batch validation', id.slice(0, 8)]);
  if (S.deploy.review_only) { batchReviewOnly(); return; }
  const j = await api(`/api/batch/${encodeURIComponent(id)}`);
  const activeNow = ['STARTING', 'RUNNING'].includes(j.status);
  const timing = Object.entries(j.timing_seconds || {});
  const alerts = j.summary?.fsu_alerts || {};
  // Steps run in this fixed order (pipeline STAGES); while running, the log names the current one.
  const order = Object.keys(STAGE_LABEL);
  const at = order.indexOf(j.current_stage);
  const stageList = activeNow ? `<ol class="stages" aria-label="Progress">${order.map((s, k) =>
    `<li class="${at >= 0 && k < at ? 'done' : k === at ? 'now' : ''}">${esc(STAGE_LABEL[s])}</li>`).join('')}</ol>
    <p class="small muted">${at >= 0 ? `Step ${at + 1} of ${order.length}: ${esc(STAGE_LABEL[j.current_stage])}.` : 'Starting…'} This page refreshes every 5 seconds.</p>` : '';
  app.innerHTML = `<a class="back" href="#/batch">${icon('back')}Batch validation</a>
    <div class="page-head"><div><p class="eyebrow">Batch job</p><h1>${esc(roundName(j.release))} · ${esc(j.label)}</h1><div class="case-tags">${jobChip(j.status)}</div></div></div>
    ${activeNow ? `<div class="panel">${panelHead('Progress', 'clock')}${stageList}</div>` : ''}
    <div class="panel">${kv([{ label: 'Started by', value: `${j.actor || '—'}${j.actor_verified ? '' : ' (unverified)'}` }, { label: 'Requested', value: when(j.created_utc) },
      { label: 'Finished', value: j.finished_utc ? when(j.finished_utc) : '—' }, { label: 'Duration', value: duration(j.started_utc || j.created_utc, j.finished_utc) },
      ...(j.reuse_label ? [{ label: 'Reuses run', value: `${j.reuse_label} (recomputes: ${(j.rerun || []).map(s => STAGE_LABEL[s] || s).join(', ')})` }] : []),
      ...(activeNow ? [{ label: 'Current step', value: STAGE_LABEL[j.current_stage] || j.current_stage || 'starting' }] : [])])}</div>
    ${j.error ? `<div class="panel red"><h2>${j.status === 'FAILED_QA_GATE' ? 'Stopped by a quality check' : 'The batch did not finish'}</h2><p>${esc(j.error)}</p>
      <p class="small muted">Nothing was published from this batch. Earlier runs are unaffected.</p></div>` : ''}
    ${j.status === 'COMPLETED' ? `<div class="panel">${panelHead('Result', 'check')}${kv([{ label: 'Persons checked', value: n(j.summary?.records) }, { label: '"Check now" cases', value: n(j.summary?.check_now) },
      { label: 'FSU group alerts', value: n((alerts.HIGH || 0) + (alerts.MEDIUM || 0)) }, { label: 'Quality checks', value: Object.values(j.qa || {}).every(s => s === 'PASSED') ? 'all passed' : JSON.stringify(j.qa) }])}
      <p class="page-actions" style="margin-top:14px"><button data-go="overview">Open dashboard</button> <button class="secondary" data-go="worklist">Open worklist</button> <button class="secondary" data-go="cases">All cases and CSV export</button> <button class="secondary" data-go="groups">FSU group alerts</button></p></div>` : ''}
    ${timing.length ? `<div class="panel"><h2>Steps</h2>${table(['Step', 'Time', 'Quality check'], timing.map(([k, v]) => `<tr><td>${esc(STAGE_LABEL[k] || k)}</td><td>${v === 'reused' ? 'reused from an earlier run' : `${n(v)} s`}</td><td>${esc((j.qa || {})[k] || '—')}</td></tr>`))}</div>` : ''}
    <div class="panel"><details ${j.error ? 'open' : ''}><summary>Technical log (last lines)</summary><pre>${esc((j.log_tail || []).join('\n'))}</pre>${j.traceback ? `<pre>${esc(j.traceback)}</pre>` : ''}</details></div>`;
  app.querySelectorAll('[data-go]').forEach(b => { b.onclick = () => openRun(j.fusion_run, b.dataset.go); });
  stopBatchTimer();
  if (activeNow) batchTimer = setTimeout(() => { if (location.hash === `#/batch/${id}`) route(); }, 5000);
}

/* ------------------------------------------------------------ sign-in and start */

function modebar() {
  const d = S.deploy || {};
  const parts = [];
  if (d.data_notice) parts.push(`<span><i class="tag synthetic">Synthetic data</i>${esc(d.data_notice)}</span>`);
  if (d.review_only) parts.push('<span><i class="tag">Review-only</i>Validation runs are performed separately and cannot be started from this instance.</span>');
  if (d.audit_writable === false) parts.push('<span><b>Decisions are read-only here.</b></span>');
  const el = document.querySelector('#modebar');
  el.innerHTML = parts.length ? `<div class="modebar-row">${parts.join('')}</div>` : '';
  el.classList.toggle('hidden', !parts.length);
  if (d.review_only) { const link = document.querySelector('#nav a[data-route="batch"]'); if (link) link.textContent = 'Batch validation (separate)'; }
  if (d.audit_writable === false && !S.user) {   // nothing is recorded here, so a typed reviewer name has no use
    reviewerInput.closest('.tool').classList.add('hidden');
    document.querySelector('#verified').textContent = 'read-only access';
  }
}

function signIn() {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'signin';
    overlay.innerHTML = `<form><h2>Sign in</h2><p class="small muted">This workspace requires an access token issued by your administrator. It is kept only for this browser session.</p>
      <label>Access token <input type="password" name="token" autocomplete="current-password" required></label><button type="submit">Sign in</button></form>`;
    document.body.appendChild(overlay);
    overlay.querySelector('input').focus();
    overlay.querySelector('form').onsubmit = e => { e.preventDefault(); store.set('s:MoSPI.token', overlay.querySelector('input').value.trim()); overlay.remove(); resolve(); };
  });
}

runSelect.onchange = () => { S.run = runSelect.value; S.filters = {}; S.page = 1; S.ov = null; store.set('l:MoSPI.run', S.run); route(); };
reviewerInput.value = store.get('l:MoSPI.reviewer', '');
reviewerInput.onchange = () => store.set('l:MoSPI.reviewer', reviewer());

(async () => {
  try {
    const required = await fetch('/api/session/required').then(r => r.json()).catch(() => ({ authentication: false }));
    if (required.authentication) {
      if (!authToken()) await signIn();
      S.user = (await api('/api/session')).user;
      if (S.user) { reviewerInput.value = S.user.name; reviewerInput.readOnly = true; document.querySelector('#verified').textContent = `signed in (${S.user.role})`; document.querySelector('#verified').classList.add('ok'); }
    } else {
      document.querySelector('#verified').textContent = 'not signed in: names are recorded as unverified';
    }
    [S.runs, S.labels, S.deploy] = await Promise.all([api('/api/runs'), api('/api/labels'), api('/api/deployment')]);
    modebar();
    if (!S.runs.length) {
      runSelect.innerHTML = '<option>No validation run yet</option>';
      if (S.deploy.review_only) { app.innerHTML = empty('No validation run has been published to this instance yet. Runs are produced on the processing machine and deployed here.'); return; }
      if (!location.hash.startsWith('#/batch')) location.hash = '#/batch';
      else await route();
      return;
    }
    const remembered = store.get('l:MoSPI.run', null);
    S.run = S.runs.some(r => r.directory === remembered) ? remembered : S.runs[0].directory;
    runSelect.innerHTML = S.runs.map(r => `<option value="${esc(r.directory)}" ${r.directory === S.run ? 'selected' : ''}>${esc(runLabel(r))}</option>`).join('');
    await route();
  } catch (e) {
    notice(e.message, 'error');
    app.innerHTML = '<div class="panel">No review list is available yet. A validation run must be created first; this workspace never generates substitute data.</div>';
  }
})();
