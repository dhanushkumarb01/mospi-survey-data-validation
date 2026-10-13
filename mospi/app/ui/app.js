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
const PAGE_SIZE = 50;
const S = { runs: [], run: null, labels: null, filters: {}, page: 1, user: null, caps: [], auth: false, session: {}, ov: null,
  deploy: { review_only: false, audit_writable: true, exports: true, notes_shown: true } };
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

// The session is an HttpOnly cookie this script never sees.  Every request carries the workspace header, which the
// server requires on anything that changes state (a page on another site cannot add it).
const REQUEST_HEADER = { 'X-MoSPI-Request': '1' };
async function api(path, options = {}) {
  const r = await fetch(path, { ...options, headers: { ...REQUEST_HEADER, ...(options.headers || {}) }, credentials: 'same-origin' });
  if (r.status === 401 && S.auth) { await signIn(); return api(path, options); }
  if (!r.ok) {
    let body = {}; try { body = await r.json(); } catch { /* not JSON */ }
    if (r.status === 403 && body.password_change_required) { await changePassword(true); return api(path, options); }
    throw Object.assign(new Error(body.detail || r.statusText), { status: r.status });
  }
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
function reviewer() { return S.user?.name || ''; }
// Capabilities come from /api/session (mospi/auth/roles.py); the server refuses anything a role cannot do either way.
const can = capability => !S.auth || S.caps.includes(capability);
function canDecide() { return can('decide'); }
function runShort(r) { return `PLFS ${String(r.release || '').replace('_', '–')} · ${r.observation === 'first_visit' ? 'first visit' : r.observation}${String(r.fusion_version || '').includes('lanes') ? '' : ' · superseded method'}`; }
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
  chev: '<path d="m9 6 6 6-6 6"/>',
  xcircle: '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/>',
  people: '<circle cx="9" cy="8" r="3.2"/><path d="M3 20c.6-3.4 3-5.2 6-5.2s5.4 1.8 6 5.2"/><path d="M16 5.2a3 3 0 0 1 0 5.7M18 14.9c1.6.7 2.6 2.4 3 5.1"/>',
  db: '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.2a2.5 2.5 0 1 1 3.4 2.4c-.6.3-1 .8-1 1.5v.4M12 17h.01"/>',
  lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  calendar: '<rect x="4" y="5" width="16" height="16" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/>',
  shield: '<path d="M12 3 5 6v5c0 4.4 3 8.3 7 10 4-1.7 7-5.6 7-10V6l-7-3z"/>',
  file: '<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5M10 13h6M10 17h6"/>',
  bars: '<path d="M4 20h16"/><path d="M7 16v-5M12 16V6M17 16v-8"/>',
  trend: '<path d="M3 20h18"/><path d="m4 15 5-5 4 3 7-7"/>',
  spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
};
const icon = name => `<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON_PATHS[name] || ''}</svg>`;
function pageHead({ eyebrow = '', title, lede = '', actions = '' }) {
  return `<div class="page-head"><div>${eyebrow ? `<p class="eyebrow">${esc(eyebrow)}</p>` : ''}<h1>${esc(title)}</h1>${lede ? `<p class="lede">${lede}</p>` : ''}</div>${actions ? `<div class="page-actions">${actions}</div>` : ''}</div>`;
}
const panelHead = (title, iconName = '', right = '') => `<div class="panel-head"><h2>${iconName ? icon(iconName) : ''}${esc(title)}</h2>${right}</div>`;
// Progress ring for a stored share (decided of listed); the number beside it is the same share as text.
const ring = (part, whole, size = 56) => {
  const r = size / 2 - 5, c = 2 * Math.PI * r, share = whole ? Math.min(1, part / whole) : 0;
  return `<svg class="ring" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" role="img" aria-label="${n(part)} of ${n(whole)} decided">
    <circle class="ring-track" cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke-width="6"/>
    <circle class="ring-fill" cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke-width="6" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - share)}" transform="rotate(-90 ${size / 2} ${size / 2})"/>
    <text x="50%" y="50%" text-anchor="middle" dominant-baseline="central">${whole ? `${Math.round(share * 100)}%` : '—'}</text></svg>`;
};
const meter = (part, whole) =>`<div class="meter" role="img" aria-label="${n(part)} of ${n(whole)}"><i style="width:${whole ? Math.min(100, (part / whole) * 100) : 0}%"></i></div>`;
/* Summary card used by the overview and Area trends: tinted icon, label, figure, one line of context.  label is plain
   text (escaped here); value and sub are HTML built by the caller from escaped values. */
function statCard({ tone = '', ic = 'info', label, badge = '', value, sub = '', href = '', extra = '', title = '' }) {
  const tag = href ? 'a' : 'div';
  return `<${tag} class="stat ${tone}"${href ? ` href="${href}"` : ''}${title ? ` title="${esc(title)}"` : ''}>
    <span class="stat-label"><span class="stat-ic">${icon(ic)}</span><span>${esc(label)}</span>${badge}</span>
    <span class="stat-main"><span class="stat-text"><span class="stat-value">${value}</span><span class="stat-sub">${sub}</span></span>${extra}${href ? `<span class="stat-go" aria-hidden="true">${icon('chev')}</span>` : ''}</span></${tag}>`;
}
const infoBox = (html, tone = '') =>`<div class="info ${tone}">${icon('info')}<div>${html}</div></div>`;
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

const routes = { overview, worklist, cases, case: casePage, groups, group: groupPage, areas, reviewed, technical, batch: id => (id ? batchJob(id) : batch()), upload, users };
async function route() {
  const [path, query] = location.hash.replace(/^#\/?/, '').split('?');
  const [name, ...rest] = path.split('/');
  const page = routes[name] ? name : 'overview';
  document.querySelectorAll('#nav a').forEach(a => {
    const on = a.dataset.route === (page === 'case' ? 'cases' : page === 'group' ? 'groups' : page);
    if (page !== 'batch' && page !== 'upload') stopBatchTimer();
    a.classList.toggle('active', on);
    if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  const navEl = document.querySelector('#nav'), activeLink = navEl.querySelector('a.active');   // narrow screens: keep the current page in view
  if (activeLink && navEl.scrollWidth > navEl.clientWidth) navEl.scrollLeft = activeLink.offsetLeft - navEl.offsetLeft - 24;
  notice(S.flash?.text || '', S.flash?.kind || ''); S.flash = null;
  app.innerHTML = '<div class="loading">Loading…</div>';
  vizRedraw = null; hideTip();
  opsbar(page === 'overview');
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

// Plain description of each reason (lane) a case can be listed for; shown next to the stored lane label.
const REASON_HELP = {
  RULE: 'A questionnaire rule is not met.',
  RULE_SOFT: 'A softer questionnaire consistency check is not met.',
  VALUE: 'A reported earnings, wage or hours figure is rare for comparable people.',
  CODING: 'The occupation code is rarely used for comparable records.',
};
const reasonIcon = code => (code === 'CODING' ? 'file' : String(code).startsWith('RULE') ? 'alert' : 'bars');
const DECISION_TILE = { CONFIRMED_ERROR: ['red', 'xcircle'], VALID_BUT_UNUSUAL: ['green', 'check'], NEEDS_FIELD_VERIFICATION: ['amber', 'alert'],
  CANNOT_VERIFY: ['grey', 'help'], ESCALATE: ['blue', 'arrow'] };
// Labelled horizontal bars in HTML (overview lists): each row is a link with its exact value.
function hbarList(items, { tone = '' } = {}) {
  const max = Math.max(1, ...items.map(i => i.value));
  return `<div class="hbars">${items.map(i => `<a class="hbar" href="${i.href}"><span class="hbar-name">${esc(i.label)}</span>
    <span class="hbar-track">${bar(i.value, max, tone)}</span><span class="hbar-val">${n(i.value)}</span>${i.sub != null ? `<span class="hbar-sub">${i.sub}</span>` : ''}</a>`).join('')}</div>`;
}
const headFact = (ic, label, value) => `<div class="head-fact"><span class="head-fact-l">${esc(label)}</span><span class="head-fact-v">${icon(ic)}${value}</span></div>`;

async function overview() {
  crumbs(['Overview']);
  const [o, rev, grp, ops, cube] = await Promise.all([overviewData(true), api(url('/api/reviews', { run: S.run })),
    api(url('/api/groups', { run: S.run, band: 'ALERTS', limit: 5 })).catch(() => ({ rows: [], total: 0 })),
    api('/api/operations').catch(() => null), api(url('/api/case-areas', { run: S.run })).catch(() => null)]);
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
  const alertFsus = (groups.HIGH || 0) + (groups.MEDIUM || 0);
  const left = Math.max(0, (now.records || 0) - (now.reviewed || 0));
  const nowLabel = lanes ? S.labels.bands.CHECK_NOW : 'highest priority';
  const laterLabel = lanes ? S.labels.bands.CHECK_IF_TIME : 'high priority';
  const run = currentRun();
  const startHref = `#/worklist${left ? '' : '?tier=B'}`;
  const listName = lanes ? '“Check now”' : 'the highest group';

  // Operational facts come from the operations store when this instance has one; nothing is shown otherwise.
  const facts = [];
  if (ops?.available) {
    const reg = (ops.runs || []).find(x => x.run_id === S.run);
    const check = ops.last_check;
    facts.push(headFact('db', 'Operational records', ops.database?.reachable ? `PostgreSQL${ops.hosted ? ' (live)' : ''}` : '<span class="bad">unreachable</span>'));
    if (S.run) facts.push(headFact('calendar', reg?.status === 'PUBLISHED' ? 'Published' : 'Registered', reg ? esc(when(reg.published_utc || reg.registered_utc)) : '<span class="warn">not registered</span>'));
    facts.push(headFact('shield', 'Integrity check', check ? (check.status === 'SUCCEEDED' ? `Passed ${esc(when(check.finished_utc || check.created_utc))}` : '<span class="bad">Found problems</span>') : 'None yet'));
  }

  const lead = `<div class="stat lead red">
      <span class="stat-label"><span class="stat-ic">${icon('xcircle')}</span><span>${lanes ? 'Needs a decision' : 'Highest priority, not yet decided'}</span>${lanes ? chip(nowLabel, 'red') : ''}</span>
      <span class="stat-main"><span class="stat-text"><span class="stat-value">${n(left)}</span>
        <span class="stat-sub">${n(now.records)} ${now.records === 1 ? 'case' : 'cases'} in the list · ${n(now.reviewed)} decided</span></span>${now.records ? ring(now.reviewed, now.records, 58) : ''}</span>
      <div class="stat-foot">${lanes && now.records ? `<p>${left ? 'Grouped by FSU and household, so one visit or call can settle several cases.' : `Every “${esc(nowLabel)}” case has a decision.`}</p>
        <a class="btn cta" href="${startHref}">${left ? 'Start reviewing' : `Open “${esc(laterLabel)}”`}${icon('chev')}</a>`
        : `<p>${lanes ? 'No case is in this list.' : 'Decisions are recorded on current-method runs.'}</p><a class="btn secondary" href="#/cases">Open case list</a>`}</div>
    </div>`;

  const reasonRows = Object.entries(reasons).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]).map(([k, v]) => {
    const code = k.toUpperCase();
    return `<a class="reason-row" href="#/cases?lane=${esc(code)}&tier=A"><span class="reason-ic">${icon(reasonIcon(code))}</span>
      <span class="reason-txt"><b>${esc(S.labels.lanes[code] || k)}</b>${REASON_HELP[code] ? `<span>${esc(REASON_HELP[code])}</span>` : ''}</span>
      <span class="reason-num"><b>${n(v)}</b> ${v === 1 ? 'case' : 'cases'}<span>${pct(v, now.records)}</span></span>
      <span class="reason-bar">${bar(v, now.records, 'red')}</span><span class="reason-go" aria-hidden="true">${icon('chev')}</span></a>`;
  }).join('');
  const reasonTotal = Object.values(reasons).reduce((s, v) => s + (v || 0), 0);

  const decisionTiles = Object.entries(r.decisions).map(([k, v]) => {
    const [tone, ic] = DECISION_TILE[k] || ['grey', 'check'];
    return `<a class="dtile ${tone}" href="#/reviewed?decision=${esc(k)}"><span class="dtile-ic">${icon(ic)}</span><span class="dtile-l">${esc(S.labels.decisions[k] || k)}</span><span class="dtile-v">${n(v)}</span></a>`;
  }).join('');

  const hasTrend = lanes && cube?.available && cube.periods?.length > 1;
  app.innerHTML = `${supersededBanner()}
    <div class="page-head ov-head"><div><h1>Overview</h1>
      <p class="lede">${esc(runLabel(run).replace(/ \([^)]*\)$/, ''))}<code class="run-id">${esc(run.directory || '')}</code></p></div>
      ${facts.length ? `<div class="head-facts">${facts.join('')}</div>` : ''}</div>
    <section class="stats ov-stats" aria-label="Review queue">
      ${lead}
      ${statCard({ tone: 'amber', ic: 'clock', label: lanes ? laterLabel : 'High priority', value: n(later.records), sub: `${n(later.reviewed)} decided · review when possible`, href: lanes ? '#/cases?tier=B' : '#/cases' })}
      ${statCard({ tone: 'violet', ic: 'people', label: 'FSU group alerts', value: n(alertFsus), sub: 'Context about whole FSUs', href: '#/groups' })}
      ${statCard({ tone: 'blue', ic: 'db', label: 'Records in batch', value: n(o.records_processed), sub: lanes ? `${n(o.household_rule_cases ?? 0)} ${o.household_rule_cases === 1 ? 'household breaks' : 'households break'} a rule${o.aggregate_alerts == null ? '' : ` · ${n(o.aggregate_alerts)} unusual area ${o.aggregate_alerts === 1 ? 'change' : 'changes'}`}` : 'All records of the run', href: '#/cases' })}
      ${statCard({ tone: 'green', ic: 'check', label: 'Decided so far', value: n(r.decided), sub: `${n(r.opened_without_decision || 0)} opened without a decision`, href: '#/reviewed' })}
    </section>
    <div class="ov-grid">
      <div class="ov-col">
      <div class="panel">${panelHead(`Why cases are in ${listName}`, 'bars', `<span class="small muted">Total cases: <b class="ink">${n(now.records)}</b>${reasonTotal > now.records ? ' · a case can have more than one reason' : ''}</span>`)}
        ${reasonRows ? `<div class="reasons">${reasonRows}</div>` : empty('No case is in this group.')}</div>
      <div class="panel">${panelHead(`Where the ${lanes ? '“Check now”' : 'highest-priority'} cases are`, 'map', `<span class="small muted">Top ${n(states.length)} States/UTs · <a href="#/areas">All areas</a></span>`)}
        ${states.length ? `<div class="hbar-head" aria-hidden="true"><span>State/UT</span><span></span><span>Cases</span><span>Records</span></div>${hbarList(states.map(s => ({ label: s.label, href: `#/worklist?state=${encodeURIComponent(s.state)}`, value: s.highest, sub: n(s.records) })))}` : empty('No case is in this group.')}</div>
      </div>
      <div class="ov-col">
      <div class="panel">${panelHead('Decisions', 'check', '<a class="small link-go" href="#/reviewed">All decisions</a>')}
        <div class="dtiles">${decisionTiles}</div></div>
      <div class="panel">${panelHead('By interview period', 'trend', '<a class="small link-go" href="#/areas">Area trends</a>')}
        ${hasTrend ? `<p class="panel-note">Cases per 1,000 records that could be checked, by when the interview took place.</p><div class="legend" id="ovTrendLegend"></div><div class="viz-box" id="ovTrend"></div>`
          : empty(lanes ? 'This run has a single interview period, so there is nothing to compare over time.' : 'Available for current-method runs.')}</div>
      <div class="panel">${panelHead('Most recent decisions', 'clock', '<a class="small link-go" href="#/reviewed">All</a>')}
        ${rev.rows.length ? table(['Case', 'By', 'When'], rev.rows.slice(0, 5).map(x =>
          `<tr><td><a href="#/case/${encodeURIComponent(x.case_id)}">${esc(x.record_label)}</a><div>${decisionChip(x.decision)}</div></td><td>${esc(x.actor)}${x.actor_verified ? '' : ' <span class="small muted">(unverified)</span>'}</td><td class="small">${esc(when(x.decided_at_utc))}</td></tr>`)) : empty('No decision recorded yet.')}</div>
      </div>
    </div>
    <div class="panel violet">${panelHead('Strongest group alerts', 'group', '<a class="small link-go" href="#/groups">All</a>')}
        ${table(['FSU', 'What differs'], grp.rows.map(g => `<tr><td><a href="#/group/${encodeURIComponent(g.fsu)}?state=${encodeURIComponent(g.state)}">${esc(g.fsu)}</a><div class="small muted">${esc(g.location_label)}</div></td><td>${esc(g.patterns?.[0]?.text || g.strongest_statement || '')}</td></tr>`), { empty: 'No FSU-level group alert.' })}
        <p class="small">Group alerts describe an FSU as a whole. They do not mean that any person's answers are wrong and never move a case in the list.</p></div>
    <div class="fold-row">
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
      <p class="small muted">${esc(burden.note || '')} This is a structural check, not a validation against confirmed errors.</p></details>` : ''}</div>`;

  if (hasTrend) {
    const draw = () => {
      const box = document.querySelector('#ovTrend');
      if (!box) return;
      const t = listTrend(cube.rows, cube.periods, {});
      document.querySelector('#ovTrendLegend').innerHTML = trendLegend(t.series);
      box.innerHTML = lineChart({ width: vizWidth(box), height: 220, periods: t.periods, series: t.series, indicator: '_per1000', zero: true,
        label: `Cases per 1,000 checkable records by interview period. ${t.summary}`, tipFor: t.tipFor });
      roving(box);
    };
    draw();
    vizRedraw = draw;
  }
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
      lede: 'Cases grouped by FSU and household, in queue order.' })}
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
      lede: 'All cases in queue order. Filter by list, reason, area or review status, or search by FSU or record.' })}
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
      ${S.deploy.exports && can('export') ? `<a class="btn secondary" href="${url('/api/export/queue', { run: S.run, ...f })}" id="export">Export CSV</a>`
        : '<span class="small muted" title="Exports are logged in the audit trail; they are offered only where that is available.">CSV export is not available on this instance</span>'}</div>
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
    <label>Note <textarea name="comment" rows="2" maxlength="2000" placeholder="Optional: what was checked and with whom"></textarea>${S.deploy.notes_shown === false ? '<span class="small muted">Your note is saved with the decision but is not shown on this site.</span>' : ''}</label>
    <button class="lg block cta">Save decision</button>
    ${S.user ? `<p class="small muted" id="who">Saving as ${esc(S.user.name)}.</p>` : ''}
  </form>`;
}

async function casePage(caseId, params) {
  crumbs(['Case']);
  const opened = new Date().toISOString();
  const d = await api(url(`/api/cases/${encodeURIComponent(caseId)}`, { run: S.run }));
  if (S.deploy.audit_writable && canDecide()) {
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
      <div class="panel kv-pairs"><h2>What was recorded</h2>${kv([...(record.location || []), ...(record.survey || [])])}${record.person?.length ? `<h3>${record.level === 'household' ? 'Household' : 'Person'}</h3>${kv(record.person)}` : ''}</div>
      ${evidence}
      ${groupHtml(s.group || (s.evidence || []).find(e => e.source === 'pattern'), d.fsu, d.state)}
      ${s.unavailable?.length ? `<div class="panel"><h2>What could not be checked</h2><ul class="checks">${s.unavailable.map(u => `<li><b>${esc(u.title)}:</b> ${esc(u.text)}</li>`).join('')}</ul></div>` : ''}
      <div class="panel flat tight">${tech({ case: Object.fromEntries(Object.entries(d).filter(([k]) => !['story', 'audit_history', 'evidence_card'].includes(k))), source_runs: s.source_runs }, 'Technical details (stored case fields)')}</div>
    </div><div class="case-side">
      <div class="panel">${panelHead('What to check', 'list')}${s.checks?.length ? `<ul class="checks">${s.checks.map(c => `<li>${esc(c.text)}${c.detail ? `<div class="small muted">${esc(c.detail)}</div>` : ''}</li>`).join('')}</ul>` : empty('No specific check.')}</div>
      <div class="panel decision-panel">${panelHead('Your decision', 'check')}${!lanes ? '<p class="muted">Decisions are recorded on current-method runs.</p>'
        : S.deploy.audit_writable && canDecide() ? decisionForm(d)
        : `<div class="readonly-note">${infoBox(S.deploy.audit_writable ? '<b>Your role can view cases but not record decisions.</b> A supervisor or administrator records them.'
          : `<b>Decisions cannot be recorded here.</b> ${esc(S.deploy.audit_reason || '')}`, 'accent')}<span class="small muted">Current status: ${decisionChip(d.review_status)}</span></div>`}</div>
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
      S.ov = null;
      S.flash = { text: body.comment && S.deploy.notes_shown === false ? 'Decision saved to the audit trail. Your note is stored with it but is not shown on this site.'
        : 'Decision saved to the audit trail.', kind: 'ok' };
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
      lede: 'FSUs whose combined answers differ from comparable FSUs. Background for case review, not a finding about any person.' })}
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

/* ------------------------------------------------------------ chart toolkit
 *
 * Hand-written inline SVG (no library, no network).  Every mark is drawn from rows the API returned; the only
 * arithmetic is scaling, ±1.96 × standard error bands, medians and differences of stored values.
 * Text is escaped with esc(); tooltips are one shared element fed from data-tip attributes (hover and keyboard focus). */

const VIZ = {
  // categorical series (focus area first); validated all-pairs for colour-vision deficiency and normal vision on white
  series: ['#3355e0', '#eb6834', '#8a5a00', '#b0399a'],
  // diverging, direction only (decrease blue <- grey -> increase orange), never good/bad
  div: ['#1f3d9e', '#4565d6', '#8fa5ee', '#cdd7f8', '#eceef3', '#f8d5bd', '#f0a46c', '#d9701f', '#9c4a0c'],
  none: '#f1f2f6',
};
let vizSeq = 0;
let vizRedraw = null;
const vscale = (d0, d1, r0, r1) => { const k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0); return v => r0 + (v - d0) * k; };
function niceStep(lo, hi, count = 5) {
  const raw = Math.max(hi - lo, 1e-12) / count, mag = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= raw * 0.999);
}
function niceDomain(lo, hi, count = 5) {
  if (!(hi > lo)) { const pad = Math.abs(hi) * 0.1 || 1; lo -= pad; hi += pad; }
  const step = niceStep(lo, hi, count);
  const d0 = Math.floor(lo / step) * step, d1 = Math.ceil(hi / step) * step;
  const ticks = []; for (let v = d0; v <= d1 + step * 1e-6; v += step) ticks.push(+v.toFixed(10));
  return { d0, d1, step, ticks };
}
function tickFormat(indicator, step) {
  const u = INDICATOR_UNIT[indicator];
  if (u === 'share') return v => `${(v * 100).toFixed(step * 100 < 1 ? 1 : 0)}%`;
  if (u === 'per1000') return v => v.toFixed(step < 1 ? 1 : 0);
  if (u === 'count') return v => n(v);
  if (u === 'rupees') return v => (Math.abs(v) >= 1000 ? `₹${(v / 1000).toFixed(step < 1000 ? 1 : 0)}K` : `₹${Math.round(v)}`);
  return v => `${v.toFixed(step < 1 ? 1 : 0)} h`;
}
const svgEl = (w, h, label, body, cls = '') => `<svg class="viz ${cls}" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(label)}">${body}</svg>`;
const hatchDef = (id, color = '#8d93a6') => `<defs><pattern id="${id}" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="5" height="5" fill="#ffffff"/><line x1="0" y1="0" x2="0" y2="5" stroke="${color}" stroke-width="1.6"/></pattern></defs>`;
function runs(points) {   // contiguous stretches of points that have a value
  const out = []; let cur = [];
  points.forEach(p => { if (p && p.y != null && Number.isFinite(p.y)) cur.push(p); else if (cur.length) { out.push(cur); cur = []; } });
  if (cur.length) out.push(cur);
  return out;
}
const pathD = pts => pts.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join('');
const bandD = pts => `${pathD(pts.map(p => ({ x: p.x, y: p.hi })))}${pts.slice().reverse().map(p => `L${p.x.toFixed(1)},${p.lo.toFixed(1)}`).join('')}Z`;
function yGrid(dom, y, x0, x1, fmt) {
  return `<g class="grid">${dom.ticks.map(t => `<line x1="${x0}" x2="${x1}" y1="${y(t).toFixed(1)}" y2="${y(t).toFixed(1)}"/>`).join('')}</g>
    ${dom.ticks.map(t => `<text x="${x0 - 8}" y="${y(t).toFixed(1)}" text-anchor="end" dominant-baseline="middle">${esc(fmt(t))}</text>`).join('')}`;
}
function xGrid(dom, x, y0, y1, fmt, labelY) {
  return `<g class="grid">${dom.ticks.map(t => `<line y1="${y0}" y2="${y1}" x1="${x(t).toFixed(1)}" x2="${x(t).toFixed(1)}"/>`).join('')}</g>
    ${dom.ticks.map(t => `<text x="${x(t).toFixed(1)}" y="${labelY}" text-anchor="middle">${esc(fmt(t))}</text>`).join('')}`;
}
// Tooltip content: the value leads, the label follows; a short line key carries the series identity.
function tipHtml(head, rows) {
  return `<div class="t-head">${esc(head)}</div>${rows.map(r => `<div class="t-row">${r.color ? `<i class="t-key" style="background:${r.color}"></i>` : ''}<b>${esc(r.value)}</b><span>${esc(r.label || '')}</span></div>${r.sub ? `<div class="t-sub">${esc(r.sub)}</div>` : ''}`).join('')}`;
}
const tipAttr = html => ` data-tip="${esc(html)}"`;
const trunc = (s, k) => (s.length > k ? `${s.slice(0, k - 1)}…` : s);
const vizWidth = el => Math.max(260, Math.floor(el?.clientWidth || 600));

/* Shared tooltip: one element, positioned at the pointer or at the focused mark. */
const vtip = Object.assign(document.createElement('div'), { className: 'vtip', role: 'tooltip' });
document.body.appendChild(vtip);
function hideTip() { vtip.classList.remove('on'); }
function placeTip(x, y) {
  const w = vtip.offsetWidth, h = vtip.offsetHeight;
  vtip.style.left = `${Math.max(8, Math.min(x + 14, window.innerWidth - w - 8))}px`;
  vtip.style.top = `${y - h - 12 < 8 ? y + 18 : y - h - 12}px`;
}
function showTip(el, x, y) { vtip.innerHTML = el.dataset.tip; vtip.classList.add('on'); placeTip(x, y); }
document.addEventListener('pointerover', e => { const t = e.target.closest?.('[data-tip]'); if (t) showTip(t, e.clientX, e.clientY); else hideTip(); });
document.addEventListener('pointermove', e => { if (vtip.classList.contains('on') && e.target.closest?.('[data-tip]')) placeTip(e.clientX, e.clientY); });
document.addEventListener('focusin', e => { const t = e.target.closest?.('[data-tip]'); if (t) { const r = t.getBoundingClientRect(); showTip(t, r.left + r.width / 2, r.top); } else hideTip(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') hideTip(); });
window.addEventListener('scroll', hideTip, { passive: true });
window.addEventListener('resize', () => { clearTimeout(window.vizResize); window.vizResize = setTimeout(() => vizRedraw?.(), 150); });

// One tab stop per chart; arrow keys move between its marks (a grid passes its column count in data-cols).
function roving(root) {
  const items = [...root.querySelectorAll('[data-rove]')];
  items.forEach((el, i) => el.setAttribute('tabindex', i ? '-1' : '0'));
  root.onkeydown = e => {
    const i = items.indexOf(e.target.closest?.('[data-rove]'));
    if (i < 0) return;
    const cols = Number(root.querySelector('[data-cols]')?.dataset.cols || 1);
    const step = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: cols, ArrowUp: -cols, Home: -i, End: items.length - 1 - i }[e.key];
    if (step == null) return;
    e.preventDefault();
    const j = Math.max(0, Math.min(items.length - 1, i + step));
    items[i].setAttribute('tabindex', '-1'); items[j].setAttribute('tabindex', '0'); items[j].focus();
  };
}

/* Line chart over periods with an optional ±1.96 × SE band per series, markers for unusual / expected / imprecise points,
   and a crosshair column per period that carries the tooltip for every series at that period. */
function lineChart({ width: W, height: H = 280, periods, series, indicator, label, tipFor, zero = false }) {
  const m = { l: 58, r: 18, t: 14, b: 30 };
  const share = INDICATOR_UNIT[indicator] === 'share';
  const lo = v => Math.max(0, v), hi = v => (share ? Math.min(1, v) : v);
  const vals = series.flatMap(s => s.points.flatMap(p => (p.v == null ? [] : s.band && p.se != null ? [lo(p.v - 1.96 * p.se), hi(p.v + 1.96 * p.se)] : [p.v])));
  if (!vals.length) return empty('No value for this area and indicator.');
  const dom = niceDomain(zero ? 0 : Math.max(0, Math.min(...vals)), Math.max(...vals), 5);
  const fmt = tickFormat(indicator, dom.step);
  const y = vscale(dom.d0, dom.d1, H - m.b, m.t);
  const k = periods.length;
  const x = k === 1 ? () => (m.l + W - m.r) / 2 : vscale(0, k - 1, m.l + 8, W - m.r - 8);
  const colW = k === 1 ? W - m.l - m.r : (W - m.l - m.r - 16) / (k - 1);
  const every = Math.max(1, Math.ceil(k * 62 / (W - m.l - m.r)));
  const uid = `v${++vizSeq}`;
  let body = hatchDef(uid) + yGrid(dom, y, m.l, W - m.r, fmt) + `<line class="axis" x1="${m.l}" x2="${W - m.r}" y1="${H - m.b}" y2="${H - m.b}"/>`;
  body += periods.map(([, lbl], i) => (i % every === 0 || i === k - 1) && !(i !== k - 1 && k - 1 - i < every) ? `<text x="${x(i).toFixed(1)}" y="${H - 10}" text-anchor="middle">${esc(lbl)}</text>` : '').join('');
  series.forEach(s => {
    const pts = s.points.map((p, i) => ({ x: x(i), y: p.v == null ? null : y(p.v), hi: p.se == null || p.v == null ? null : y(hi(p.v + 1.96 * p.se)), lo: p.se == null || p.v == null ? null : y(lo(p.v - 1.96 * p.se)) }));
    if (s.band) body += runs(pts.map(p => (p.hi == null ? null : p))).map(r => `<path class="band" d="${bandD(r)}" fill="${s.color}"/>`).join('');
  });
  series.forEach(s => {
    const pts = s.points.map((p, i) => ({ x: x(i), y: p.v == null ? null : y(p.v) }));
    body += runs(pts).map(r => (r.length > 1 ? `<path class="ln ${s.dash ? 'dash' : 'draw'}" ${s.dash ? '' : 'pathLength="1"'} d="${pathD(r)}" stroke="${s.color}"/>` : '')).join('');
    s.points.forEach((p, i) => {
      if (p.v == null) return;
      const cx = x(i).toFixed(1), cy = y(p.v).toFixed(1);
      if (p.notable || p.expected) body += `<circle class="ring-mark" cx="${cx}" cy="${cy}" r="8" ${p.expected ? 'stroke-dasharray="2.5 2"' : ''}/>`;
      if (k <= 24 || i === k - 1 || p.low || p.notable) body += `<circle class="pt ${p.low ? 'low' : ''}" cx="${cx}" cy="${cy}" r="4" fill="${s.color}" ${p.low ? `stroke="${s.color}"` : ''}/>`;
    });
    const lastI = s.points.map(p => p.v != null).lastIndexOf(true);
    if (s.endLabel && lastI >= 0) {
      const ex = x(lastI), ey = y(s.points[lastI].v);
      body += `<text class="lbl-strong" x="${(ex + (ex > W - 80 ? -10 : 10)).toFixed(1)}" y="${(ey - 12).toFixed(1)}" text-anchor="${ex > W - 80 ? 'end' : 'start'}">${esc(indicatorValue(indicator, s.points[lastI].v))}</text>`;
    }
  });
  body += `<g data-cols="1">${periods.map(([pi, lbl], i) => `<g class="col" data-rove${tipAttr(tipFor(pi, lbl))} aria-label="${esc(lbl)}">
      <line class="xhair" x1="${x(i).toFixed(1)}" x2="${x(i).toFixed(1)}" y1="${m.t}" y2="${H - m.b}"/>
      <rect class="hit" x="${(x(i) - colW / 2).toFixed(1)}" y="${m.t}" width="${Math.max(8, colW).toFixed(1)}" height="${H - m.t - m.b}"/></g>`).join('')}</g>`;
  return svgEl(W, H, label, body);
}

/* Horizontal bars from zero with a ±1.96 × SE whisker, a reference line, and a hatched fill for low-precision values. */
function rankChart({ width: W, items, indicator, ref, label, rowH = 26 }) {
  if (!items.length) return empty('No area matches.');
  const labelW = Math.min(210, Math.round(W * 0.36)), valW = 70;
  const m = { l: labelW + 10, r: valW, t: ref ? 22 : 6, b: 26 };
  const H = m.t + items.length * rowH + m.b;
  const top = Math.max(...items.map(i => (i.v ?? 0) + 1.96 * (i.se ?? 0)), ref?.v ?? 0);
  const dom = niceDomain(0, top || 1, Math.max(2, Math.min(5, Math.floor((W - m.l - m.r) / 90))));
  const fmt = tickFormat(indicator, dom.step);
  const x = vscale(0, dom.d1, m.l, W - m.r);
  const uid = `v${++vizSeq}`;
  let body = hatchDef(uid, '#3355e0') + xGrid(dom, x, m.t - 4, H - m.b, fmt, H - 8);
  body += `<g data-cols="1">${items.map((it, i) => {
    const cy = m.t + i * rowH + rowH / 2;
    const w = it.v == null ? 0 : Math.max(1, x(it.v) - x(0));
    const wl = it.se == null || it.v == null ? null : x(Math.max(0, it.v - 1.96 * it.se)), wr = it.se == null || it.v == null ? null : x(it.v + 1.96 * it.se);
    return `<g class="rk ${it.focus ? 'focus' : ''}" data-rove ${it.key ? `data-focus="${esc(it.key)}"` : ''}${tipAttr(it.tip)} aria-label="${esc(it.name)}">
      <rect class="hit" x="0" y="${(cy - rowH / 2).toFixed(1)}" width="${W}" height="${rowH}" rx="6"/>
      <text class="lbl-ink" x="${labelW}" y="${cy.toFixed(1)}" text-anchor="end" dominant-baseline="middle">${esc(trunc(it.name, Math.floor(labelW / 6.4)))}</text>
      ${it.v == null ? '' : `<rect class="bar-fill" x="${x(0).toFixed(1)}" y="${(cy - 6).toFixed(1)}" width="${w.toFixed(1)}" height="12" rx="3" fill="${it.low ? `url(#${uid})` : it.color || VIZ.series[0]}" ${it.low ? `stroke="${VIZ.series[0]}" stroke-width="1"` : ''}/>`}
      ${wl == null ? '' : `<line class="whisker" x1="${wl.toFixed(1)}" x2="${wr.toFixed(1)}" y1="${cy.toFixed(1)}" y2="${cy.toFixed(1)}"/><line class="whisker" x1="${wl.toFixed(1)}" x2="${wl.toFixed(1)}" y1="${cy - 4}" y2="${cy + 4}"/><line class="whisker" x1="${wr.toFixed(1)}" x2="${wr.toFixed(1)}" y1="${cy - 4}" y2="${cy + 4}"/>`}
      <text class="lbl-strong" x="${W - 4}" y="${cy.toFixed(1)}" text-anchor="end" dominant-baseline="middle">${esc(indicatorValue(indicator, it.v))}</text></g>`;
  }).join('')}</g>`;
  if (ref && ref.v != null) body += `<line class="ref" x1="${x(ref.v).toFixed(1)}" x2="${x(ref.v).toFixed(1)}" y1="${m.t - 6}" y2="${H - m.b}"/>
    <text class="lbl-ink" x="${x(ref.v).toFixed(1)}" y="${m.t - 10}" text-anchor="middle">${esc(ref.label)} ${esc(indicatorValue(indicator, ref.v))}</text>`;
  return svgEl(W, H, label, body);
}

const divColor = z => (z == null || !Number.isFinite(z) ? null : VIZ.div[z <= -4 ? 0 : z <= -3 ? 1 : z <= -2 ? 2 : z <= -1 ? 3 : z < 1 ? 4 : z < 2 ? 5 : z < 3 ? 6 : z < 4 ? 7 : 8]);
const divLegend = () => `<span><span class="div-scale" aria-hidden="true">${VIZ.div.map(c => `<i style="background:${c}"></i>`).join('')}</span>
  <span class="small">decrease ← change ÷ design SE (−4 … +4) → increase</span></span><span><i class="k-sw" style="background:${VIZ.none};outline:1px dashed #8d93a6"></i>not assessable</span><span><i class="k-ring" style="border-radius:2px"></i>unusual change</span>`;

/* Areas × periods heatmap; one tab stop, arrow keys move cell by cell. */
function heatmap({ width: W, rows, periods, cell, label }) {
  if (!rows.length || !periods.length) return empty('No area matches.');
  const labelW = Math.min(200, Math.round(W * 0.32));
  const cw = Math.max(18, Math.floor((W - labelW - 12) / periods.length)), ch = 22;
  const Wt = labelW + 12 + cw * periods.length, H = 26 + rows.length * ch + 4;
  const every = Math.max(1, Math.ceil(56 / cw));
  const uid = `v${++vizSeq}`;
  let body = hatchDef(uid) + periods.map(([, lbl], j) => (j % every === 0 ? `<text x="${(labelW + 12 + j * cw + cw / 2).toFixed(1)}" y="14" text-anchor="middle">${esc(String(lbl).replace(/ (\d{2})(\d{2})$/, ' ’$2'))}</text>` : '')).join('');
  body += `<g data-cols="${periods.length}">`;
  rows.forEach((r, i) => {
    const y0 = 24 + i * ch;
    body += `<text class="${r.focus ? 'lbl-strong' : 'lbl-ink'}" x="${labelW}" y="${y0 + ch / 2}" text-anchor="end" dominant-baseline="middle">${esc(trunc(r.name, Math.floor(labelW / 6.4)))}</text>`;
    periods.forEach(([pi, lbl], j) => {
      const c = cell(r, pi, lbl);
      const fill = divColor(c.z);
      body += `<rect class="cell ${c.notable ? 'notable' : ''}" data-rove${tipAttr(c.tip)} aria-label="${esc(`${r.name}, ${lbl}`)}" x="${labelW + 12 + j * cw}" y="${y0}" width="${cw}" height="${ch}" rx="3" fill="${fill || (c.present ? `url(#${uid})` : VIZ.none)}"/>`;
    });
  });
  return svgEl(Wt, H, label, `${body}</g>`);
}

const sparkline = (values, { w = 160, h = 34, color = VIZ.series[0], lowLast = false } = {}) => {
  const pts = values.map((v, i) => ({ i, v })).filter(p => p.v != null);
  if (!pts.length) return `<svg class="viz" width="${w}" height="${h}" aria-hidden="true"></svg>`;
  const lo = Math.min(...pts.map(p => p.v)), hi = Math.max(...pts.map(p => p.v));
  const x = values.length === 1 ? () => w / 2 : vscale(0, values.length - 1, 4, w - 6), y = vscale(lo === hi ? lo - 1 : lo, lo === hi ? hi + 1 : hi, h - 5, 5);
  const xy = pts.map(p => ({ x: x(p.i), y: y(p.v) }));
  const end = xy[xy.length - 1];
  return `<svg class="viz" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true" preserveAspectRatio="none">${runs(values.map((v, i) => (v == null ? null : { x: x(i), y: y(v) }))).map(r => `<path class="ln" style="stroke-width:1.6" d="${pathD(r)}" stroke="${color}"/>`).join('')}
    <circle class="pt ${lowLast ? 'low' : ''}" cx="${end.x.toFixed(1)}" cy="${end.y.toFixed(1)}" r="3.5" fill="${color}" stroke="${lowLast ? color : ''}"/></svg>`;
};

/* Spread of area values in one period: one strip per sector, median marked, focus area highlighted. */
function spreadChart({ width: W, height = 0, groups, indicator, label }) {
  const all = groups.flatMap(g => g.values.map(v => v.v)).filter(v => v != null);
  if (!all.length) return empty('No value this period.');
  // Strips grow to fill the card beside the trend chart; dots and median bar scale with them.
  const m = { l: 70, r: 16, t: 8, b: 26 }, gh = Math.max(54, (height - m.t - m.b) / groups.length), k = Math.min(gh / 54, 2.6);
  const H = m.t + groups.length * gh + m.b;
  const dom = niceDomain(Math.max(0, Math.min(...all)), Math.max(...all), Math.max(2, Math.min(5, Math.floor((W - m.l - m.r) / 80))));
  const fmt = tickFormat(indicator, dom.step);
  const x = vscale(dom.d0, dom.d1, m.l, W - m.r);
  let body = xGrid(dom, x, m.t, H - m.b, fmt, H - 8);
  groups.forEach((g, gi) => {
    const cy = m.t + gi * gh + gh / 2;
    const vals = g.values.filter(v => v.v != null).sort((a, b) => a.v - b.v);
    const med = median(vals.map(v => v.v));
    body += `<text class="lbl-ink" x="${m.l - 10}" y="${cy}" text-anchor="end" dominant-baseline="middle">${esc(g.name)}</text>`;
    body += vals.map((v, i) => `<circle class="spread-dot ${v.focus ? 'focus' : ''}" cx="${x(v.v).toFixed(1)}" cy="${(cy + ((i * 7) % 5 - 2) * 3.4 * k).toFixed(1)}" r="${v.focus ? 5.5 : 3.6}"${tipAttr(tipHtml(g.name, [{ value: indicatorValue(indicator, v.v), label: v.name }]))}/>`).join('');
    if (med != null) body += `<line class="ref" x1="${x(med).toFixed(1)}" x2="${x(med).toFixed(1)}" y1="${(cy - 17 * k).toFixed(1)}" y2="${(cy + 17 * k).toFixed(1)}" style="stroke-dasharray:none;stroke-width:2"/>
      <text class="lbl-strong" x="${x(med).toFixed(1)}" y="${(cy - 17 * k - 3).toFixed(1)}" text-anchor="middle">median ${esc(indicatorValue(indicator, med))}</text>`;
  });
  return svgEl(W, H, label, body);
}
function median(values) {
  const v = values.filter(x => x != null && Number.isFinite(x)).sort((a, b) => a - b);
  return v.length ? (v.length % 2 ? v[(v.length - 1) / 2] : (v[v.length / 2 - 1] + v[v.length / 2]) / 2) : null;
}

/* ------------------------------------------------------------ case analytics (Area trends: cases by area)
 *
 * Built from /api/case-areas: stored record counts by area x sector x interview period x list x reason set.  Every
 * record is counted once; the only arithmetic is sums, shares, rates per 1,000 and a two-proportion comparison. */

const LIST_BANDS = { A: ['CHECK_NOW'], B: ['CHECK_IF_TIME'], AB: ['CHECK_NOW', 'CHECK_IF_TIME'] };
const LIST_NAME = { A: 'Check now', B: 'Check if time', AB: 'Check now or Check if time' };
const LIST_TONE = { A: ['red', 'xcircle'], B: ['amber', 'clock'], AB: ['red', 'alert'] };
const STATUS_LINE = { red: '#c0302b', amber: '#a86400' };
// Rates from fewer records that could be checked are shown but never ranked or compared: they move too much by chance.
const MIN_CHECKABLE = 1000;
// A difference counts as clear at three standard errors (conservative, because cases cluster within FSUs).
const CLEAR_Z = 3;
const per1000 = (cases, base) => (base ? (cases / base) * 1000 : null);
const fmtRate = v => (v == null ? '—' : Number(v).toFixed(1));
function propZ(c1, n1, c2, n2) {
  if (!n1 || !n2) return null;
  const p = (c1 + c2) / (n1 + n2), se = Math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2));
  return se ? (c2 / n2 - c1 / n1) / se : null;
}

// Sum cube rows into groups (key(row) -> group).  Reason counts overlap when a case has several reasons.
function caseAgg(rows, { list = 'A', reason = '', sector = '', key = () => '' } = {}) {
  const bands = LIST_BANDS[list] || LIST_BANDS.A;
  const out = new Map();
  rows.forEach(r => {
    if (sector && r.sector !== sector) return;
    const k = key(r);
    if (k == null) return;
    if (!out.has(k)) out.set(k, { key: k, name: r.area_label, records: 0, checkable: 0, cases: 0, decided: 0, lanes: {} });
    const g = out.get(k);
    g.records += r.records;
    if (r.band !== 'NOT_ASSESSABLE') g.checkable += r.records;
    if (bands.includes(r.band) && (!reason || r.lanes.includes(reason))) {
      g.cases += r.records; g.decided += r.decided;
      r.lanes.forEach(l => { g.lanes[l] = (g.lanes[l] || 0) + r.records; });
    }
  });
  out.forEach(g => { g.rate = per1000(g.cases, g.checkable); });
  return out;
}
const total = (rows, f) => caseAgg(rows, f).get('') || { records: 0, checkable: 0, cases: 0, decided: 0, lanes: {}, rate: null };

// Both lists over interview periods, as rates per 1,000 checkable records, for lineChart.
function listTrend(rows, periods, { reason = '', sector = '' } = {}) {
  const P = periods.map(p => [p.index, p.label]);
  const per = list => caseAgg(rows, { list, reason, sector, key: r => r.period_index });
  const mk = (m, name, color, dash) => ({ name, color, dash, endLabel: !dash,
    points: P.map(([i]) => { const g = m.get(i); return g && g.checkable ? { v: g.rate, row: g } : { v: null }; }) });
  const series = [mk(per('A'), LIST_NAME.A, STATUS_LINE.red, false), mk(per('B'), LIST_NAME.B, STATUS_LINE.amber, true)];
  const tipFor = (pi, lbl) => tipHtml(lbl, series.map(s => { const p = s.points[P.findIndex(x => x[0] === pi)]; const g = p.row;
    return { color: s.color, value: g ? `${fmtRate(p.v)} per 1,000` : '—', label: s.name, sub: g ? `${n(g.cases)} cases · ${n(g.checkable)} records could be checked` : 'no records' }; }));
  const summary = series.map(s => `${s.name}: ${s.points.map((p, i) => `${P[i][1]} ${fmtRate(p.v)}`).join(', ')}`).join('. ');
  return { periods: P, series, tipFor, summary };
}
const trendLegend = series => series.map(s => `<span><i class="${s.dash ? 'k-dash' : 'k-line'}" style="${s.dash ? `border-color:${s.color}` : `background:${s.color}`}"></i>${esc(s.name)}</span>`).join('');
// First vs last interview period for one list: values and whether the difference is clear.
function periodChange(rows, periods, f) {
  const m = caseAgg(rows, { ...f, key: r => r.period_index });
  const pts = periods.map(p => ({ ...p, g: m.get(p.index) })).filter(p => p.g && p.g.checkable);
  if (pts.length < 2) return null;
  const a = pts[0], b = pts[pts.length - 1];
  return { a, b, z: propZ(a.g.cases, a.g.checkable, b.g.cases, b.g.checkable) };
}
const compareWord = z => (z == null || Math.abs(z) < CLEAR_Z ? 'close to' : z > 0 ? 'clearly above' : 'clearly below');

function areaTabs(view) {
  return `<div class="tabs" role="navigation" aria-label="Area trends views">
    <a href="#/areas" ${view === 'cases' ? 'aria-current="page"' : ''}>${icon('map')}Cases by area</a>
    <a href="#/areas?view=indicators" ${view === 'indicators' ? 'aria-current="page"' : ''}>${icon('trend')}Survey indicators</a></div>`;
}

async function areas(_, params) {
  const view = params.get('view') || (params.get('indicator') || params.get('level') ? 'indicators' : 'cases');
  return view === 'indicators' ? areaIndicators(_, params) : areaCases(params);
}

async function areaCases(params) {
  crumbs(['Area trends']);
  const head = `${pageHead({ eyebrow: 'Context', title: 'Area trends', lede: 'Where the cases needing attention are, why they are listed and how they change across interview periods.' })}${areaTabs('cases')}`;
  const d = await api(url('/api/case-areas', { run: S.run }));
  if (!d.available) { app.innerHTML = head + empty(d.reason || 'No case data for this run.'); return; }
  if (d.method !== 'lanes') {
    app.innerHTML = `${supersededBanner()}${head}${infoBox('Cases by area use the “Check now” and “Check if time” lists of current-method runs. Select a current-method survey round, or open <a href="#/areas?view=indicators">Survey indicators</a>.', 'accent')}`;
    return;
  }
  const lanesPresent = Object.keys(S.labels.lanes).filter(l => d.rows.some(r => r.lanes.includes(l)));
  const stateCodes = [...new Map(d.rows.map(r => [r.area, r.area_label])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
  const V = {
    list: LIST_BANDS[params.get('list')] ? params.get('list') : 'A',
    sector: ['1', '2'].includes(params.get('sector')) ? params.get('sector') : '',
    reason: lanesPresent.includes(params.get('reason')) ? params.get('reason') : '',
    state: stateCodes.some(([c]) => c === params.get('state')) ? params.get('state') : '',
    measure: params.get('measure') === 'rate' ? 'rate' : 'cases', top: 15,
  };
  const districts = new Map();   // state code -> district rows (fetched on demand)
  const stateName = code => (stateCodes.find(([c]) => c === code) || [, `State ${code}`])[1];
  const scopeName = () => (V.state ? stateName(V.state) : 'All India');
  const seg = (name, value, options) => `<div class="seg" data-seg="${name}">${options.map(([v, l]) => `<button type="button" data-v="${esc(v)}" aria-pressed="${v === value}">${esc(l)}</button>`).join('')}</div>`;

  app.innerHTML = `${head}<div id="ac">
    <div class="toolbar at-controls">
      <div class="ctl" role="group" aria-label="List"><span aria-hidden="true">List</span>${seg('list', V.list, [['A', 'Check now'], ['B', 'Check if time'], ['AB', 'Both']])}</div>
      <div class="ctl" role="group" aria-label="Sector"><span aria-hidden="true">Sector</span>${seg('sector', V.sector, [['', 'All'], ['1', 'Rural'], ['2', 'Urban']])}</div>
      <label class="ctl">Reason <select class="field" id="acReason"><option value="">Any reason</option>${lanesPresent.map(l => `<option value="${esc(l)}">${esc(S.labels.lanes[l])}</option>`).join('')}</select></label>
      <label class="ctl">Area <select class="field" id="acState"><option value="">All India</option>${stateCodes.map(([c, l]) => `<option value="${esc(c)}">${esc(l)}</option>`).join('')}</select></label>
      <button type="button" class="secondary" id="acReset">Reset</button>
    </div>
    <div class="scope" id="acScope"></div>
    <section class="stats area-stats" id="acStats" aria-label="Headline figures"></section>
    <section class="panel insights" aria-labelledby="acInsH"><div class="panel-head"><h2 id="acInsH">${icon('spark')}What the data shows</h2><span class="small muted" id="acInsSub"></span></div><ul id="acInsights"></ul></section>
    <div class="at-grid">
      <div class="panel">${panelHead('Where the cases are', 'map', `<span id="acMeasure">${seg('measure', V.measure, [['cases', 'Number of cases'], ['rate', 'Rate per 1,000']])}</span>`)}
        <p class="panel-note" id="acRankNote"></p>
        <div class="viz-box tall" id="acRank"></div>
        <div class="rank-foot"><span class="small muted" id="acRankCount"></span><span id="acTop">${seg('top', String(V.top), [['15', 'Top 15'], ['30', 'Top 30'], ['0', 'All']])}</span></div></div>
      <div class="at-col">
        <div class="panel">${panelHead('Why cases are listed', 'bars', '<span class="small muted" id="acReasonSub"></span>')}<div id="acReasons"></div></div>
        <div class="panel">${panelHead('Rural and urban', 'group', '<span class="small muted">per 1,000 checkable records</span>')}<div id="acSectors"></div></div>
      </div>
    </div>
    <div class="at-grid even">
      <div class="panel">${panelHead('Across interview periods', 'trend', '<span class="small muted" id="acTrendSub"></span>')}
        <p class="panel-note">Cases per 1,000 records that could be checked, by when the interview took place. Interview periods of this survey round; this is not review progress.</p>
        <div class="legend" id="acTrendLegend"></div><div class="viz-box" id="acTrend"></div><p class="small" id="acTrendText" style="margin:10px 0 0"></p></div>
      <div class="panel">${panelHead('Other survey rounds', 'calendar', '<span class="small muted">current method only</span>')}<div id="acRounds"></div></div>
    </div>
    <div class="panel">${panelHead('All areas', 'list', '<span class="small muted" id="acTableSub"></span>')}<div id="acTable"></div></div>
    <details class="panel"><summary>What these figures mean</summary><ul class="checks small">
      <li><b>Records</b> are the person records in this survey round. <b>Records that could be checked</b> exclude those with “No check possible”; every rate uses them as the base.</li>
      <li><b>Cases</b> are records in the selected list. Each record is counted once, even when it has more than one reason, so reason counts can add up to more than the number of cases.</li>
      <li><b>Rate per 1,000</b> = cases ÷ records that could be checked × 1,000. A high count can simply mean many records; compare rates to see where cases are more concentrated.</li>
      <li>Areas with fewer than ${n(MIN_CHECKABLE)} records that could be checked are not ranked by rate. A difference is called <i>clear</i> only when it exceeds three standard errors of a two-proportion comparison; this is conservative because cases cluster within FSUs.</li>
      <li>“Check now” is limited by the review budget (${((d.budget.review_budget_share || 0) * 100).toFixed(1)}% of records, ${n(d.budget.budget_cases)} places in this round), so its size depends on the budget as well as on the data. Being listed means unusual, not wrong.</li></ul></details>
  </div>`;
  const root = document.querySelector('#ac');
  const $ = sel => root.querySelector(sel);
  $('#acReason').value = V.reason;
  $('#acState').value = V.state;

  const filt = () => ({ list: V.list, reason: V.reason, sector: V.sector });
  const baseRows = () => (V.state ? d.rows.filter(r => r.area === V.state) : d.rows);
  const areaRows = () => (V.state ? districts.get(V.state) : d.rows);
  const listLabel = () => `“${LIST_NAME[V.list]}”`;
  const syncUrl = () => {
    const q = new URLSearchParams(Object.entries({ list: V.list === 'A' ? '' : V.list, sector: V.sector, reason: V.reason, state: V.state, measure: V.measure === 'cases' ? '' : 'rate' }).filter(([, v]) => v));
    history.replaceState(null, '', `#/areas${q.toString() ? `?${q}` : ''}`);
    $('#acReset').disabled = !q.toString();
  };

  function drawScope() {
    const tier = V.list;
    const caseHref = V.list === 'AB' ? '' : `#/cases?${new URLSearchParams(Object.entries({ tier, state: V.state, sector: V.sector, lane: V.reason }).filter(([, v]) => v))}`;
    const wlHref = `#/worklist?${new URLSearchParams(Object.entries({ tier, state: V.state }).filter(([, v]) => v))}`;
    const parts = [V.state ? `<span class="scope-chip">${icon('map')}${esc(stateName(V.state))}<button type="button" data-clear="state" aria-label="Back to All India">×</button></span>` : `<span class="scope-chip plain">${icon('map')}All India</span>`,
      V.sector ? `<span class="scope-chip">${esc(sectorName(V.sector))}<button type="button" data-clear="sector" aria-label="Show both sectors">×</button></span>` : '',
      V.reason ? `<span class="scope-chip">${esc(S.labels.lanes[V.reason])}<button type="button" data-clear="reason" aria-label="Show every reason">×</button></span>` : ''];
    $('#acScope').innerHTML = `<div class="scope-l"><span class="small muted">Showing ${esc(listLabel())} cases for</span>${parts.join('')}</div>
      <div class="scope-r"><a class="btn secondary" href="${wlHref}">${icon('list')}Open worklist</a>${caseHref ? `<a class="btn secondary" href="${caseHref}">All matching cases</a>` : ''}</div>`;
  }

  function drawStats() {
    const t = total(baseRows(), filt());
    const areaMap = areaRows() ? caseAgg(areaRows(), { ...filt(), key: r => r.area }) : new Map();
    const list = [...areaMap.values()];
    const top = list.slice().sort((a, b) => b.cases - a.cases)[0];
    const eligible = list.filter(a => a.checkable >= MIN_CHECKABLE);
    const topRate = eligible.slice().sort((a, b) => b.rate - a.rate)[0];
    const [tone, ic] = LIST_TONE[V.list];
    const level = V.state ? 'district' : 'State/UT';
    $('#acStats').innerHTML = [
      statCard({ tone: 'blue', ic: 'db', label: 'Records that could be checked', value: n(t.checkable), sub: `of ${n(t.records)} records · ${n(t.records - t.checkable)} with no check possible` }),
      statCard({ tone, ic, label: `${LIST_NAME[V.list]} cases`, value: n(t.cases), sub: `${fmtRate(t.rate)} per 1,000 checkable records` }),
      statCard({ tone: 'green', ic: 'check', label: 'Decided', value: t.cases ? pct(t.decided, t.cases) : '—', sub: `${n(t.decided)} of ${n(t.cases)} cases` }),
      statCard({ ic: 'map', label: `Most cases (${level})`, value: top && top.cases ? `<span class="stat-name">${esc(top.name)}</span>` : '—', sub: top && top.cases ? `${n(top.cases)} cases · ${pct(top.cases, t.cases)} of ${esc(scopeName())}` : 'No case in this selection' }),
      statCard({ ic: 'trend', label: `Highest rate (${level})`, value: topRate && topRate.cases ? `<span class="stat-name">${esc(topRate.name)}</span>` : '—',
        sub: topRate && topRate.cases ? `${fmtRate(topRate.rate)} per 1,000 · ${esc(scopeName())} ${fmtRate(t.rate)}` : eligible.length ? 'No case in this selection' : `No ${level} has ${n(MIN_CHECKABLE)} checkable records`,
        title: `Among areas with at least ${n(MIN_CHECKABLE)} records that could be checked` }),
    ].join('');
  }

  function drawInsights() {
    const rows = baseRows(), f = filt(), t = total(rows, f), out = [];
    const scope = esc(scopeName());
    const ln = esc(listLabel());
    if (!t.cases) { $('#acInsights').innerHTML = `<li>No ${ln} case matches this selection.</li>`; $('#acInsSub').textContent = ''; return; }
    const areaMap = areaRows() ? caseAgg(areaRows(), { ...f, key: r => r.area }) : new Map();
    const list = [...areaMap.values()];
    const level = V.state ? 'district' : 'State/UT';
    const top = list.slice().sort((a, b) => b.cases - a.cases)[0];
    if (top && top.cases && list.length > 1) {
      let s = `<b>${esc(top.name)}</b> has the most ${ln} cases: ${n(top.cases)}, or ${pct(top.cases, t.cases)} of ${scope}.`;
      if (top.checkable >= MIN_CHECKABLE) {
        const z = propZ(t.cases - top.cases, t.checkable - top.checkable, top.cases, top.checkable);
        s += ` Its rate, ${fmtRate(top.rate)} per 1,000 checkable records, is ${compareWord(z)} the rest of ${scope} (${fmtRate(per1000(t.cases - top.cases, t.checkable - top.checkable))}).`;
      }
      out.push(s);
    }
    const eligible = list.filter(a => a.checkable >= MIN_CHECKABLE);
    if (eligible.length > 1) {
      const hi = eligible.slice().sort((a, b) => b.rate - a.rate)[0];
      if (hi.key !== top?.key && hi.cases) {
        const z = propZ(t.cases - hi.cases, t.checkable - hi.checkable, hi.cases, hi.checkable);
        out.push(z != null && z >= CLEAR_Z
          ? `<b>${esc(hi.name)}</b> has the highest concentration: ${fmtRate(hi.rate)} cases per 1,000 checkable records, clearly above the rest of ${scope} (${fmtRate(per1000(t.cases - hi.cases, t.checkable - hi.checkable))}). It deserves a closer look.`
          : `<b>${esc(hi.name)}</b> has the highest rate (${fmtRate(hi.rate)} per 1,000), but it is not clearly different from the rest of ${scope}.`);
      }
      const clearHigh = eligible.filter(a => { const z = propZ(t.cases - a.cases, t.checkable - a.checkable, a.cases, a.checkable); return z != null && z >= CLEAR_Z; });
      if (clearHigh.length) out.push(`${n(clearHigh.length)} ${clearHigh.length === 1 ? level : `${level === 'district' ? 'districts' : 'States/UTs'}`} ${clearHigh.length === 1 ? 'has' : 'have'} a rate clearly above the rest of ${scope}: ${clearHigh.sort((a, b) => b.rate - a.rate).slice(0, 5).map(a => esc(a.name)).join(', ')}${clearHigh.length > 5 ? ' and others' : ''}.`);
    } else if (list.length > 1) {
      out.push(`Rates are not compared between ${V.state ? 'districts' : 'areas'}: ${eligible.length ? 'only one has' : 'none has'} at least ${n(MIN_CHECKABLE)} records that could be checked, so counts are shown instead.`);
    }
    const reasons = Object.entries(t.lanes).sort((a, b) => b[1] - a[1]);
    if (reasons.length && !V.reason) {
      const [code, c] = reasons[0];
      out.push(c / t.cases > 0.5 ? `Most of these cases (${pct(c, t.cases)}) are listed for <b>${esc(S.labels.lanes[code] || code)}</b>.` : `The most common reason is <b>${esc(S.labels.lanes[code] || code)}</b> (${pct(c, t.cases)} of cases).`);
    }
    const ch = periodChange(rows, d.periods, f);
    if (ch) {
      const clear = ch.z != null && Math.abs(ch.z) >= CLEAR_Z;
      out.push(clear ? `The ${ln} rate ${ch.z < 0 ? 'fell' : 'rose'} from ${fmtRate(ch.a.g.rate)} per 1,000 in ${esc(ch.a.label)} to ${fmtRate(ch.b.g.rate)} in ${esc(ch.b.label)}.`
        : `The ${ln} rate was ${fmtRate(ch.a.g.rate)} per 1,000 in ${esc(ch.a.label)} and ${fmtRate(ch.b.g.rate)} in ${esc(ch.b.label)}; the difference is too small to call a trend.`);
    }
    if (!V.sector) {
      const sec = caseAgg(rows, { ...f, key: r => r.sector });
      const ru = sec.get('1'), ur = sec.get('2');
      if (ru && ur && ru.checkable >= MIN_CHECKABLE && ur.checkable >= MIN_CHECKABLE) {
        const z = propZ(ur.cases, ur.checkable, ru.cases, ru.checkable);
        out.push(z != null && Math.abs(z) >= CLEAR_Z ? `Rural records have a ${z > 0 ? 'higher' : 'lower'} rate (${fmtRate(ru.rate)} per 1,000) than urban records (${fmtRate(ur.rate)}).`
          : `Rural and urban rates are similar (${fmtRate(ru.rate)} and ${fmtRate(ur.rate)} per 1,000).`);
      }
    }
    $('#acInsights').innerHTML = out.map(s => `<li>${s}</li>`).join('');
    $('#acInsSub').textContent = `${LIST_NAME[V.list]} · ${scopeName()}${V.sector ? ` · ${sectorName(V.sector)}` : ''}${V.reason ? ` · ${S.labels.lanes[V.reason]}` : ''}`;
  }

  function drawRank() {
    const box = $('#acRank');
    const rows = areaRows();
    const level = V.state ? 'district' : 'State/UT';
    if (!rows) { box.innerHTML = '<div class="loading">Loading districts…</div>'; return; }
    const t = total(baseRows(), filt());
    const all = [...caseAgg(rows, { ...filt(), key: r => r.area }).values()];
    const rate = V.measure === 'rate';
    const pool = rate ? all.filter(a => a.checkable >= MIN_CHECKABLE) : all.filter(a => a.cases > 0);
    pool.sort((a, b) => (rate ? b.rate - a.rate : b.cases - a.cases) || a.name.localeCompare(b.name));
    const shown = V.top ? pool.slice(0, V.top) : pool;
    const left = all.length - all.filter(a => a.checkable >= MIN_CHECKABLE).length;
    $('#acRankNote').innerHTML = rate
      ? `${esc(LIST_NAME[V.list])} cases per 1,000 records that could be checked. The dashed line is ${esc(scopeName())}.${left ? ` ${n(left)} ${left === 1 ? 'area' : 'areas'} with fewer than ${n(MIN_CHECKABLE)} checkable records ${left === 1 ? 'is' : 'are'} left out.` : ''}`
      : `Number of ${esc(LIST_NAME[V.list])} cases. Larger areas have more records, so compare rates as well.`;
    $('#acRankCount').textContent = `${n(shown.length)} of ${n(pool.length)} ${level === 'district' ? 'districts' : 'States/UTs'}${V.state ? '' : ' · select one to see its districts'}`;
    box.innerHTML = shown.length ? rankChart({ width: vizWidth(box), indicator: rate ? '_per1000' : '_cases', ref: rate && t.rate != null ? { v: t.rate, label: scopeName() } : null,
      label: `${LIST_NAME[V.list]} cases by ${level}, ${rate ? 'rate per 1,000 checkable records' : 'number of cases'}, ${scopeName()}. Exact values are in the All areas table.`,
      items: shown.map(a => ({ key: V.state ? '' : a.key, name: a.name, v: rate ? a.rate : a.cases, focus: false,
        tip: tipHtml(a.name, [{ value: `${n(a.cases)} cases`, label: LIST_NAME[V.list], sub: `${fmtRate(a.rate)} per 1,000 · ${n(a.checkable)} records could be checked · ${n(a.decided)} decided${a.checkable < MIN_CHECKABLE ? ' · few records: rate unstable' : ''}` }]) })) })
      : empty(rate ? `No ${level} has ${n(MIN_CHECKABLE)} records that could be checked.` : 'No case in this selection.');
    roving(box);
  }

  function drawReasons() {
    const t = total(baseRows(), { ...filt(), reason: '' });
    const entries = Object.entries(t.lanes).sort((a, b) => b[1] - a[1]);
    const sum = entries.reduce((s, [, v]) => s + v, 0);
    $('#acReasonSub').textContent = t.cases ? `${n(t.cases)} ${LIST_NAME[V.list]} cases${sum > t.cases ? ' · a case can have more than one reason' : ''}` : '';
    $('#acReasons').innerHTML = entries.length ? `<div class="reasons">${entries.map(([code, c]) => `<button type="button" class="reason-row ${V.reason === code ? 'on' : ''}" data-reason="${esc(code)}" aria-pressed="${V.reason === code}">
        <span class="reason-ic">${icon(reasonIcon(code))}</span><span class="reason-txt"><b>${esc(S.labels.lanes[code] || code)}</b>${REASON_HELP[code] ? `<span>${esc(REASON_HELP[code])}</span>` : ''}</span>
        <span class="reason-num"><b>${n(c)}</b> ${c === 1 ? 'case' : 'cases'}<span>${pct(c, t.cases)}</span></span><span class="reason-bar">${bar(c, t.cases, V.list === 'B' ? 'amber' : 'red')}</span></button>`).join('')}</div>
      <p class="small muted" style="margin:8px 0 0">${V.reason ? 'Select the reason again to show every reason.' : 'Select a reason to filter the page.'}</p>` : empty('No case in this selection.');
  }

  function drawSectors() {
    const sec = caseAgg(baseRows(), { ...filt(), sector: '', key: r => r.sector });
    const items = ['1', '2'].map(s => sec.get(s)).filter(Boolean);
    const max = Math.max(1e-9, ...items.map(g => g.rate || 0));
    $('#acSectors').innerHTML = items.length ? `<div class="hbars">${items.map(g => `<button type="button" class="hbar ${V.sector === g.key ? 'on' : ''}" data-sector="${esc(g.key)}" aria-pressed="${V.sector === g.key}">
        <span class="hbar-name">${esc(sectorName(g.key))}</span><span class="hbar-track">${g.checkable >= MIN_CHECKABLE ? bar(g.rate || 0, max) : '<span class="small muted">few records</span>'}</span>
        <span class="hbar-val">${fmtRate(g.rate)}</span><span class="hbar-sub">${n(g.cases)} of ${n(g.checkable)}</span></button>`).join('')}</div>
      <p class="small muted" style="margin:8px 0 0">Rate per 1,000 · cases of records that could be checked. Select a sector to filter the page.</p>` : empty('No record in this selection.');
  }

  function drawTrend() {
    const box = $('#acTrend');
    if (d.periods.length < 2) { box.innerHTML = empty('This survey round has a single interview period.'); $('#acTrendText').textContent = ''; return; }
    const t = listTrend(baseRows(), d.periods, { reason: V.reason, sector: V.sector });
    $('#acTrendLegend').innerHTML = trendLegend(t.series);
    $('#acTrendSub').textContent = `${d.periods[0].label} – ${d.periods[d.periods.length - 1].label}`;
    box.innerHTML = lineChart({ width: vizWidth(box), height: window.innerWidth < 720 ? 220 : 260, periods: t.periods, series: t.series, indicator: '_per1000', zero: true,
      label: `Cases per 1,000 checkable records by interview period, ${scopeName()}. ${t.summary}`, tipFor: t.tipFor });
    roving(box);
    const lines = ['A', 'B'].map(l => { const ch = periodChange(baseRows(), d.periods, { ...filt(), list: l }); if (!ch) return '';
      const clear = ch.z != null && Math.abs(ch.z) >= CLEAR_Z;
      return `<b>${esc(LIST_NAME[l])}:</b> ${fmtRate(ch.a.g.rate)} → ${fmtRate(ch.b.g.rate)} per 1,000 (${clear ? (ch.z < 0 ? 'a clear fall' : 'a clear rise') : 'no clear change'}).`; }).filter(Boolean);
    $('#acTrendText').innerHTML = lines.join(' ');
  }

  function drawRounds() {
    const rounds = d.rounds || [];
    if (rounds.length < 2) { $('#acRounds').innerHTML = empty('Only this survey round is available on this instance.'); return; }
    $('#acRounds').innerHTML = `${table(['Survey round', { label: 'Records', num: true }, { label: 'Check now', num: true }, { label: 'Budget used', num: true }, { label: 'Per 1,000', num: true }], rounds.map(r => {
      const checkable = r.records - r.not_assessable;
      return `<tr class="${r.run === d.run ? 'current' : ''}"><td><b>${esc(roundName(r.release))}</b>${r.run === d.run ? ' <span class="chip blue">selected</span>' : ''}<div class="small muted">${r.periods?.length ? `${esc(r.periods[0])} – ${esc(r.periods[r.periods.length - 1])}` : ''}</div></td>
        <td class="num">${n(r.records)}</td><td class="num">${n(r.check_now)}</td><td class="num">${r.budget_cases ? pct(r.check_now, r.budget_cases) : '—'}</td><td class="num">${fmtRate(per1000(r.check_now, checkable))}</td></tr>`; }))}
      <p class="small muted" style="margin:10px 0 0">“Budget used” is “Check now” as a share of the review budget; a lower share means less evidence was rare enough to list. Per 1,000 uses records that could be checked. Rounds whose interview periods overlap share records, so they are not independent.</p>`;
  }

  function drawTable() {
    const rows = areaRows();
    const level = V.state ? 'District' : 'State/UT';
    if (!rows) { $('#acTable').innerHTML = '<div class="loading">Loading districts…</div>'; return; }
    const all = [...caseAgg(rows, { ...filt(), key: r => r.area }).values()].sort((a, b) => b.cases - a.cases || a.name.localeCompare(b.name, 'en', { numeric: true }));
    $('#acTableSub').textContent = `${n(all.length)} ${V.state ? 'districts' : 'States/UTs'} · ${scopeName()}`;
    const href = a => `#/worklist?${new URLSearchParams(Object.entries({ tier: V.list, state: V.state || a.key, district: V.state ? a.key : '' }).filter(([, v]) => v))}`;
    $('#acTable').innerHTML = table([level, { label: 'Records that could be checked', num: true }, { label: `${LIST_NAME[V.list]} cases`, num: true }, { label: 'Per 1,000', num: true }, 'Main reason', { label: 'Decided', num: true }, ''],
      all.map(a => { const main = Object.entries(a.lanes).sort((x, y) => y[1] - x[1])[0];
        return `<tr><td>${V.state ? esc(a.name) : `<button type="button" class="linkish" data-focus="${esc(a.key)}">${esc(a.name)}</button>`}</td><td class="num">${n(a.checkable)}</td><td class="num"><b>${n(a.cases)}</b></td>
          <td class="num">${fmtRate(a.rate)}${a.checkable < MIN_CHECKABLE ? ' <span class="chip" title="Fewer than 1,000 records could be checked: the rate is unstable">few records</span>' : ''}</td>
          <td>${main ? esc(S.labels.lanes[main[0]] || main[0]) : '<span class="muted">—</span>'}</td><td class="num">${a.cases ? pct(a.decided, a.cases) : '—'}</td>
          <td class="num">${a.cases ? `<a href="${href(a)}">Worklist</a>` : ''}</td></tr>`; }), { empty: 'No area in this selection.' });
  }

  function drawAll() { syncUrl(); drawScope(); drawStats(); drawInsights(); drawRank(); drawReasons(); drawSectors(); drawTrend(); drawRounds(); drawTable(); }
  async function setState(code) {
    V.state = code; $('#acState').value = code;
    if (code && !districts.has(code)) {
      drawAll();
      try { const r = await api(url('/api/case-areas', { run: S.run, state: code })); districts.set(code, r.available ? r.rows : []); }
      catch (e) { districts.set(code, []); notice(e.message, 'error'); }
      if (V.state !== code || !document.body.contains(root)) return;
    }
    drawAll();
  }
  root.addEventListener('click', e => {
    const t = e.target.closest('button, [data-focus]');
    if (!t || !root.contains(t)) return;
    const segEl = t.closest('[data-seg]');
    if (segEl && t.dataset.v != null) {
      const k = segEl.dataset.seg; V[k] = k === 'top' ? Number(t.dataset.v) : t.dataset.v;
      segEl.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b === t)));
      if (k === 'top' || k === 'measure') { syncUrl(); drawRank(); } else drawAll();
      return;
    }
    if (t.dataset.reason) { V.reason = V.reason === t.dataset.reason ? '' : t.dataset.reason; $('#acReason').value = V.reason; drawAll(); }
    else if (t.dataset.sector != null) { V.sector = V.sector === t.dataset.sector ? '' : t.dataset.sector; root.querySelectorAll('[data-seg="sector"] button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.v === V.sector))); drawAll(); }
    else if (t.dataset.clear) {
      if (t.dataset.clear === 'state') { setState(''); return; }
      V[t.dataset.clear] = '';
      if (t.dataset.clear === 'reason') $('#acReason').value = '';
      root.querySelectorAll(`[data-seg="${t.dataset.clear}"] button`).forEach(b => b.setAttribute('aria-pressed', String(b.dataset.v === '')));
      drawAll();
    } else if (t.id === 'acReset') { go('#/areas'); }
    else if (t.dataset.focus) { setState(t.dataset.focus); window.scrollTo({ top: 0 }); }
  });
  root.addEventListener('keydown', e => { const t = e.target.closest?.('g[data-focus]'); if (t && t.dataset.focus && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); setState(t.dataset.focus); } });
  $('#acReason').onchange = e => { V.reason = e.target.value; drawAll(); };
  $('#acState').onchange = e => setState(e.target.value);
  vizRedraw = () => { if (document.body.contains(root)) { drawRank(); drawTrend(); } };
  await setState(V.state);
}

/* ------------------------------------------------------------ areas */

const INDICATOR_UNIT = { lfpr_cws_15plus: 'share', wpr_cws_15plus: 'share', ur_cws_15plus: 'share', median_salaried_earnings: 'rupees', mean_day7_hours_workers: 'hours',
  _cases: 'count', _per1000: 'per1000' };   // the last two are the case counts and rates of Cases by area
function indicatorValue(indicator, v) {
  if (v == null) return '—';
  const u = INDICATOR_UNIT[indicator];
  if (u === 'count') return n(Math.round(v));
  if (u === 'per1000') return Number(v).toFixed(1);
  return u === 'share' ? `${(v * 100).toFixed(1)}%` : u === 'rupees' ? money(v) : `${Number(v).toFixed(1)} h`;
}
// A change of a share is in percentage points; rupees and hours keep their unit.
function changeValue(indicator, v) {
  if (v == null) return '—';
  const sign = v > 0 ? '+' : v < 0 ? '−' : '';
  return INDICATOR_UNIT[indicator] === 'share' ? `${sign}${Math.abs(v * 100).toFixed(Math.abs(v) < 0.001 ? 2 : 1)} pp` : `${sign}${indicatorValue(indicator, Math.abs(v))}`;
}
const SECTOR_NAME = { 1: 'Rural', 2: 'Urban' };
const sectorName = s => SECTOR_NAME[s] || (s ? `Sector ${s}` : 'Combined');
const placeKey = r => `${r.state || ''}|${r.district || ''}`;
const placeName = r => (r.state ? String(r.area_label || '').split(' · ').slice(0, -1).join(' · ') || r.area_label : 'All India');
const seOf = r => r?.design_standard_error ?? r?.srs_standard_error ?? null;
// Display rule for "low precision" (screening only): any one of these makes an estimate indicative, never solid.
const PRECISION = { rse: 0.25, deff: 5, persons: 100 };
function precisionIssues(r) {
  if (!r || r.value == null) return [];
  const out = [];
  const se = seOf(r);
  if (r.design_standard_error == null) out.push('no design-based standard error');
  if (se != null && (r.value === 0 ? se > 0 : se / Math.abs(r.value) > PRECISION.rse)) out.push(`standard error above ${PRECISION.rse * 100}% of the value`);
  if (r.design_effect != null && r.design_effect > PRECISION.deff) out.push(`design effect above ${PRECISION.deff}`);
  if (r.persons_15plus != null && r.persons_15plus < PRECISION.persons) out.push(`fewer than ${PRECISION.persons} persons aged 15+`);
  return out;
}
const precisionNote = `Low precision when any of: no design-based standard error, standard error above ${PRECISION.rse * 100}% of the value, design effect above ${PRECISION.deff}, or fewer than ${PRECISION.persons} persons aged 15+. Read such estimates as indicative only.`;
const LEVEL_NAME = { national: 'National', state: 'State/UT', district: 'District' };

async function areaIndicators(_, params) {
  crumbs(['Area trends']);
  const level = params.get('level') || 'state';
  const indicator = params.get('indicator') || 'ur_cws_15plus';
  // All India rows give the reference line and the default focus at State and District level (same endpoint, national level).
  const [data, nat] = await Promise.all([api(url('/api/aggregates', { run: S.run, level, indicator, limit: 5000 })),
    level === 'national' ? null : api(url('/api/aggregates', { run: S.run, level: 'national', indicator, limit: 5000 })).catch(() => null)]);
  const head = pageHead({ eyebrow: 'Context', title: 'Area trends',
    lede: 'Weighted current-weekly-status indicators from first-visit records, with notable period-on-period changes. Screening values, not official PLFS estimates.' }) + areaTabs('indicators');
  if (!data.available) { app.innerHTML = head + empty('No historical run is attached to this survey round.'); return; }

  /* ---- index the rows: area = place (State/UT, district) × sector; one row per period */
  const indLabel = (data.indicators.find(i => i.indicator === indicator) || {}).indicator_label || indicator;
  const natRows = level === 'national' ? [] : (nat?.available ? nat.rows : []);
  const periods = [...new Map([...data.rows, ...natRows].map(r => [r.period_index, r.period_label])).entries()].sort((a, b) => a[0] - b[0]);
  const lastIdx = data.rows.length ? Math.max(...data.rows.map(r => r.period_index)) : null;
  const last = (periods.find(p => p[0] === lastIdx) || [])[1] || '';
  const series = new Map();
  [...data.rows, ...natRows].forEach(r => { const k = `${placeKey(r)}#${r.sector}`; if (!series.has(k)) series.set(k, new Map()); series.get(k).set(r.period_index, r); });
  const get = (place, sector, pi) => series.get(`${place}#${sector}`)?.get(pi);
  const latestOf = (place, sector) => { for (let i = periods.length - 1; i >= 0; i -= 1) { const r = get(place, sector, periods[i][0]); if (r && r.value != null) return r; } return null; };
  const places = new Map();
  data.rows.forEach(r => { if (!places.has(placeKey(r))) places.set(placeKey(r), { key: placeKey(r), name: placeName(r) }); });
  const hasNat = level === 'national' || natRows.length > 0;
  if (hasNat && !places.has('|')) places.set('|', { key: '|', name: 'All India' });
  const placeList = [...places.values()].filter(p => p.key !== '|').sort((a, b) => a.name.localeCompare(b.name, 'en', { numeric: true }));
  const sectors = [...new Set(data.rows.map(r => r.sector))].sort();
  const truncated = data.rows.length >= 5000;
  const notable = data.notable || [];

  /* ---- view state (client-side only; level and indicator stay in the URL through the #af form) */
  const wanted = params.get('area');
  const V = {
    sector: sectors.includes(params.get('sector')) ? params.get('sector') : sectors.includes('1') ? '1' : sectors[0],
    focus: wanted != null && places.has(wanted) ? wanted : hasNat ? '|' : (placeList[0]?.key || ''),
    compare: [], q: '', top: 15, order: 'desc', sm: 'value',
    board: { ind: 'all', level: 'all', period: '', sort: 'strength' },
  };
  const nameOf = key => places.get(key)?.name || 'All India';
  const fmtSe = r => (seOf(r) == null ? 'no standard error' : `± ${indicatorValue(indicator, 1.96 * seOf(r))} (95%)`);
  const rowTip = (title, r) => tipHtml(title, [{ value: indicatorValue(indicator, r?.value), label: `${sectorName(r?.sector)} · ${r?.period_label || ''}`,
    sub: r ? `${fmtSe(r)} · ${n(r.persons_15plus)} persons 15+${r.change != null ? ` · change ${changeValue(indicator, r.change)}` : ''}${precisionIssues(r).length ? ' · low precision' : ''}${r.notable_change ? ' · unusual change' : ''}` : '' }]);

  const multiSector = sectors.length > 1;
  app.innerHTML = `${head}<div id="at">
    <div class="toolbar at-controls">
      <form class="filters" id="af"><input type="hidden" name="view" value="indicators"><label>Level <select name="level">${['national', 'state', 'district'].map(l => `<option value="${l}" ${l === level ? 'selected' : ''}>${l[0].toUpperCase() + l.slice(1)}</option>`).join('')}</select></label>
        <label>Indicator <select name="indicator">${data.indicators.map(i => `<option value="${esc(i.indicator)}" ${i.indicator === indicator ? 'selected' : ''}>${esc(i.indicator_label)}</option>`).join('')}</select></label><div class="actions"><button>Show</button></div></form>
      <span class="sep" aria-hidden="true"></span>
      <div class="filters">
        ${multiSector ? `<div class="ctl" role="group" aria-label="Sector"><span aria-hidden="true">Sector</span><div class="seg" id="atSector">${sectors.map(s => `<button type="button" data-sector="${esc(s)}" aria-pressed="${s === V.sector}">${esc(sectorName(s))}</button>`).join('')}</div></div>` : ''}
        ${level === 'national' ? '' : `<label class="ctl">Area in focus <select class="field" id="atFocus">${hasNat ? '<option value="|">All India</option>' : ''}${placeList.map(p => `<option value="${esc(p.key)}">${esc(p.name)}</option>`).join('')}</select></label>`}
      </div>
    </div>
    ${truncated ? infoBox(`<b>Only the first ${n(data.rows.length)} rows were returned</b> (the page limit), in State/UT and district order, so areas late in that order are missing from these views.`, 'amber') : ''}
    <section class="kpis" id="atKpis" aria-label="Headline figures"></section>
    <div class="at-grid">
      <div class="panel">${panelHead(`${indLabel} over time`, 'map', '<span class="small muted" id="atTrendSub"></span>')}
        <div class="legend" id="atTrendLegend"></div>
        <div class="viz-box" id="atTrend"></div>
        ${level === 'national' ? '' : `<div class="compare" id="atCompare" style="margin-top:10px"></div>`}
        <p class="small muted" style="margin:10px 0 0">The shaded band is ±1.96 × the design-based standard error (falls back to the simple-random-sampling error when no design-based one exists). Use the arrow keys on the chart to read each period.</p>
      </div>
      <div class="panel">${panelHead(level === 'national' ? `Rural and urban — ${last}` : `Spread of areas — ${last}`, 'group', '<span class="small muted">all sectors</span>')}
        <div class="viz-box fill" id="atSpread"></div>
        <p class="small muted" style="margin:8px 0 0">${level === 'national' ? 'Bars show the value; whiskers show ±1.96 × standard error.' : 'Each dot is one area; the bar marks the median. The highlighted dot is the area in focus.'}</p>
      </div>
    </div>
    <div class="panel">${panelHead('Unusual period-on-period changes', 'alert', `<span class="small muted">${n(notable.length)} ${notable.length === 1 ? 'change' : 'changes'}${notable.length > 100 ? ' · first 100 shown' : ''}</span>`)}
      <p class="small muted">A change is shown when it stands out from the other areas' changes in the same period <i>and</i> exceeds three standard errors of the change. Changes listed by HSD as known events are marked as expected instead.</p>
      ${notable.length ? `<div class="board-tools">
        <div class="fchips" role="group" aria-label="Indicator" id="bInd"></div>
        <div class="fchips" role="group" aria-label="Level" id="bLevel"></div>
        <label class="ctl" style="flex-direction:row;align-items:center;gap:8px">Period <select class="field" id="bPeriod"><option value="">All</option>${[...new Map(notable.map(a => [a.period_index, a.period_label])).entries()].sort((a, b) => a[0] - b[0]).map(([, l]) => `<option value="${esc(l)}">${esc(l)}</option>`).join('')}</select></label>
        <label class="ctl" style="flex-direction:row;align-items:center;gap:8px;margin-left:auto">Sort <select class="field" id="bSort"><option value="strength">Largest change ÷ SE</option><option value="screen">Screening order</option><option value="recent">Most recent</option><option value="area">Area</option></select></label></div>` : ''}
      <div id="atBoard"></div></div>
    ${level === 'national' ? '' : `<div class="toolbar" style="align-items:center">
        <label class="ctl grow" style="flex:1 1 220px">Find an area <input class="field" type="search" id="atQ" placeholder="State/UT or district" autocomplete="off"></label>
        <div class="ctl" role="group" aria-label="How many areas"><span aria-hidden="true">Show</span><div class="seg" id="atTop">${[[15, 'Top 15'], [30, 'Top 30'], [0, 'All']].map(([v, l]) => `<button type="button" data-top="${v}" aria-pressed="${v === V.top}">${l}</button>`).join('')}</div></div>
        <div class="ctl" role="group" aria-label="Order"><span aria-hidden="true">Order</span><div class="seg" id="atOrder"><button type="button" data-order="desc" aria-pressed="true">Highest first</button><button type="button" data-order="asc" aria-pressed="false">Lowest first</button></div></div>
        <span class="small muted" id="atCount"></span></div>
      <div class="panel">${panelHead(`Areas ranked — ${last}`, 'list', '<span class="small muted" id="atRankSub"></span>')}
        <div class="legend"><span><i class="k-sw" style="background:${VIZ.series[0]}"></i>value</span><span><i class="k-sw" style="background:#fff;outline:1px solid ${VIZ.series[0]};background-image:repeating-linear-gradient(45deg,${VIZ.series[0]} 0 1.5px,#fff 1.5px 4px)"></i>low precision</span><span><i class="k-ref"></i>All India (same sector)</span><span><i class="k-line" style="background:var(--ink-2);height:1.5px"></i>±1.96 × SE</span></div>
        <div class="viz-box tall" id="atRank"></div></div>
      <div class="panel">${panelHead('Change heatmap', 'clock', '<span class="small muted">areas × periods</span>')}
        <div class="legend">${divLegend()}</div>
        <div class="viz-box tall scroll" id="atHeat"></div>
        <p class="small muted" style="margin:8px 0 0">Colour shows each period's change divided by its design-based standard error, so small, noisy areas do not dominate. Rows follow the ranking above. Focus the map and use the arrow keys to read each cell.</p></div>
      <div class="panel">${panelHead('Small multiples', 'group', `<label class="ctl" style="flex-direction:row;align-items:center;gap:8px">Sort by <select class="field" id="atSm"><option value="value">Latest value</option><option value="change">Latest change</option><option value="vol">Volatility</option></select></label>`)}
        <p class="small muted" style="margin:-4px 0 12px">One line per area over all periods, each on its own scale. Volatility is the spread (standard deviation) of period-on-period changes. Choose a card to put it in focus.</p>
        <div class="sm-grid" id="atSmGrid"></div></div>`}
    <div class="panel">${panelHead(`${indLabel} — ${last || ''}`, 'map', '<span class="small muted">every area this period</span>')}
      <div id="atTable"></div>
      <div class="about" style="margin-top:12px">
        <p class="small muted">Standard errors are design-based (FSU as primary sampling unit within strata).</p>
        <p class="small muted">${esc(precisionNote)}</p>
        ${(data.limitations || []).map(l => `<p class="small muted">${esc(l)}</p>`).join('')}
        ${data.periods?.length ? `<p class="small muted">Periods compared: ${esc(data.periods[0])} – ${esc(data.periods[data.periods.length - 1])}${data.design_period ? ` · sample design ${esc(data.design_period)}` : ''}.</p>` : ''}
      </div></div>
  </div>`;
  document.querySelector('#af').onsubmit = e => { e.preventDefault(); go(`#/areas?${new URLSearchParams(Object.fromEntries(new FormData(e.target)))}`); };
  const root = document.querySelector('#at');
  const $ = sel => root.querySelector(sel);

  /* ---- 1. headline strip */
  function drawKpis() {
    const r = latestOf(V.focus, V.sector);
    const low = precisionIssues(r);
    const z = r?.change_over_design_se;
    const arrow = r?.change > 0 ? '▲' : r?.change < 0 ? '▼' : '';
    const unusualNow = notable.filter(a => a.indicator === indicator && a.level === level && a.period_index === lastIdx).length;
    const unusualAll = notable.filter(a => a.indicator === indicator && a.level === level).length;
    const latestRows = data.rows.filter(x => x.period_index === lastIdx && x.value != null);
    const lowCount = latestRows.filter(x => precisionIssues(x).length).length;
    const kpi = (icon_, lbl, value, sub) => `<div class="kpi"><span class="kpi-label">${icon(icon_)}${lbl}</span><span class="kpi-value">${value}</span><span class="kpi-sub">${sub}</span></div>`;
    $('#atKpis').innerHTML = [
      kpi('map', `${esc(nameOf(V.focus))} · ${esc(sectorName(V.sector))}`, `${esc(indicatorValue(indicator, r?.value))}${low.length ? '<span class="prec" title="' + esc(low.join('; ')) + '">low precision</span>' : ''}`,
        r ? `${esc(r.period_label)} · ${esc(fmtSe(r))}` : 'No value for this area'),
      kpi('arrow', 'Change vs previous period', r?.change == null ? '—' : `${esc(changeValue(indicator, r.change))}<span class="delta" aria-hidden="true">${arrow}</span>`,
        r?.change == null ? (r?.change_reason ? esc(`Not comparable: ${String(r.change_reason).toLowerCase().replace(/_/g, ' ')}`) : 'No earlier period to compare') : `vs ${esc(periods[periods.findIndex(p => p[0] === r.period_index) - 1]?.[1] || 'previous period')} (${esc(indicatorValue(indicator, r.previous_value))})${z == null ? '' : ` · ${Number(z).toFixed(1)} × SE of the change`}`),
      kpi('alert', `Unusual changes · ${esc(last)}`, n(unusualNow), `${n(unusualAll)} for this indicator at ${esc(LEVEL_NAME[level])} level · ${n(notable.length)} in all`),
      kpi('group', 'Areas covered', n(new Set(latestRows.map(x => `${placeKey(x)}#${x.sector}`)).size), `${esc(LEVEL_NAME[level])} × sector in ${esc(last)} · ${n(lowCount)} low precision${truncated ? ' · list truncated' : ''}`),
    ].join('');
  }

  /* ---- 2. trend chart */
  function drawTrend() {
    const list = [V.focus, ...V.compare];
    const sets = V.compare.length || !multiSector
      ? list.map((p, i) => ({ place: p, sector: V.sector, name: `${nameOf(p)}${multiSector ? ` · ${sectorName(V.sector)}` : ''}`, color: VIZ.series[i], band: i === 0, endLabel: i === 0 }))
      : [{ place: V.focus, sector: V.sector, name: `${nameOf(V.focus)} · ${sectorName(V.sector)}`, color: VIZ.series[0], band: true, endLabel: true },
        ...sectors.filter(s => s !== V.sector).map((s, i) => ({ place: V.focus, sector: s, name: `${nameOf(V.focus)} · ${sectorName(s)}`, color: VIZ.series[i + 1], dash: true }))];
    const chartSeries = sets.map(s => ({ ...s, points: periods.map(([pi]) => { const r = get(s.place, s.sector, pi); return r ? { v: r.value, se: seOf(r), low: precisionIssues(r).length > 0, notable: !!r.notable_change, expected: !!r.expected_change_known_event, row: r } : { v: null }; }) }));
    const used = chartSeries.flatMap(s => s.points);
    $('#atTrendLegend').innerHTML = chartSeries.map(s => `<span><i class="${s.dash ? 'k-dash' : 'k-line'}" style="${s.dash ? `border-color:${s.color}` : `background:${s.color}`}"></i>${esc(s.name)}</span>`).join('')
      + `<span><i class="k-band" style="background:${VIZ.series[0]}"></i>95% band</span>`
      + (used.some(p => p.notable) ? '<span><i class="k-ring"></i>unusual change</span>' : '')
      + (used.some(p => p.expected) ? '<span><i class="k-ring" style="border-style:dashed"></i>expected (known event)</span>' : '')
      + (used.some(p => p.low) ? '<span><i class="k-low"></i>low precision</span>' : '');
    $('#atTrendSub').textContent = periods.length ? `${periods.length} ${periods.length === 1 ? 'period' : 'periods'} · ${periods[0][1]}${periods.length > 1 ? ` – ${periods[periods.length - 1][1]}` : ''}` : '';
    const box = $('#atTrend');
    box.innerHTML = periods.length ? lineChart({ width: vizWidth(box), height: window.innerWidth < 720 ? 230 : 290, periods, series: chartSeries, indicator,
      label: `${indLabel}, ${chartSeries.map(s => s.name).join(', ')}, by period. Values are listed in the table below and on each period's tooltip.`,
      tipFor: (pi, lbl) => tipHtml(lbl, chartSeries.map(s => { const p = s.points[periods.findIndex(x => x[0] === pi)]; const r = p.row;
        return { color: s.color, value: indicatorValue(indicator, p.v), label: s.name,
          sub: r ? [fmtSe(r), `${n(r.persons_15plus)} persons 15+`, p.low ? 'low precision' : '', p.notable ? 'unusual change' : '', p.expected ? 'expected (known event)' : ''].filter(Boolean).join(' · ') : 'no value' }; })) })
      : empty('No period is available for this indicator.');
    roving(box);
    const cmp = $('#atCompare');
    if (cmp) {
      const options = placeList.filter(p => p.key !== V.focus && !V.compare.includes(p.key));
      cmp.innerHTML = `<span class="small muted">Compare:</span>${V.compare.map((k, i) => `<span class="cmp-chip"><i style="background:${VIZ.series[i + 1]}"></i>${esc(nameOf(k))}<button type="button" data-uncompare="${esc(k)}" aria-label="Remove ${esc(nameOf(k))} from the comparison">×</button></span>`).join('')}
        ${V.compare.length < 3 ? `<select class="field" id="atAdd" aria-label="Add an area to compare" style="height:30px;max-width:240px"><option value="">Add an area…</option>${options.map(p => `<option value="${esc(p.key)}">${esc(p.name)}</option>`).join('')}</select>` : '<span class="small muted">up to 4 areas</span>'}`;
      $('#atAdd')?.addEventListener('change', e => { if (e.target.value) { V.compare.push(e.target.value); drawTrend(); drawSpread(); $('#atAdd')?.focus(); } });
    }
  }

  /* ---- spread (State/District) or rural/urban bars (national) */
  function drawSpread() {
    const box = $('#atSpread');
    box.innerHTML = '';  // measure the space the stretched card leaves once the old chart is gone
    const fill = box.clientHeight;
    if (level === 'national') {
      const items = sectors.map((s, i) => { const r = latestOf('|', s); return { name: sectorName(s), v: r?.value, se: seOf(r), low: precisionIssues(r).length > 0, color: VIZ.series[i], tip: rowTip(`All India · ${sectorName(s)}`, r) }; });
      box.innerHTML = rankChart({ width: vizWidth(box), items, indicator, label: `${indLabel}, rural and urban, ${last}: ${items.map(i => `${i.name} ${indicatorValue(indicator, i.v)}`).join(', ')}`, rowH: 34 });
    } else {
      const groups = sectors.map(s => ({ name: sectorName(s), values: [...places.values()].filter(p => p.key !== '|').map(p => ({ name: p.name, v: get(p.key, s, lastIdx)?.value, focus: p.key === V.focus })) }));
      const summary = groups.map(g => `${g.name}: median ${indicatorValue(indicator, median(g.values.map(v => v.v)))} across ${g.values.filter(v => v.v != null).length} areas`).join('; ');
      box.innerHTML = spreadChart({ width: vizWidth(box), height: fill, groups, indicator, label: `${indLabel} by area, ${last}. ${summary}.` });
    }
    roving(box);
  }

  /* ---- 3. unusual-changes board */
  function drawBoard() {
    const board = $('#atBoard');
    if (!notable.length) { board.innerHTML = empty('No unusual change.'); return; }
    const B = V.board;
    const count = pred => notable.filter(pred).length;
    const indicators = [...new Set(notable.map(a => a.indicator))];
    $('#bInd').innerHTML = [['all', 'All indicators', notable.length], ...indicators.map(k => [k, (data.indicators.find(i => i.indicator === k) || {}).indicator_label || notable.find(a => a.indicator === k).indicator_label, count(a => a.indicator === k)])]
      .map(([k, l, c]) => `<button type="button" class="fchip" data-bind="${esc(k)}" aria-pressed="${B.ind === k}">${esc(trunc(String(l).replace(/ \(CWS, age 15\+\)| of salaried workers \(₹\)/g, ''), 34))} <span class="cnt">${n(c)}</span></button>`).join('');
    const levels = ['national', 'state', 'district'].filter(l => notable.some(a => a.level === l));
    $('#bLevel').innerHTML = [['all', 'All levels'], ...levels.map(l => [l, LEVEL_NAME[l]])].map(([k, l]) => `<button type="button" class="fchip" data-blevel="${k}" aria-pressed="${B.level === k}">${esc(l)}</button>`).join('');
    let rows = notable.filter(a => (B.ind === 'all' || a.indicator === B.ind) && (B.level === 'all' || a.level === B.level) && (!B.period || a.period_label === B.period));
    const absZ = a => Math.abs(a.change_over_design_se ?? 0);
    if (B.sort === 'strength') rows = rows.slice().sort((a, b) => absZ(b) - absZ(a));
    else if (B.sort === 'recent') rows = rows.slice().sort((a, b) => b.period_index - a.period_index || absZ(b) - absZ(a));
    else if (B.sort === 'area') rows = rows.slice().sort((a, b) => String(a.area_label).localeCompare(String(b.area_label), 'en', { numeric: true }));
    const maxZ = Math.max(4, ...rows.map(absZ));
    const domains = {};
    notable.forEach(a => { const d = domains[a.indicator] || (domains[a.indicator] = [Infinity, -Infinity]); [a.value, a.previous_value].forEach(v => { if (v != null) { d[0] = Math.min(d[0], v); d[1] = Math.max(d[1], v); } }); });
    const dumbbell = a => {
      const [lo, hi] = domains[a.indicator]; const pad = (hi - lo) * 0.06 || 1; const x = vscale(lo - pad, hi + pad, 6, 134);
      if (a.previous_value == null || a.value == null) return '';
      const x0 = x(a.previous_value), x1 = x(a.value);
      return `<svg class="dumb" width="140" height="16" viewBox="0 0 140 16" aria-hidden="true"><line class="d-line" x1="${x0.toFixed(1)}" x2="${x1.toFixed(1)}" y1="8" y2="8"/><circle class="d-prev" cx="${x0.toFixed(1)}" cy="8" r="4.5"/><circle class="d-now" cx="${x1.toFixed(1)}" cy="8" r="5"/></svg>`;
    };
    const trendHref = a => `#/areas?${new URLSearchParams({ view: 'indicators', level: a.level, indicator: a.indicator, area: placeKey(a), sector: a.sector })}`;
    board.innerHTML = table(['Area', 'Indicator · period', 'Before → Now', { label: 'Change ÷ SE', num: true }], rows.slice(0, 100).map(a => {
      const z = a.change_over_design_se;
      return `<tr><td><a href="${trendHref(a)}" title="Show this area's trend">${esc(a.area_label)}</a><div class="small muted">${esc(LEVEL_NAME[a.level] || a.level)}${a.expected_change_known_event ? ` ${chip('Expected (known event)', 'blue')}` : ''}</div></td>
        <td>${esc(a.indicator_label)}<div class="small muted">${esc(a.period_label)}</div></td>
        <td><div class="dumb-cell">${dumbbell(a)}<span class="dumb-vals">${esc(indicatorValue(a.indicator, a.previous_value))} → <b>${esc(indicatorValue(a.indicator, a.value))}</b> <span class="muted">(${esc(changeValue(a.indicator, a.change))})</span></span></div></td>
        <td class="num"><div class="mag"><span class="mag-bar" aria-hidden="true"><i style="width:${(Math.min(1, Math.abs(z ?? 0) / maxZ) * 100).toFixed(1)}%"></i><s style="left:${((3 / maxZ) * 100).toFixed(1)}%" title="3 standard errors"></s></span><b>${z == null ? '—' : `${z > 0 ? '+' : z < 0 ? '−' : ''}${Math.abs(z).toFixed(1)}`}</b></div></td></tr>`;
    }), { empty: 'No unusual change matches these filters.' })
      + `<p class="small muted" style="margin-top:8px">${n(Math.min(rows.length, 100))} of ${n(rows.length)} shown. Before → Now: hollow dot is the previous period, filled dot is the period of the change; the bar shows the change in standard errors, with the mark at 3.</p>`;
  }

  /* ---- 4–6. ranking, heatmap and small multiples share one filtered, ordered list of places */
  function shownPlaces() {
    const q = V.q.trim().toLowerCase();
    const list = placeList.filter(p => !q || p.name.toLowerCase().includes(q))
      .map(p => ({ ...p, r: get(p.key, V.sector, lastIdx) }))
      .sort((a, b) => (a.r?.value == null) - (b.r?.value == null) || (V.order === 'asc' ? 1 : -1) * ((a.r?.value ?? 0) - (b.r?.value ?? 0)));
    return { all: list, shown: V.top ? list.slice(0, V.top) : list };
  }
  function drawRank() {
    const { all, shown } = shownPlaces();
    $('#atCount').textContent = `${n(shown.length)} of ${n(all.length)} areas · ${sectorName(V.sector)}`;
    const natR = get('|', V.sector, lastIdx);
    $('#atRankSub').textContent = `${sectorName(V.sector)} · ${V.order === 'asc' ? 'lowest' : 'highest'} first`;
    const box = $('#atRank');
    box.innerHTML = rankChart({ width: vizWidth(box), indicator, ref: natR ? { v: natR.value, label: 'All India' } : null,
      label: `${indLabel} by area, ${last}, ${sectorName(V.sector)}. ${shown.length} areas shown; values are also in the table below.`,
      items: shown.map(p => ({ key: p.key, name: p.name, v: p.r?.value, se: seOf(p.r), low: precisionIssues(p.r).length > 0, focus: p.key === V.focus,
        tip: rowTip(p.name, p.r) + (precisionIssues(p.r).length ? `<div class="t-sub">${esc(precisionIssues(p.r).join('; '))}</div>` : '') })) });
    roving(box);
    const heat = $('#atHeat');
    heat.innerHTML = heatmap({ width: vizWidth(heat), periods, label: `Change divided by its standard error, ${shown.length} areas by ${periods.length} periods, ${sectorName(V.sector)}.`,
      rows: shown.map(p => ({ key: p.key, name: p.name, focus: p.key === V.focus })),
      cell: (row, pi, lbl) => { const r = get(row.key, V.sector, pi); const z = r?.change_over_design_se;
        return { z, present: !!r, notable: !!r?.notable_change,
          tip: tipHtml(`${row.name} · ${lbl}`, [{ value: r?.change == null ? 'not assessable' : changeValue(indicator, r.change), label: z == null ? '' : `${Number(z).toFixed(1)} × SE`,
            sub: r ? `${indicatorValue(indicator, r.previous_value)} → ${indicatorValue(indicator, r.value)}${r.notable_change ? ' · unusual change' : ''}${precisionIssues(r).length ? ' · low precision' : ''}` : 'no value' }]) }; } });
    roving(heat);
    drawSm(all);
  }
  function drawSm(all) {
    const stats = all.map(p => {
      const vals = periods.map(([pi]) => get(p.key, V.sector, pi)?.value ?? null);
      const changes = periods.map(([pi]) => get(p.key, V.sector, pi)?.change).filter(c => c != null);
      const mean = changes.reduce((s, c) => s + c, 0) / (changes.length || 1);
      const vol = changes.length > 1 ? Math.sqrt(changes.reduce((s, c) => s + (c - mean) ** 2, 0) / (changes.length - 1)) : null;
      return { ...p, vals, vol };
    });
    const key = { value: s => s.r?.value, change: s => (s.r?.change == null ? null : Math.abs(s.r.change)), vol: s => s.vol }[V.sm];
    stats.sort((a, b) => (key(a) == null) - (key(b) == null) || (key(b) ?? 0) - (key(a) ?? 0));
    const shown = V.top ? stats.slice(0, V.top) : stats;
    $('#atSmGrid').innerHTML = shown.map(s => `<button type="button" class="sm ${s.key === V.focus ? 'focus' : ''}" data-focus="${esc(s.key)}" aria-label="${esc(`${s.name}: ${indicatorValue(indicator, s.r?.value)}, change ${changeValue(indicator, s.r?.change)}. Put in focus.`)}">
        <span class="sm-name" title="${esc(s.name)}">${esc(s.name)}</span>
        <span class="sm-row"><span class="sm-val">${esc(indicatorValue(indicator, s.r?.value))}</span><span class="sm-chg">${esc(changeValue(indicator, s.r?.change))}${s.vol == null ? '' : ` · σ ${esc(changeValue(indicator, s.vol).replace(/^\+/, ''))}`}</span></span>
        ${sparkline(s.vals, { w: 166, lowLast: precisionIssues(s.r).length > 0 })}${precisionIssues(s.r).length ? '<span class="prec" style="align-self:flex-start;margin-top:4px">low precision</span>' : ''}</button>`).join('') || empty('No area matches.');
  }

  /* ---- values table (all sectors, latest period) */
  function drawTable() {
    const q = V.q.trim().toLowerCase();
    const rows = data.rows.filter(r => r.period_index === lastIdx && (!q || String(r.area_label).toLowerCase().includes(q)));
    $('#atTable').innerHTML = table(['Area', { label: 'Value', num: true }, { label: 'Design SE', num: true }, { label: 'Design effect', num: true }, { label: 'Change', num: true }, { label: 'Persons 15+', num: true }, 'Precision'], rows.map(r =>
      `<tr><td>${esc(r.area_label)}</td><td class="num">${esc(indicatorValue(indicator, r.value))}</td><td class="num">${esc(indicatorValue(indicator, r.design_standard_error ?? r.srs_standard_error))}</td>
       <td class="num">${r.design_effect == null ? '—' : Number(r.design_effect).toFixed(2)}</td><td class="num">${r.change == null ? '—' : esc(changeValue(indicator, r.change))}</td><td class="num">${n(r.persons_15plus)}</td>
       <td>${precisionIssues(r).length ? `<span class="prec" title="${esc(precisionIssues(r).join('; '))}">low precision</span>` : ''}</td></tr>`));
  }

  function drawAll() { drawKpis(); drawTrend(); drawSpread(); drawBoard(); if (level !== 'national') drawRank(); drawTable(); }
  const setFocus = key => { V.focus = key; V.compare = V.compare.filter(k => k !== key); const sel = $('#atFocus'); if (sel) sel.value = key; drawKpis(); drawTrend(); drawSpread(); if (level !== 'national') drawRank(); };
  drawAll();
  const focusSel = $('#atFocus');
  if (focusSel) { focusSel.value = V.focus; focusSel.onchange = () => setFocus(focusSel.value); }
  root.addEventListener('click', e => {
    const t = e.target.closest('button, [data-focus]');
    if (!t || !root.contains(t)) return;
    if (t.dataset.sector) { V.sector = t.dataset.sector; root.querySelectorAll('[data-sector]').forEach(b => b.setAttribute('aria-pressed', String(b === t))); drawKpis(); drawTrend(); if (level !== 'national') drawRank(); }
    else if (t.dataset.top != null) { V.top = Number(t.dataset.top); root.querySelectorAll('[data-top]').forEach(b => b.setAttribute('aria-pressed', String(b === t))); drawRank(); }
    else if (t.dataset.order) { V.order = t.dataset.order; root.querySelectorAll('[data-order]').forEach(b => b.setAttribute('aria-pressed', String(b === t))); drawRank(); }
    else if (t.dataset.bind) { V.board.ind = t.dataset.bind; drawBoard(); }
    else if (t.dataset.blevel) { V.board.level = t.dataset.blevel; drawBoard(); }
    else if (t.dataset.uncompare) { V.compare = V.compare.filter(k => k !== t.dataset.uncompare); drawTrend(); drawSpread(); }
    else if (t.dataset.focus != null) setFocus(t.dataset.focus);
  });
  root.addEventListener('keydown', e => { const t = e.target.closest?.('g[data-focus]'); if (t && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); setFocus(t.dataset.focus); } });
  $('#bPeriod')?.addEventListener('change', e => { V.board.period = e.target.value; drawBoard(); });
  $('#bSort')?.addEventListener('change', e => { V.board.sort = e.target.value; drawBoard(); });
  $('#atSm')?.addEventListener('change', e => { V.sm = e.target.value; drawRank(); });
  let qTimer;
  $('#atQ')?.addEventListener('input', e => { clearTimeout(qTimer); qTimer = setTimeout(() => { V.q = e.target.value; drawRank(); drawTable(); }, 160); });
  vizRedraw = () => { if (document.body.contains(root)) { drawTrend(); drawSpread(); if (level !== 'national') drawRank(); } };
}

// Share of each decision among the rows shown (counts of the stored decisions; nothing else).
function decisionMix(rows) {
  const counts = {};
  rows.forEach(x => { counts[x.decision] = (counts[x.decision] || 0) + 1; });
  const parts = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const tone = k => DECISION_CHIP[k] || 'none';
  return `<div class="panel"><div class="stack" role="img" aria-label="${esc(parts.map(([k, v]) => `${S.labels.decisions[k] || k}: ${v}`).join(', '))}">${parts.map(([k, v]) =>
      `<i class="${tone(k)}" style="flex:${v}" title="${esc(S.labels.decisions[k] || k)}: ${n(v)}"></i>`).join('')}</div>
    <div class="stack-legend">${parts.map(([k, v]) => `<span><i class="${tone(k)}" style="background:var(--${tone(k) === 'none' ? 'line-2' : tone(k)})"></i>${esc(S.labels.decisions[k] || k)} <b>${n(v)}</b> <span class="muted">${pct(v, rows.length)}</span></span>`).join('')}</div></div>`;
}

async function reviewed(_, params) {
  crumbs(['Decisions']);
  const decision = params.get('decision') || '';
  const data = await api(url('/api/reviews', { run: S.run, decision }));
  app.innerHTML = `${pageHead({ eyebrow: 'Audit trail', title: 'Decisions',
      lede: 'Decisions recorded for the selected run, newest first.' })}
    <form class="filters toolbar" id="rf"><label>Decision <select name="decision"><option value="">All</option>${Object.entries(S.labels.decisions).filter(([k]) => k !== 'UNREVIEWED').map(([k, v]) => `<option value="${k}" ${k === decision ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></label><div class="actions"><button>Show</button></div></form>
    ${!decision && data.rows.length ? decisionMix(data.rows) : ''}
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
      lede: 'Run provenance, audit-trail integrity, questionnaire rules, evaluation results and the single-record check.' })}
    <div class="panel kv-pairs"><h2>Run and method</h2>${kv([{ label: 'Fusion run', value: summary.run }, { label: 'Method', value: m.fusion_version },
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
  S.run = directory; S.filters = {}; S.page = 1; S.ov = null; store.set('l:MoSPI.run', S.run);
  renderRuns();
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
      lede: 'Run all validation checks on a prepared survey delivery to produce a new review list.' })}
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
      lede: 'Validation runs are started on the processing machine, not on this instance.' })}
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

/* ------------------------------------------------------------ upload & validate (PostgreSQL operational store)
 *
 * Upload -> pre-flight report -> explicit "Start Validation" -> the worker runs the unchanged pipeline.
 * Progress shown is real: bytes sent while uploading, and the stage events the worker records while validating.
 * No percentage is invented for a validation; a running step is shown as running. */

const DS_LABEL = { RECEIVING: 'Receiving files', PREFLIGHT_PASSED: 'Pre-flight passed', PREFLIGHT_BLOCKED: 'Pre-flight blocked', QUEUED: 'Queued for validation',
  VALIDATING: 'Validating', VALIDATED: 'Validated and published', FAILED: 'Validation failed', REJECTED: 'Rejected' };
const DS_CHIP = { PREFLIGHT_PASSED: 'green', PREFLIGHT_BLOCKED: 'red', QUEUED: 'blue', VALIDATING: 'blue', VALIDATED: 'green', FAILED: 'red' };
const OPS_LABEL = { QUEUED: 'Queued', RUNNING: 'Running', SUCCEEDED: 'Succeeded', FAILED: 'Failed', FAILED_QA_GATE: 'Stopped by a quality check', INTERRUPTED: 'Interrupted', CANCELLED: 'Cancelled' };
const OPS_CHIP = { QUEUED: 'blue', RUNNING: 'blue', SUCCEEDED: 'green', FAILED: 'red', FAILED_QA_GATE: 'red', INTERRUPTED: 'amber' };
const opsChip = s => chip(OPS_LABEL[s] || s, OPS_CHIP[s] || '');
const JOB_STAGES = ['staging', 'preparation', 'peer', 'statistical', 'contextual', 'ml', 'pattern', 'historical', 'integrity', 'fusion', 'publication'];
const JOB_STAGE_LABEL = { staging: 'Check stored files', preparation: 'Prepare delivery', ...STAGE_LABEL, publication: 'Publish run' };
const SEVERITY = { BLOCKING: 'blocking', WARNING: 'warning', INFO: '' };
const isAdmin = () => can('run');
const bytes = v => (v == null ? '—' : v >= 1048576 ? `${(v / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(v / 1024))} KB`);
const newKey = () => (window.crypto?.randomUUID ? crypto.randomUUID() : `${Date.now()}${Math.random()}`).replace(/[^a-z0-9]/gi, '');
const up = { files: [], skipped: [] };
let opsSeen = 0;

async function opsbar(force = false) {
  const el = document.querySelector('#opsbar');
  if (!force && Date.now() - opsSeen < 30000) return;
  opsSeen = Date.now();
  let o;
  try { o = await api('/api/operations'); } catch { el.classList.add('hidden'); return; }
  if (!o.available) { el.classList.add('hidden'); return; }
  // Shown only when something needs attention.
  const parts = [];
  if (!o.database?.reachable) parts.push('<span class="bad">Operations database unreachable</span>');
  if (o.last_check && o.last_check.status !== 'SUCCEEDED') parts.push(`<span class="bad">Last integrity check found problems</span> ${esc(when(o.last_check.finished_utc || o.last_check.created_utc))}`);
  if ((o.failed_jobs || []).length) parts.push(`<span class="bad">${n(o.failed_jobs.length)} failed ${o.failed_jobs.length === 1 ? 'job' : 'jobs'}</span>${o.uploads ? ' <a href="#/upload">see why</a>' : ''}`);
  if (o.open_alerts?.errors) parts.push(`<span class="bad">${n(o.open_alerts.errors)} open ${o.open_alerts.errors === 1 ? 'alert' : 'alerts'}</span>`);
  if (!parts.length) { el.classList.add('hidden'); return; }
  el.innerHTML = `<div class="opsbar-row">${parts.join('')}</div>`;
  el.classList.remove('hidden');
}

async function upload(sub) {
  crumbs(['Upload & validate']);
  stopBatchTimer();
  if (sub && sub.startsWith('job/')) { await uploadJob(sub.slice(4)); return; }
  if (sub) { await datasetPage(sub); return; }
  const ops = await api('/api/operations');
  const head = pageHead({ eyebrow: 'Operations', title: 'Upload & validate',
    lede: 'Upload a survey delivery, check the pre-flight report, then start validation.' });
  if (!S.deploy.uploads) {
    app.innerHTML = `${head}${infoBox(esc(ops.available ? 'Uploads and validation runs happen on the processing machine. This instance shows their status only.' : ops.reason), 'accent')}${opsPanels(ops, [], [])}`;
    return;
  }
  if (!S.user || !can('operations')) {
    app.innerHTML = `${head}${infoBox('An administrator uploads and validates survey data; analysts follow the jobs and checks here.', 'amber')}${opsPanels(ops, [], [])}`;
    return;
  }
  const [info, ds, jobs, alerts] = await Promise.all([api('/api/ingest/contracts'), api('/api/datasets'), api('/api/jobs'), api('/api/notifications')]);
  const step = (k, title) => `<div class="panel-head"><h2><span class="step-num">${k}</span>${esc(title)}</h2></div>`;
  const contract = c => `PLFS ${c.release.replace('_', '–')} · ${c.observation === 'first_visit' ? 'first visit' : c.observation}`;
  app.innerHTML = `${head}
    ${isAdmin() ? `<div class="panel">${step(1, 'Choose the layout and the files')}
      <form id="uf" class="filters">
        <label>Survey layout <select name="contract">${info.contracts.map(c => `<option value="${esc(c.name)}">${esc(contract(c))} (${esc(c.household_file)} + ${esc(c.person_file)})</option>`).join('')}</select></label>
        <label class="tick" style="flex-direction:row;align-items:center;gap:6px;text-transform:none;letter-spacing:0;font-weight:500;font-size:12.5px;color:var(--ink)">
          <input type="checkbox" name="synthetic"> These files are synthetic test data</label>
      </form>
      <div id="dz" class="dropzone" style="margin-top:12px">Drop the household and person CSV files, or their folder, here.
        <div class="pickers"><label class="btn secondary">Choose files<input type="file" id="pf" multiple accept=".csv,text/csv"></label>
        <label class="btn secondary">Choose a folder<input type="file" id="pd" webkitdirectory multiple></label></div>
        <p class="small muted" style="margin:10px 0 0">One delivery = one household file and one person file of the chosen layout. Up to ${n(info.limits.max_files)} files,
        ${n(info.limits.max_file_mb)} MB each. Files other than .csv in a folder are listed and skipped, never uploaded.</p></div>
      <div id="sel"></div>
      <p class="page-actions" style="margin-top:12px"><button id="ugo" class="lg" disabled>${icon('play')}Upload and run the pre-flight check</button></p>
      <p class="small muted">Nothing is validated yet: after the upload you will see a pre-flight report and decide whether to start.</p></div>`
      : infoBox('Only an administrator can upload survey data. You can follow datasets, jobs and checks below.', 'amber')}
    <div class="panel">${panelHead('Datasets', 'list')}
      ${table(['Received', 'Layout', 'Data', 'Files', 'Status', 'By', ''], ds.datasets.map(d => `<tr><td class="small">${esc(when(d.created_utc))}</td>
        <td>${esc(roundName(d.release))}</td><td>${d.data_class === 'SYNTHETIC' ? chip('Synthetic', 'violet') : 'Survey data'}</td><td class="num">${n(d.files)}</td>
        <td>${chip(DS_LABEL[d.status] || d.status, DS_CHIP[d.status] || '')}${d.label ? ` <span class="small muted">${esc(d.label)}</span>` : ''}</td>
        <td>${esc(d.created_by)}</td><td><a href="#/upload/${d.dataset_id}">Open</a></td></tr>`), { empty: 'No dataset has been uploaded yet.' })}</div>
    ${opsPanels(ops, jobs.jobs, alerts.notifications)}`;
  bindOps();
  if (isAdmin()) bindUpload(info);
  if ((jobs.jobs || []).some(j => ['QUEUED', 'RUNNING'].includes(j.status))) batchTimer = setTimeout(() => { if (location.hash === '#/upload') route(); }, 5000);
}

function opsPanels(ops, jobs, alerts) {
  const runs = (ops.runs || []).slice(0, 15);
  return `${alerts.length ? `<div class="panel red">${panelHead('Open alerts', 'alert')}<ul class="findings">${alerts.map(a =>
      `<li class="${a.severity === 'ERROR' ? 'blocking' : a.severity === 'WARNING' ? 'warning' : ''}"><b>${esc(when(a.created_utc))}</b> · ${esc(a.message)}
       ${a.job_id ? ` <a href="#/upload/job/${a.job_id}">details</a>` : ''} <button class="secondary" data-ack="${a.notification_id}" style="height:24px;margin-left:6px">Acknowledge</button></li>`).join('')}</ul></div>` : ''}
    ${jobs.length ? `<div class="panel">${panelHead('Jobs', 'clock', isAdmin() ? '<button class="secondary" id="chk">Run integrity check now</button>' : '')}
      ${table(['Requested', 'Job', 'Status', 'Step', 'Finished', ''], jobs.slice(0, 20).map(j => `<tr><td class="small">${esc(when(j.created_utc))}</td>
        <td>${j.kind === 'VALIDATION' ? `Validation <span class="small muted">${esc(j.label || '')}${j.attempt > 1 ? ` · attempt ${j.attempt}` : ''}</span>` : 'Integrity check'}
        <span class="small muted">(${esc((j.trigger || '').toLowerCase().replace('_', ' '))})</span></td><td>${opsChip(j.status)}</td>
        <td class="small">${esc(JOB_STAGE_LABEL[j.current_stage] || j.current_stage || '—')}</td><td class="small">${esc(j.finished_utc ? when(j.finished_utc) : '—')}</td>
        <td><a href="#/upload/job/${j.job_id}">Open</a></td></tr>`))}</div>` : ''}
    <div class="panel">${panelHead('Run registry', 'check', ops.last_check ? `<span class="small muted">Last integrity check ${esc(when(ops.last_check.finished_utc || ops.last_check.created_utc))}: ${ops.last_check.status === 'SUCCEEDED' ? 'passed' : 'found problems'}</span>` : '')}
      ${ops.available ? table(['Run', 'Status', 'Data', 'Persons', 'Published or registered'], runs.map(r => `<tr><td class="small">${esc(r.run_id)}</td>
        <td>${chip(r.status === 'PUBLISHED' ? 'Published' : r.status === 'REGISTERED' ? 'Registered' : r.status === 'PENDING' ? 'Being produced' : r.status, r.status === 'FAILED' ? 'red' : r.status === 'PENDING' ? 'blue' : 'green')}</td>
        <td>${r.data_class === 'SYNTHETIC' ? chip('Synthetic', 'violet') : 'Survey data'}</td><td class="num">${n(r.records)}</td>
        <td class="small">${esc(when(r.published_utc || r.registered_utc))}</td></tr>`), { empty: 'No run is registered.' })
        : empty(ops.reason || 'Operational records are not available on this instance.')}</div>`;
}

function bindOps() {
  app.querySelectorAll('[data-ack]').forEach(b => { b.onclick = async () => {
    try { await api(`/api/notifications/${b.dataset.ack}/ack`, { method: 'POST' }); route(); } catch (err) { notice(err.message, 'error'); } }; });
  const chk = document.querySelector('#chk');
  if (chk) chk.onclick = async () => {
    chk.disabled = true;
    try { const r = await api('/api/checks', { method: 'POST' }); S.flash = { text: r.already_active ? 'An integrity check is already queued or running.' : 'Integrity check queued; the worker runs it shortly.', kind: 'ok' }; go(`#/upload/job/${r.job_id}`); }
    catch (err) { notice(err.message, 'error'); chk.disabled = false; }
  };
}

function bindUpload(info) {
  up.files = []; up.skipped = [];
  const take = list => {
    for (const { file, path } of list) {
      if (!/\.csv$/i.test(file.name)) { up.skipped.push(path || file.name); continue; }
      if (!up.files.some(f => f.path === (path || file.name))) up.files.push({ file, path: path || file.name });
    }
    showSelection(info);
  };
  document.querySelector('#pf').onchange = e => take([...e.target.files].map(file => ({ file, path: file.name })));
  document.querySelector('#pd').onchange = e => take([...e.target.files].map(file => ({ file, path: file.webkitRelativePath || file.name })));
  const dz = document.querySelector('#dz');
  dz.ondragover = e => { e.preventDefault(); dz.classList.add('over'); };
  dz.ondragleave = () => dz.classList.remove('over');
  dz.ondrop = async e => {
    e.preventDefault(); dz.classList.remove('over');
    const entries = [...(e.dataTransfer.items || [])].map(i => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
    take(entries.length ? (await Promise.all(entries.map(walk))).flat() : [...e.dataTransfer.files].map(file => ({ file, path: file.name })));
  };
  document.querySelector('#ugo').onclick = () => startUpload(info);
}

function walk(entry, prefix = '') {
  // Browsers expose a dropped folder only through this entry API; relative paths are kept for the report.
  return new Promise(resolve => {
    if (entry.isFile) { entry.file(file => resolve([{ file, path: prefix + file.name }]), () => resolve([])); return; }
    const reader = entry.createReader(); const all = [];
    const next = () => reader.readEntries(async batch => {
      if (!batch.length) { resolve((await Promise.all(all.map(e => walk(e, `${prefix}${entry.name}/`)))).flat()); return; }
      all.push(...batch); next();
    }, () => resolve([]));
    next();
  });
}

function showSelection(info) {
  const sel = document.querySelector('#sel');
  const tooBig = up.files.filter(f => f.file.size > info.limits.max_file_mb * 1048576);
  sel.innerHTML = (up.files.length ? `<div style="margin-top:12px">${table(['File', 'Folder path', { label: 'Size', num: true }, 'Upload'], up.files.map((f, k) =>
      `<tr><td>${esc(f.file.name)}</td><td class="small muted">${esc(f.path)}</td><td class="num">${bytes(f.file.size)}</td><td><div class="upbar" id="ub${k}"><i style="width:0"></i></div></td></tr>`))}</div>` : '')
    + (up.skipped.length ? infoBox(`Skipped (not CSV, not uploaded): ${esc(up.skipped.join(', '))}`) : '')
    + (up.files.length > info.limits.max_files ? infoBox(`Too many files: at most ${info.limits.max_files} per delivery.`, 'amber') : '')
    + (tooBig.length ? infoBox(`Larger than the ${info.limits.max_file_mb} MB limit: ${esc(tooBig.map(f => f.file.name).join(', '))}`, 'amber') : '');
  document.querySelector('#ugo').disabled = !up.files.length || up.files.length > info.limits.max_files || tooBig.length > 0;
}

function putFile(datasetId, item, k) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const bar = document.querySelector(`#ub${k}`);
    xhr.open('PUT', url(`/api/datasets/${datasetId}/files`, { name: item.file.name, path: item.path }));
    xhr.setRequestHeader('X-MoSPI-Request', '1');
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.upload.onprogress = e => { if (e.lengthComputable && bar) bar.firstElementChild.style.width = `${(e.loaded / e.total) * 100}%`; };
    xhr.onload = () => {
      let body = {}; try { body = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
      if (xhr.status === 200) { if (bar) { bar.classList.add('done'); bar.firstElementChild.style.width = '100%'; } resolve(body); }
      else { if (bar) bar.classList.add('failed'); reject(new Error(`${item.file.name}: ${body.detail || xhr.statusText}`)); }
    };
    xhr.onerror = () => { if (bar) bar.classList.add('failed'); reject(new Error(`${item.file.name}: the upload was interrupted.`)); };
    xhr.send(item.file);
  });
}

async function startUpload(info) {
  const form = document.querySelector('#uf');
  const button = document.querySelector('#ugo');
  button.disabled = true;
  try {
    const dataset = await api('/api/datasets', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': newKey() },
      body: JSON.stringify({ contract: form.contract.value, synthetic: form.synthetic.checked }) });
    for (const [k, item] of up.files.entries()) await putFile(dataset.dataset_id, item, k);
    notice('Files received. Running the pre-flight check…');
    await api(`/api/datasets/${dataset.dataset_id}/preflight`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    go(`#/upload/${dataset.dataset_id}`);
  } catch (err) { notice(err.message, 'error'); button.disabled = false; }
}

async function datasetPage(id) {
  const d = await api(`/api/datasets/${encodeURIComponent(id)}`);
  const report = d.preflight || {};
  const counts = report.counts || {};
  const findings = report.findings || [];
  const blocking = findings.filter(f => f.severity === 'BLOCKING');
  const key = newKey();
  crumbs(['Upload & validate', d.label || id.slice(0, 8)]);
  app.innerHTML = `<a class="back" href="#/upload">${icon('back')}Upload & validate</a>
    <div class="page-head"><div><p class="eyebrow">Dataset ${esc(id.slice(0, 8))}</p><h1>${esc(roundName(d.release))} · ${d.data_class === 'SYNTHETIC' ? 'synthetic test data' : 'survey data'}</h1>
      <div class="case-tags">${chip(DS_LABEL[d.status] || d.status, DS_CHIP[d.status] || '')}</div></div></div>
    <div class="panel">${panelHead('Files received', 'list')}${table(['File', 'Folder path', 'Recognised as', { label: 'Size', num: true }, 'Columns', 'SHA-256'], d.files.map(f => {
      const r = (report.files || []).find(x => x.file_id === f.file_id) || {};
      return `<tr><td>${esc(f.display_name)}</td><td class="small muted">${esc(f.relative_path || '—')}</td><td>${f.level ? esc(f.level === 'household' ? 'Household file' : 'Person file') : chip('Not recognised', 'amber')}</td>
        <td class="num">${bytes(f.size_bytes)}</td><td class="num">${n(r.columns)}</td><td class="small muted">${esc(f.sha256.slice(0, 12))}</td></tr>`; }))}</div>
    <div class="panel ${blocking.length ? 'red' : ''}">${panelHead(report.status ? `Pre-flight report: ${report.status === 'PASSED' ? 'ready to validate' : 'cannot be validated as it is'}` : 'Pre-flight report', 'check')}
      ${report.status ? `${counts.person ? kv([{ label: 'Persons', value: n(counts.person.rows) }, { label: 'Households', value: n(counts.household?.rows) },
        { label: 'Rows with a blank key part', value: n((counts.person.blank_key_rows || 0) + (counts.household?.blank_key_rows || 0)) },
        { label: 'Rows sharing a key', value: n((counts.person.duplicate_key_rows || 0) + (counts.household?.duplicate_key_rows || 0)) },
        { label: 'Persons without a household', value: n(counts.person.without_household) }, { label: 'Persons already received earlier', value: n(counts.person.overlapping_records) }]) : ''}
        ${findings.length ? `<ul class="findings">${findings.map(f => `<li class="${SEVERITY[f.severity] || ''}"><b>${f.severity === 'BLOCKING' ? 'Must be fixed' : f.severity === 'WARNING' ? 'Note' : 'Info'}</b>${f.file ? ` · ${esc(f.file)}` : ''} — ${esc(f.message)}</li>`).join('')}</ul>`
          : '<p>No problem found. Every documented column is present and the household and person files belong together.</p>'}
        <p class="small muted">The report shows counts and column names only, never survey values. Records are never dropped or corrected; preparation keeps and marks them.</p>
        ${tech({ contract: report.contract, mapping_profile: report.mapping_profile, files: report.files, counts })}` : empty('The pre-flight check has not run yet.')}</div>
    ${d.status === 'PREFLIGHT_PASSED' && isAdmin() ? `<div class="panel">${panelHead('Start the validation', 'play')}
      <p>The full V2.2 validation runs on the processing machine: preparation, every check and quality gate, then the review list is published. A delivery of this size takes minutes to about an hour; you can leave and come back.</p>
      <form id="cf" class="confirm-row"><label class="filters" style="display:flex;flex-direction:column">Run label (optional)
        <input name="label" pattern="[a-z0-9][a-z0-9_]{0,23}" size="16" placeholder="assigned if empty" value="${esc(d.label || '')}" ${d.label ? 'readonly' : ''}></label>
        <label class="tick"><input type="checkbox" name="ok"> I have reviewed the pre-flight report for this dataset</label>
        <button id="cgo" class="lg cta" disabled>${icon('play')}Start Validation</button>
        <button type="button" id="rj" class="secondary">Reject dataset</button></form></div>`
      : d.status === 'PREFLIGHT_BLOCKED' && isAdmin() ? `<div class="panel">${panelHead('What next', 'info')}<p>Fix the files and upload them again as a new dataset. This dataset is kept as a record.</p>
        <button type="button" id="rj" class="secondary">Reject dataset</button></div>` : ''}
    ${d.jobs.length ? `<div class="panel">${panelHead('Validation jobs', 'clock')}${table(['Requested', 'Status', 'Attempt', 'Run', ''], d.jobs.map(j =>
      `<tr><td class="small">${esc(when(j.created_utc))}</td><td>${opsChip(j.status)}</td><td>${n(j.attempt)}</td><td class="small">${esc(j.run_id || '—')}</td><td><a href="#/upload/job/${j.job_id}">Open</a></td></tr>`))}</div>` : ''}`;
  const form = document.querySelector('#cf');
  if (form) {
    form.ok.onchange = () => { document.querySelector('#cgo').disabled = !form.ok.checked; };
    form.onsubmit = async e => {
      e.preventDefault();
      document.querySelector('#cgo').disabled = true;
      try {
        const job = await api(`/api/datasets/${id}/confirm`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
          body: JSON.stringify({ label: form.label.value.trim() || null, confirm: true }) });
        S.flash = { text: 'Validation queued. The worker starts it shortly.', kind: 'ok' };
        go(`#/upload/job/${job.job_id}`);
      } catch (err) { notice(err.message, 'error'); document.querySelector('#cgo').disabled = false; }
    };
  }
  const rj = document.querySelector('#rj');
  if (rj) rj.onclick = async () => { try { await api(`/api/datasets/${id}/reject`, { method: 'POST' }); route(); } catch (err) { notice(err.message, 'error'); } };
}

async function uploadJob(id) {
  const j = await api(`/api/jobs/${encodeURIComponent(id)}`);
  const active = ['QUEUED', 'RUNNING'].includes(j.status);
  crumbs(['Upload & validate', j.kind === 'VALIDATION' ? (j.label || id.slice(0, 8)) : 'Integrity check']);
  const state = {};
  for (const e of j.events) if (JOB_STAGES.includes(e.stage)) state[e.stage] = e.status;
  const cls = s => ({ COMPLETED: 'done', REUSED: 'reused', STARTED: active ? 'now' : 'failed', FAILED: 'failed' }[s] || '');
  const result = j.result || {};
  app.innerHTML = `<a class="back" href="#/upload">${icon('back')}Upload & validate</a>
    <div class="page-head"><div><p class="eyebrow">${j.kind === 'VALIDATION' ? 'Validation job' : 'Integrity check'}</p>
      <h1>${j.kind === 'VALIDATION' ? esc(j.run_id || j.label) : 'Integrity check of registered data'}</h1><div class="case-tags">${opsChip(j.status)}</div></div>
      <div class="page-actions">${isAdmin() && j.kind === 'VALIDATION' && ['FAILED', 'INTERRUPTED'].includes(j.status) ? '<button id="jr">Retry</button>' : ''}
        ${isAdmin() && j.status === 'QUEUED' ? '<button id="jc" class="secondary">Cancel</button>' : ''}</div></div>
    ${j.kind === 'VALIDATION' ? `<div class="panel">${panelHead('Steps', 'clock')}<ol class="stages" aria-label="Steps">${JOB_STAGES.map(s =>
        `<li class="${cls(state[s])}">${esc(JOB_STAGE_LABEL[s] || s)}${state[s] === 'REUSED' ? ' (reused)' : ''}</li>`).join('')}</ol>
      <p class="small muted">${j.status === 'QUEUED' ? 'Waiting for the worker.' : active ? `Running: ${esc(JOB_STAGE_LABEL[j.current_stage] || j.current_stage || 'starting')}. Steps take different times, so no percentage is shown. This page refreshes every 5 seconds.` : ''}</p></div>` : ''}
    <div class="panel">${kv([{ label: 'Requested by', value: `${j.requested_by}${j.requested_by_verified ? '' : ' (unverified)'}` }, { label: 'Requested', value: when(j.created_utc) },
      { label: 'Started', value: j.started_utc ? when(j.started_utc) : '—' }, { label: 'Finished', value: j.finished_utc ? when(j.finished_utc) : '—' },
      { label: 'Trigger', value: (j.trigger || '').toLowerCase().replace('_', ' ') }, ...(j.attempt > 1 ? [{ label: 'Attempt', value: String(j.attempt) }] : [])])}</div>
    ${j.error_message ? `<div class="panel red"><h2>${j.status === 'FAILED_QA_GATE' ? 'Stopped by a quality check' : j.kind === 'INTEGRITY_CHECK' ? 'Problems found' : 'The job did not finish'}</h2><p>${esc(j.error_message)}</p>
      ${j.kind === 'VALIDATION' ? `<p class="small muted">Nothing was published from this job. Earlier runs are unaffected.${j.status === 'FAILED_QA_GATE' ? ' A quality-check stop is not retried: fix the data and upload it again.' : ''}</p>` : ''}</div>` : ''}
    ${j.status === 'SUCCEEDED' && j.kind === 'VALIDATION' ? `<div class="panel">${panelHead('Result', 'check')}${kv([{ label: 'Persons checked', value: n(result.records) },
      { label: '"Check now" cases', value: n(result.check_now) }, { label: 'Quality checks', value: Object.values(result.qa || {}).every(s => s === 'PASSED') ? 'all passed' : JSON.stringify(result.qa) },
      { label: 'Earlier periods compared', value: (result.history_used || []).join(', ') || 'none available on this server' }])}
      <p class="page-actions" style="margin-top:14px"><button data-go="overview">Open dashboard</button> <button class="secondary" data-go="worklist">Open worklist</button></p></div>` : ''}
    ${j.findings ? `<div class="panel">${panelHead('Findings', 'list')}${table(['Target', 'Check', 'Result', 'Detail'], j.findings.map(f =>
      `<tr><td class="small">${esc(f.target_kind.toLowerCase())} ${esc(f.target_id)}</td><td class="small">${esc(f.check_name)}</td>
       <td>${chip(f.status === 'PASSED' ? 'Passed' : f.status === 'CHANGED' ? 'Changed' : f.status === 'WARNING' ? 'Warning' : 'Failed', { PASSED: 'green', FAILED: 'red', CHANGED: 'amber', WARNING: 'amber' }[f.status])}</td>
       <td class="small">${esc(f.detail || '')}</td></tr>`), { empty: active ? 'The check has not run yet.' : 'No findings recorded.' })}</div>` : ''}
    <div class="panel"><details><summary>Technical log of this job</summary>${table(['Time', 'Step', 'Event', 'Message'], j.events.map(e =>
      `<tr><td class="small">${esc(when(e.created_utc))}</td><td class="small">${esc(e.stage)}</td><td class="small">${esc(e.status)}</td><td class="small">${esc(e.message || '')}</td></tr>`))}</details></div>`;
  app.querySelectorAll('[data-go]').forEach(b => { b.onclick = () => openRun(j.run_id, b.dataset.go); });
  const act = (sel, path, text) => { const b = document.querySelector(sel); if (b) b.onclick = async () => {
    b.disabled = true;
    try { const r = await api(`/api/jobs/${id}/${path}`, { method: 'POST' }); S.flash = { text, kind: 'ok' }; go(`#/upload/job/${r.job_id}`); }
    catch (err) { notice(err.message, 'error'); b.disabled = false; } }; };
  act('#jr', 'retry', 'Retry queued. Completed steps are reused; nothing stored is overwritten.');
  act('#jc', 'cancel', 'Job cancelled before it started.');
  stopBatchTimer();
  if (active) batchTimer = setTimeout(() => { if (location.hash === `#/upload/job/${id}`) route(); }, 5000);
  else opsbar(true);
}

/* ------------------------------------------------------------ users (administrators) */

const AUTH_EVENT = { SIGNED_IN: 'Signed in', SIGN_IN_FAILED: 'Failed sign-in', ACCOUNT_LOCKED: 'Locked after failed sign-ins', SIGNED_OUT: 'Signed out',
  PASSWORD_CHANGED: 'Changed own password', PASSWORD_RESET: 'Password reset', USER_CREATED: 'Account created', USER_UPDATED: 'Account changed' };
const ROLE_HELP = { supervisor: 'Reviews cases and records decisions; can export case lists.',
  analyst: 'Reads review lists, analytics, jobs and checks; records no decisions.' };

function accountStatus(u) {
  if (!u.active) return chip('Deactivated');
  if (u.locked_until && new Date(u.locked_until) > new Date()) return chip('Locked', 'amber');
  if (u.must_change_password) return chip('Password not set yet', 'amber');
  return chip('Active', 'green');
}

function credentialsPanel(c) {
  return `<div class="panel credentials" role="status">${panelHead(c.title, 'lock')}
    <dl class="kv"><dt>Name</dt><dd>${esc(c.name)}</dd><dt>Username</dt><dd class="mono">${esc(c.username)}</dd><dt>Temporary password</dt><dd class="mono">${esc(c.password)}</dd></dl>
    <p class="small muted">Shown only now. Pass it on through a separate channel, such as a phone call or in person. They choose their own password at their first sign-in.</p>
    <p class="page-actions"><button type="button" class="secondary" id="copyCreds">Copy username and password</button></p></div>`;
}

async function users() {
  crumbs(['Users']);
  const head = pageHead({ eyebrow: 'Administration', title: 'Users', lede: 'Create supervisor and analyst accounts, reset passwords and deactivate accounts. Administrator accounts are created on the server.' });
  if (!S.auth || !can('manage_users') || !S.session.accounts_managed_here) {
    app.innerHTML = `${head}${infoBox(S.auth && can('manage_users') ? 'Accounts are managed on the processing machine.' : 'Only an administrator can manage accounts.', 'amber')}`;
    return;
  }
  const data = await api('/api/users');
  const creds = S.creds; S.creds = null;
  const roleOptions = selected => data.roles.map(r => `<option value="${r}" ${r === selected ? 'selected' : ''}>${esc(data.role_labels[r])}</option>`).join('');
  app.innerHTML = `${head}
    ${creds ? credentialsPanel(creds) : ''}
    <div class="panel">${panelHead('Add an account', 'people')}
      <form id="uf" class="filters user-form" autocomplete="off">
        <label class="grow">Name <input name="display_name" required maxlength="80" placeholder="As it should appear in the audit trail"></label>
        <label>Username <input name="username" required maxlength="40" pattern="[a-z0-9][a-z0-9._\\-]{2,39}" autocapitalize="none" spellcheck="false" placeholder="e.g. r.sharma"
          title="3 to 40 characters: lower-case letters, digits, dots, hyphens or underscores"></label>
        <label>Role <select name="role" id="ufRole">${roleOptions('supervisor')}</select></label>
        <div class="actions"><button id="ufGo">Create account</button></div>
      </form>
      <p class="small muted" id="ufHelp">${esc(ROLE_HELP.supervisor)}</p></div>
    <div class="panel">${panelHead('Accounts', 'list', `<span class="small muted">${n(data.users.filter(u => u.active).length)} active</span>`)}
      ${table(['Name', 'Role', 'Status', 'Last sign-in', 'Created', ''], data.users.map(u => {
        const self = u.user_id === S.user.user_id, admin = u.role === 'admin';
        const actions = admin ? `<span class="small muted">${self ? 'You' : 'Managed on the server'}</span>`
          : `<div class="row-actions">${u.active ? `<button type="button" class="secondary sm" data-reset="${u.user_id}">Reset password</button>` : ''}
              <button type="button" class="secondary sm" data-active="${u.user_id}" data-to="${u.active ? '0' : '1'}">${u.active ? 'Deactivate' : 'Reactivate'}</button></div>`;
        const role = admin || !u.active ? esc(data.role_labels[u.role]) : `<select class="role-pick" data-role="${u.user_id}" aria-label="Role of ${esc(u.display_name)}">${roleOptions(u.role)}</select>`;
        return `<tr><td><b>${esc(u.display_name)}</b><div class="small muted mono">${esc(u.username)}</div></td><td>${role}</td><td>${accountStatus(u)}</td>
          <td class="small">${u.last_login_utc ? esc(when(u.last_login_utc)) : '—'}</td><td class="small">${esc(when(u.created_utc))}<div class="muted">${esc(u.created_by)}</div></td><td>${actions}</td></tr>`;
      }), { empty: 'No accounts yet.' })}</div>
    <div class="panel">${panelHead('Recent sign-in and account activity', 'clock')}
      ${table(['When', 'What', 'Account', 'By'], data.activity.map(e => `<tr><td class="small">${esc(when(e.event_utc))}</td><td>${esc(AUTH_EVENT[e.event_type] || e.event_type)}${e.detail ? ` <span class="small muted">(${esc(e.detail)})</span>` : ''}</td>
        <td class="mono small">${esc(e.username)}</td><td class="small">${esc(e.actor === 'anonymous' || e.actor === e.username ? '—' : e.actor)}${e.origin === 'hosted' ? ' <span class="muted">(hosted)</span>' : e.origin === 'cli' ? ' <span class="muted">(server)</span>' : ''}</td></tr>`),
        { empty: 'Nothing recorded yet.' })}</div>`;

  const send = (path, method, body) => api(path, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  const form = document.querySelector('#uf');
  document.querySelector('#ufRole').onchange = e => { document.querySelector('#ufHelp').textContent = ROLE_HELP[e.target.value] || ''; };
  form.onsubmit = async e => {
    e.preventDefault();
    const button = document.querySelector('#ufGo'); button.disabled = true;
    try {
      const r = await send('/api/users', 'POST', { display_name: form.display_name.value.trim(), username: form.username.value.trim().toLowerCase(), role: form.role.value });
      S.creds = { title: 'Account created', name: r.user.display_name, username: r.user.username, password: r.temporary_password };
      notice('');
      await users();
    } catch (err) { notice(err.message, 'error'); button.disabled = false; }
  };
  document.querySelector('#copyCreds')?.addEventListener('click', async e => {
    try { await navigator.clipboard.writeText(`Username: ${creds.username}\nTemporary password: ${creds.password}`); e.target.textContent = 'Copied'; }
    catch { e.target.textContent = 'Copy failed: select the text instead'; }
  });
  const byId = id => data.users.find(u => String(u.user_id) === String(id));
  app.querySelectorAll('[data-reset]').forEach(b => { b.onclick = async () => {
    const u = byId(b.dataset.reset);
    if (!confirm(`Set a new temporary password for ${u.display_name}? Their current password stops working and they are signed out.`)) return;
    b.disabled = true;
    try { const r = await send(`/api/users/${u.user_id}/password`, 'POST'); S.creds = { title: 'Password reset', name: u.display_name, username: u.username, password: r.temporary_password }; await users(); }
    catch (err) { notice(err.message, 'error'); b.disabled = false; }
  }; });
  app.querySelectorAll('[data-active]').forEach(b => { b.onclick = async () => {
    const u = byId(b.dataset.active), activate = b.dataset.to === '1';
    if (!activate && !confirm(`Deactivate ${u.display_name}? They are signed out and cannot sign in until the account is reactivated. Their recorded decisions are kept.`)) return;
    b.disabled = true;
    try { await send(`/api/users/${u.user_id}`, 'PATCH', { active: activate }); notice(`${u.display_name}: ${activate ? 'reactivated' : 'deactivated'}.`, 'ok'); await users(); }
    catch (err) { notice(err.message, 'error'); b.disabled = false; }
  }; });
  app.querySelectorAll('[data-role]').forEach(s => { s.onchange = async () => {
    const u = byId(s.dataset.role);
    if (!confirm(`Make ${u.display_name} ${data.role_labels[s.value].toLowerCase()}? They are signed out and sign in again with the new role.`)) { s.value = u.role; return; }
    try { await send(`/api/users/${u.user_id}`, 'PATCH', { role: s.value }); notice(`${u.display_name} is now ${data.role_labels[s.value].toLowerCase()}.`, 'ok'); await users(); }
    catch (err) { notice(err.message, 'error'); s.value = u.role; }
  }; });
}

/* ------------------------------------------------------------ sign-in, account and start */

function modebar() {
  const d = S.deploy || {};
  const parts = [];
  if (d.data_notice) parts.push(`<span><i class="tag synthetic">Synthetic data</i>${esc(d.data_notice)}</span>`);
  // Review-only and read-only decisions are a property of the instance: one compact note in the sidebar.
  const pill = document.querySelector('#modePill');
  const modes = [d.review_only ? 'Validation runs are performed separately and cannot be started from this instance.' : '', d.audit_writable === false ? 'Decisions are read-only here.' : ''].filter(Boolean);
  if (pill && modes.length) {
    pill.innerHTML = `${icon('lock')}<span><b>${d.review_only ? 'Review-only' : 'Read-only'}</b><span class="mode-sub">${d.audit_writable === false ? 'Decisions are read-only here' : 'Runs start on the processing machine'}</span></span>`;
    pill.title = modes.join(' ');
    pill.classList.remove('hidden');
  }
  const el = document.querySelector('#modebar');
  el.innerHTML = parts.length ? `<div class="modebar-row">${parts.join('')}</div>` : '';
  el.classList.toggle('hidden', !parts.length);
  if (d.review_only) { const link = document.querySelector('#nav a[data-route="batch"]'); if (link) (link.querySelector('.nav-label') || link).textContent = 'Batch validation (separate)'; }
}

function renderRuns() {
  const counts = {};
  S.runs.forEach(r => { counts[runShort(r)] = (counts[runShort(r)] || 0) + 1; });
  runSelect.innerHTML = S.runs.map(r => `<option value="${esc(r.directory)}" ${r.directory === S.run ? 'selected' : ''}>${esc(runShort(r) + (counts[runShort(r)] > 1 ? ` (${r.directory})` : ''))}</option>`).join('');
  runSelect.title = runLabel(currentRun());
  document.querySelector('#runPick').classList.toggle('hidden', S.runs.length < 2);
}

function applySession(session) {
  S.session = session || {};
  S.user = S.session.user || null;
  S.caps = S.session.capabilities || [];
  document.querySelectorAll('#nav [data-needs]').forEach(el => {
    const needs = el.dataset.needs;
    el.classList.toggle('hidden', !can(needs) || (needs === 'manage_users' && !S.session.accounts_managed_here));
  });
  const box = document.querySelector('#account');
  if (!S.user) { box.classList.add('hidden'); return; }
  document.querySelector('#accountName').textContent = S.user.name;
  document.querySelector('#accountRole').textContent = S.session.role_label || S.user.role;
  document.querySelector('#accountInitials').textContent = S.user.name.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]).join('').toUpperCase();
  document.querySelector('#pwButton').classList.toggle('hidden', !S.session.can_change_password);
  box.classList.remove('hidden');
}

// However many requests are waiting for a sign-in or a new password, one dialog is shown.
const pendingDialogs = {};
function once(key, open) { return pendingDialogs[key] ||= open().finally(() => { delete pendingDialogs[key]; }); }

// Sign-in backdrop: a soft dot grid, two drifting colour fields and a bar-and-trend skyline that rises on open.
// Decorative only (aria-hidden, no pointer events); every animation stops under prefers-reduced-motion.
const SIGNIN_BACKDROP = (() => {
  const W = 1440, H = 900, n = 36, step = W / n, base = H;
  const heights = Array.from({ length: n }, (_, i) => 70 + 60 * Math.sin(i * .55) + 45 * Math.sin(i * 1.7 + 1) + i * 4.5);
  const bars = heights.map((h, i) => `<rect class="sb-bar" x="${(i * step + step * .18).toFixed(1)}" y="${(base - h).toFixed(1)}" width="${(step * .64).toFixed(1)}" height="${h.toFixed(1)}" rx="5" style="--d:${(i * 0.035).toFixed(3)}s"/>`).join('');
  const pts = heights.map((h, i) => [i * step + step / 2, base - h - 70 - 40 * Math.sin(i * .3)]);
  const line = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
  const area = `${line} L${pts[n - 1][0].toFixed(1)} ${H} L${pts[0][0].toFixed(1)} ${H} Z`;
  const dots = [6, 14, 23, 31].map((i, k) => `<circle class="sb-dot" cx="${pts[i][0].toFixed(1)}" cy="${pts[i][1].toFixed(1)}" r="5" style="--d:${(1.6 + k * .25).toFixed(2)}s"/>`).join('');
  return `<div class="signin-bg" aria-hidden="true"><span class="sb-orb sb-orb-a"></span><span class="sb-orb sb-orb-b"></span>
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMax slice" focusable="false">
      <defs><pattern id="sb-grid" width="28" height="28" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.3"/></pattern>
        <linearGradient id="sb-bar-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#3355e0" stop-opacity=".2"/><stop offset="1" stop-color="#3355e0" stop-opacity=".03"/></linearGradient>
        <linearGradient id="sb-area-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5a3fcf" stop-opacity=".12"/><stop offset="1" stop-color="#5a3fcf" stop-opacity="0"/></linearGradient></defs>
      <rect class="sb-grid" width="${W}" height="${H}" fill="url(#sb-grid)"/>
      <g fill="url(#sb-bar-fill)">${bars}</g>
      <path class="sb-area" d="${area}" fill="url(#sb-area-fill)"/>
      <path class="sb-line" d="${line}" pathLength="1"/>${dots}
    </svg></div>`;
})();

function authDialog(html) {
  const overlay = document.createElement('div');
  overlay.className = 'signin';
  overlay.innerHTML = SIGNIN_BACKDROP + html;
  document.body.appendChild(overlay);
  return overlay;
}
const AUTH_BRAND = `<div class="auth-brand"><span class="brand-mark" aria-hidden="true"><svg width="17" height="17" viewBox="0 0 32 32"><path d="M6 26V8h4v18zm8 0V14h4v12zm8 0v-8h4v8z" fill="#ffffff"/></svg></span>
  <span><b>MoSPI</b><span>Survey Data Validation · PLFS</span></span></div>`;

async function post(path, body) {
  const r = await fetch(path, { method: 'POST', credentials: 'same-origin', headers: { ...REQUEST_HEADER, 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

function signIn() {
  return once('signin', () => new Promise(resolve => {
    const overlay = authDialog(`<form class="auth-card" novalidate>${AUTH_BRAND}
      <h1>Sign in</h1>
      <label>Username <input name="username" autocomplete="username" autocapitalize="none" spellcheck="false" required maxlength="40"></label>
      <label>Password <input type="password" name="password" autocomplete="current-password" required maxlength="128"></label>
      <p class="auth-error hidden" role="alert"></p>
      <button type="submit" class="lg block">Sign in</button>
      <p class="small muted">Accounts are created by your administrator.</p></form>`);
    const form = overlay.querySelector('form'), error = overlay.querySelector('.auth-error');
    form.username.focus();
    form.onsubmit = async e => {
      e.preventDefault();
      if (!form.username.value.trim() || !form.password.value) { error.textContent = 'Enter your username and password.'; error.classList.remove('hidden'); return; }
      const button = form.querySelector('button[type=submit]');
      button.disabled = true; error.classList.add('hidden');
      try {
        applySession(await post('/api/auth/login', { username: form.username.value.trim(), password: form.password.value }));
        overlay.remove();
        resolve();
      } catch (err) {
        error.textContent = err.message; error.classList.remove('hidden');
        form.password.value = ''; form.password.focus();
      } finally { button.disabled = false; }
    };
  })).then(() => (S.user?.must_change_password ? changePassword(true) : undefined));
}

function changePassword(forced = false) {
  return once('password', () => new Promise(resolve => {
    const overlay = authDialog(`<form class="auth-card" novalidate>${forced ? AUTH_BRAND : ''}
      <h1>${forced ? 'Choose your password' : 'Change password'}</h1>
      ${forced ? '<p class="muted">You signed in with a temporary password. Choose your own to continue.</p>' : ''}
      <label>Current password <input type="password" name="current" autocomplete="current-password" required maxlength="128"></label>
      <label>New password <input type="password" name="next" autocomplete="new-password" required maxlength="128" aria-describedby="pwRule"></label>
      <label>New password again <input type="password" name="again" autocomplete="new-password" required maxlength="128"></label>
      <p class="small muted" id="pwRule">At least 12 characters, without your name or username. A short phrase is easier to remember.</p>
      <p class="auth-error hidden" role="alert"></p>
      <div class="auth-actions"><button type="button" class="secondary" data-leave>${forced ? 'Sign out' : 'Cancel'}</button><button type="submit">Save password</button></div></form>`);
    const form = overlay.querySelector('form'), error = overlay.querySelector('.auth-error');
    const fail = text => { error.textContent = text; error.classList.remove('hidden'); };
    form.current.focus();
    overlay.querySelector('[data-leave]').onclick = () => { if (forced) { signOut(); return; } overlay.remove(); resolve(); };
    form.onsubmit = async e => {
      e.preventDefault();
      error.classList.add('hidden');
      if (form.next.value.length < 12) { fail('Use at least 12 characters.'); return; }
      if (form.next.value !== form.again.value) { fail('The two new passwords are not the same.'); return; }
      const button = form.querySelector('button[type=submit]'); button.disabled = true;
      try {
        applySession(await post('/api/auth/password', { current_password: form.current.value, new_password: form.next.value }));
        overlay.remove();
        if (!forced) notice('Password changed.', 'ok');
        resolve();
      } catch (err) { fail(err.message); } finally { button.disabled = false; }
    };
  }));
}

async function signOut() {
  try { await post('/api/auth/logout'); } catch { /* the page reloads either way */ }
  location.reload();
}

// The skip link must not change the hash (the hash is the route), so it moves focus instead.
document.querySelector('.skip-link')?.addEventListener('click', e => { e.preventDefault(); document.querySelector('#main').focus(); });
runSelect.onchange = () => { S.run = runSelect.value; S.filters = {}; S.page = 1; S.ov = null; store.set('l:MoSPI.run', S.run); runSelect.title = runLabel(currentRun()); route(); };
document.querySelector('#signOut').onclick = signOut;
document.querySelector('#pwButton').onclick = () => changePassword(false);

(async () => {
  try {
    const required = await fetch('/api/session/required').then(r => r.json()).catch(() => ({ authentication: false }));
    S.auth = Boolean(required.authentication);
    applySession(S.auth ? await api('/api/session') : {});          // without a session this asks for sign-in first
    if (S.user?.must_change_password) await changePassword(true);
    [S.runs, S.labels, S.deploy] = await Promise.all([api('/api/runs'), api('/api/labels'), api('/api/deployment')]);
    modebar();
    if (!S.runs.length) {
      renderRuns();
      if (S.deploy.review_only) { app.innerHTML = empty('No validation run has been published to this instance yet. Runs are produced on the processing machine and deployed here.'); return; }
      if (!location.hash.startsWith('#/batch') && !location.hash.startsWith('#/users')) location.hash = '#/batch';
      else await route();
      return;
    }
    const remembered = store.get('l:MoSPI.run', null);
    S.run = S.runs.some(r => r.directory === remembered) ? remembered : S.runs[0].directory;
    renderRuns();
    await route();
  } catch (e) {
    notice(e.message, 'error');
    app.innerHTML = '<div class="panel">No review list is available yet. A validation run must be created first; this workspace never generates substitute data.</div>';
  }
})();
