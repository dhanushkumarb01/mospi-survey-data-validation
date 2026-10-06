/* MoSPI survey data validation workstation (internal package name: MoSPI).
 *
 * Every value shown comes from the local API, which reads stored Fusion and
 * source-layer outputs. Nothing here computes or invents evidence: charts only
 * redraw stored counts, quantiles and indicator values. Wording choices such as
 * "much higher" are display conventions applied to stored numbers. Decorative
 * artwork (the hero light streaks and perspective floors) carries no data.
 *
 * Supervisor journey: what needs attention → why this record → what looks
 * unusual → what to check → decide → next case. Technical detail is always one
 * click further away, never on the primary path. */

const app = document.querySelector('#app');
const runSelect = document.querySelector('#runSelect');
const reviewerInput = document.querySelector('#reviewer');
const PAGE_SIZE = 25;
const GROUP_PAGE = 24; // fills 2-, 3- and 4-column card grids evenly
const UNUSUAL = 0.95; // display convention shared with fusion/explain.py
const S = { runs: [], run: null, labels: null, filters: {}, page: 1, ov: null, keys: null, user: null, moreOpen: false };
const MOTION = !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
// Indian digit grouping everywhere (the backend formats the same way), e.g. 1,66,722 and ₹1,85,000.
const nf = new Intl.NumberFormat('en-IN');

const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]));
const n = v => (v == null ? '—' : nf.format(v));
const pct = (part, whole) => (whole ? `${((part / whole) * 100).toFixed(1)}%` : '—');
const when = iso => { try { return new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }); } catch { return iso; } };
const capital = t => (t ? t[0].toUpperCase() + t.slice(1) : t);
const plural = (count, word, many = `${word}s`) => (count === 1 ? word : many);
const store = {
  get(k, fallback) { try { const v = (k.startsWith('s:') ? sessionStorage : localStorage).getItem(k.slice(2)); return v == null ? fallback : JSON.parse(v); } catch { return fallback; } },
  set(k, v) { try { (k.startsWith('s:') ? sessionStorage : localStorage).setItem(k.slice(2), JSON.stringify(v)); } catch { /* storage unavailable: keep in memory only */ } },
};

const ICONS = {
  overview: '<rect x="4" y="4" width="7" height="9" rx="2"/><rect x="13" y="4" width="7" height="5" rx="2"/><rect x="13" y="11" width="7" height="9" rx="2"/><rect x="4" y="15" width="7" height="5" rx="2"/>',
  cases: '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4.5 6h.01M4.5 12h.01M4.5 18h.01" stroke-width="2.6"/>',
  groups: '<circle cx="9" cy="8.5" r="3"/><circle cx="17" cy="10" r="2.3"/><path d="M3.5 19.5c.4-3 2.7-5 5.5-5s5.1 2 5.5 5M15 15.2c2.8-.6 5 1 5.5 4.3"/>',
  reviewed: '<rect x="4" y="4" width="16" height="16" rx="4"/><path d="m8.5 12.2 2.4 2.4 4.6-4.8"/>',
  technical: '<path d="M6 3.5h8l4 4V20a.5.5 0 0 1-.5.5h-11A.5.5 0 0 1 6 20z"/><path d="M14 3.5V8h4M9 12.5h6M9 16h4"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
  right: '<path d="M5 12h14M13 6l6 6-6 6"/>', left: '<path d="M19 12H5M11 6l-6 6 6 6"/>',
  chev: '<path d="m6 9 6 6 6-6"/>', chevr: '<path d="m9 6 6 6-6 6"/>', download: '<path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19.5h14"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.2M12 7.8h.01"/>',
  balance: '<path d="M12 4v16M7 20h10M5 8h14M7.5 8 4.5 14h6zM16.5 8l-3 6h6z"/>',
  inbox: '<path d="M4 13.5 6.2 5h11.6l2.2 8.5V19H4z"/><path d="M4 13.5h4.5l1.2 2h4.6l1.2-2H20"/>',
  people: '<circle cx="9" cy="8.5" r="3"/><path d="M3.5 19.5c.4-3 2.7-5 5.5-5s5.1 2 5.5 5"/><path d="M16 5.6a3 3 0 0 1 0 5.8M17.5 14.6c1.7.8 2.8 2.5 3 4.9"/>',
  areas: '<path d="M4 19h16"/><path d="M5 15l4-5 4 3 5-7"/><circle cx="18" cy="6" r="1.2"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  next: '<path d="M12 4v8l5 3"/><circle cx="12" cy="12" r="8.5"/>',
  layers: '<path d="m12 4 8.5 4.5L12 13 3.5 8.5z"/><path d="m3.5 12.5 8.5 4.5 8.5-4.5"/>',
  filter: '<path d="M4 6.5h16M7 12h10M10 17.5h4"/>',
  compare: '<path d="M4 19.5h16"/><path d="M7 16V10M12 16V5.5M17 16v-3.5"/>',
  history: '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4.5 4.5v3.8h3.8M12 8v4.3l2.8 1.8"/>',
  combo: '<circle cx="6.5" cy="7" r="2.3"/><circle cx="17.5" cy="7" r="2.3"/><circle cx="12" cy="17" r="2.3"/><path d="m7.7 9 3.2 6M16.3 9l-3.2 6M8.8 7h6.4"/>',
  model: '<path d="M4 17.5 9 12l3.5 3 7.5-8"/><path d="M15 7h5v5"/>',
  work: '<rect x="4" y="7.5" width="16" height="11" rx="2.5"/><path d="M9 7.5V6a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 6v1.5M4 12.5h16"/>',
  rule: '<path d="M6 3.5h8l4 4V20a.5.5 0 0 1-.5.5h-11A.5.5 0 0 1 6 20z"/><path d="m9 13.5 2 2 4-4"/>',
  pin: '<path d="M12 20.5s-6.3-5.4-6.3-10.6a6.3 6.3 0 0 1 12.6 0c0 5.2-6.3 10.6-6.3 10.6z"/><circle cx="12" cy="10" r="2.2"/>',
  plus: '<path d="M12 5.5v13M5.5 12h13"/>',
  user: '<circle cx="12" cy="8.5" r="3.5"/><path d="M5 20c.6-3.6 3.4-6 7-6s6.4 2.4 7 6"/>',
  spark: '<path d="M12 3.5v4M12 16.5v4M3.5 12h4M16.5 12h4M6 6l2.6 2.6M15.4 15.4 18 18M6 18l2.6-2.6M15.4 8.6 18 6"/>',
};
const icon = (name, cls = '') => `<svg viewBox="0 0 24 24" class="${cls}" aria-hidden="true">${ICONS[name] || ''}</svg>`;
const MARK = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 18V7h2.6v11zm5.7 0V10.5h2.6V18zm5.7 0v-4.6H19V18z"/></svg>';
document.querySelectorAll('[data-icon]').forEach(el => { el.innerHTML = icon(el.dataset.icon); });

function authToken() { return store.get('s:MoSPI.token', ''); }
async function api(path, options = {}) {
  const token = authToken();
  const headers = { ...(options.headers || {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) };
  const r = await fetch(path, { ...options, headers });
  if (r.status === 401) { store.set('s:MoSPI.token', ''); await signIn(); return api(path, options); }
  if (!r.ok) { let m = await r.text(); try { m = JSON.parse(m).detail || m; } catch { /* plain text */ } throw new Error(m || 'Request failed'); }
  return r.json();
}
function url(path, params = {}) {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== ''));
  const s = q.toString();
  return s ? `${path}?${s}` : path;
}
function notice(text, kind = '') {
  const el = document.querySelector('#notice');
  el.textContent = text || '';
  el.className = `notice ${kind} ${text ? '' : 'hidden'}`;
}
function reviewer() { return reviewerInput.value.trim(); }
const initials = name => String(name || '').split(/[\s.]+/).filter(Boolean).map(w => w[0]).join('').slice(0, 2).toUpperCase() || '?';
function setAvatar() { document.querySelector('#avatar').textContent = reviewer() ? initials(reviewer()) : '?'; }
function runLabel(r) {
  const base = `PLFS ${String(r.release).replace('_', '–')} · ${r.observation === 'first_visit' ? 'First visit' : 'Revisit'}`;
  const dupes = S.runs.filter(x => x.release === r.release && x.observation === r.observation).length > 1;
  const legacy = String(r.fusion_version || '').includes('v2') ? '' : ' · earlier method (V1)';
  return (dupes ? `${base} (${r.run_id})` : base) + legacy;
}
function currentRun() { return S.runs.find(r => r.directory === S.run) || {}; }
function listParams(extra = {}) { return { run: S.run, ...S.filters, ...extra }; }
function saveFilters() { store.set('s:MoSPI.filters', { run: S.run, filters: S.filters, page: S.page }); }
function crumbs(parts) { document.title = [...parts.slice().reverse(), 'MoSPI'].join(' · '); }
function emptyState(title, text, action = '') {
  return `<div class="empty"><span class="empty-ico">${icon('inbox')}</span><b>${esc(title)}</b><span>${esc(text)}</span>${action}</div>`;
}
async function overviewData(force = false) {
  if (!force && S.ov && S.ov.run === S.run) return S.ov.data;
  const data = await api(url('/api/overview', { run: S.run }));
  S.ov = { run: S.run, data };
  return data;
}

/* ------------------------------------------------------------ design primitives */

const tag = (text, cls = '') => `<span class="tag ${cls}">${esc(text)}</span>`;
// Large figures follow the reference typography: the currency sign and % are set small beside the numerals.
function bigValue(text) {
  return esc(text).replace(/^(−?)₹/, '$1<span class="cur">₹</span>').replace(/%$/, '<sup>%</sup>').replace(/ (hours?|years)$/, '<span class="unit"> $1</span>');
}
// A number that counts up when its section scrolls into view; the final (stored) value is always the text.
const count = v => `<span data-count="${Number(v) || 0}">${n(v)}</span>`;

// Chips: colour carries meaning — red highest priority / issue, yellow waiting / follow-up, green valid, violet whole FSU.
const BAND_TONE = { CRITICAL: 'red', HIGH: 'amber', MEDIUM: 'ink', LOW: 'plain', NOT_ASSESSABLE: '' };
const STATUS_TONE = { CONFIRMED_VALID: 'green', CONFIRMED_ISSUE: 'red', INCONCLUSIVE_NEEDS_FOLLOW_UP: 'amber', UNREVIEWED: 'plain' };
const STATUS_TEXT = { CONFIRMED_VALID: 'Confirmed valid', CONFIRMED_ISSUE: 'Issue confirmed', INCONCLUSIVE_NEEDS_FOLLOW_UP: 'Needs follow-up', UNREVIEWED: 'Not yet reviewed' };
const GROUP_TONE = { HIGH: 'violet', MEDIUM: 'violet', LOW: 'plain', NOT_ASSESSABLE: '' };
const bandChip = (code, label) => `<span class="chip ${BAND_TONE[code] ?? ''}"><span class="dot"></span>${esc(label || S.labels?.bands?.[code] || code)}</span>`;
const statusChip = code => `<span class="chip st ${STATUS_TONE[code] || 'plain'}"><span class="dot"></span>${esc(STATUS_TEXT[code] || code)}</span>`;
const groupChip = (code, label) => `<span class="chip ${GROUP_TONE[code] ?? ''}"><span class="dot"></span>${esc(label || code)}</span>`;
// Strength = how unusual a check found the record, never how likely it is to be wrong.
function strengthBadge(s, group = false) {
  if (!s) return '<span class="strength">Not available</span>';
  const bars = { low: 1, some: 2, high: 3, very: 4 }[s.level];
  const meter = bars ? `<i aria-hidden="true">${[1, 2, 3, 4].map(i => `<b class="${i <= bars ? 'on' : ''}"></b>`).join('')}</i>` : '';
  return `<span class="strength ${esc(s.level)} ${group ? 'g' : ''}">${meter}${esc(s.label)}</span>`;
}

// Decorative light streaks for the dark hero (deterministic; no data).
function streaks() {
  let seed = 11;
  const r = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const reds = ['#ff2a17', '#ff3b22', '#e3170b', '#ff5a2e', '#b80f08', '#ff7a3d'];
  const strands = [];
  // Ribbons sweep diagonally from upper-left to lower-right with an S-bend, in dense fibrous bundles.
  const bundle = (x, spread, count, drift, wide) => {
    for (let i = 0; i < count; i++) {
      const o = (r() - 0.5) * spread, j = () => (r() - 0.5) * spread * 0.22;
      const x0 = x + o, w = wide ? 46 + r() * 50 : 0.7 + r() ** 2.2 * 7;
      const d = `M${(x0 + j()).toFixed(0)},-90 C${(x0 + drift * 0.95 + j()).toFixed(0)},150 ${(x0 + drift * 0.05 + j()).toFixed(0)},470 ${(x0 + drift * 1.05 + j()).toFixed(0)},900`;
      const color = reds[Math.floor(r() * reds.length)];
      strands.push(`<path d="${d}" stroke="${color}" stroke-width="${w.toFixed(1)}" stroke-opacity="${(wide ? 0.22 + r() * 0.16 : 0.45 + r() * 0.55).toFixed(2)}"${wide ? ' filter="url(#blur)"' : ''}/>`);
    }
  };
  bundle(430, 160, 5, 430, true); bundle(840, 200, 5, 400, true);
  bundle(420, 150, 54, 430); bundle(830, 190, 48, 400); bundle(1180, 120, 18, 260);
  const ash = `<path d="M690,-90 C1050,180 700,470 1080,900" stroke="#3d4a46" stroke-width="2.2" stroke-opacity=".7"/><path d="M1060,-90 C1300,200 1100,470 1400,900" stroke="#33403d" stroke-width="1.5" stroke-opacity=".55"/>`;
  return `<svg class="streaks" viewBox="0 0 1400 800" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
    <defs><filter id="blur" x="-50%" y="-10%" width="200%" height="120%"><feGaussianBlur stdDeviation="14"/></filter></defs>
    <g fill="none" stroke-linecap="round">${strands.join('')}${ash}</g></svg>`;
}
// Perspective floor, as under the reference's hero and closing section (decorative).
function floor(stroke) {
  const w = 1400, h = 260, vx = 700, lines = [];
  for (let i = 1; i <= 13; i++) { const y = h * (i / 13) ** 1.9; lines.push(`<line x1="0" x2="${w}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}"/>`); }
  for (let k = -16; k <= 16; k++) lines.push(`<line x1="${vx + k * 26}" y1="0" x2="${vx + k * 150}" y2="${h}"/>`);
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><g stroke="${stroke}" stroke-width="1" vector-effect="non-scaling-stroke">${lines.join('')}</g></svg>`;
}

// Scroll reveal and count-up, as in the reference (fade and rise; numbers run up to their stored value).
function countUp(el) {
  const target = Number(el.dataset.count);
  if (!MOTION || !Number.isFinite(target) || target === 0) { el.textContent = n(target); return; }
  const t0 = performance.now(), dur = 950;
  const step = t => { const k = Math.min(1, (t - t0) / dur); el.textContent = n(Math.round(target * (1 - (1 - k) ** 3))); if (k < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}
function reveal(root = app) {
  const items = [...root.querySelectorAll('.rv:not([data-rv])')];
  items.forEach(el => { el.dataset.rv = '1'; });
  if (!MOTION || !('IntersectionObserver' in window)) { items.forEach(el => el.classList.add('in')); return; }
  items.forEach(el => el.querySelectorAll('[data-count]').forEach(c => { c.textContent = n(0); }));
  const io = new IntersectionObserver(entries => entries.forEach(e => {
    if (!e.isIntersecting) return;
    io.unobserve(e.target);
    e.target.classList.add('in');
    e.target.querySelectorAll('[data-count]').forEach(countUp);
  }), { threshold: 0.08, rootMargin: '0px 0px -40px 0px' });
  items.forEach(el => io.observe(el));
  (S.observers ||= []).push(io);
}

/* ------------------------------------------------------------ routing */

const routes = { overview, cases, case: casePage, groups, group: groupPage, areas, reviewed, technical };

async function route() {
  const [path, query] = location.hash.replace(/^#\/?/, '').split('?');
  const [name, ...rest] = path.split('/');
  const page = routes[name] ? name : 'overview';
  document.querySelectorAll('#nav a').forEach(a => {
    const on = a.dataset.route === (page === 'case' ? 'cases' : page === 'group' ? 'groups' : page);
    a.classList.toggle('active', on);
    if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  document.body.classList.toggle('on-hero', page === 'overview');
  document.body.dataset.page = page;
  setMenu(false);
  if (S.keys) { document.removeEventListener('keydown', S.keys); S.keys = null; }
  if (S.spy) { S.spy.disconnect(); S.spy = null; }
  (S.observers || []).forEach(o => o.disconnect()); S.observers = [];
  notice(S.flash?.text || '', S.flash?.kind || ''); S.flash = null;
  app.innerHTML = page === 'case' ? caseSkeleton() : page === 'overview' ? `<section class="hero hero-loading"><div class="hero-art" aria-hidden="true">${streaks()}<div class="hero-floor">${floor('rgba(255,255,255,.085)')}</div></div><div class="hero-body"><h1 class="display">What should I review today?</h1><p class="hero-sub"><span class="spinner light"></span> Loading your review queue…</p></div></section>` : '<div class="loading"><span class="spinner"></span>Loading…</div>';
  try {
    await routes[page](decodeURIComponent(rest.join('/')), new URLSearchParams(query || ''));
  } catch (e) {
    app.innerHTML = `<div class="panel">${emptyState('This page could not be loaded.', e.message)}</div>`;
  }
  app.classList.remove('enter'); void app.offsetWidth; app.classList.add('enter');
  reveal();
  window.scrollTo(0, 0);
  onScroll();
}
function onScroll() {
  document.body.classList.toggle('scrolled', window.scrollY > 8);
  const nav = document.querySelector('.case-nav'); if (nav) nav.classList.toggle('stuck', window.scrollY > 4);
}
window.addEventListener('hashchange', route);
window.addEventListener('scroll', onScroll, { passive: true });
function go(hash) { if (location.hash === hash) route(); else location.hash = hash; }
function openList(filters) { S.filters = filters; S.page = 1; saveFilters(); go('#/cases'); }
function setMenu(open) {
  document.body.classList.toggle('menu-open', open);
  document.querySelector('#menuBtn').setAttribute('aria-expanded', String(open));
}
document.querySelector('#menuBtn').onclick = () => setMenu(!document.body.classList.contains('menu-open'));

function caseSkeleton() {
  const line = (w, h = 14) => `<div class="skeleton" style="height:${h}px;width:${w}"></div>`;
  return `<div class="case-layout"><div class="case-main"><div class="panel" style="display:flex;flex-direction:column;gap:16px">${line('22%', 26)}${line('40%', 14)}${line('55%', 90)}${line('70%')}${line('100%', 70)}</div>
    <div class="panel" style="display:flex;flex-direction:column;gap:12px">${line('30%', 22)}${line('100%', 64)}${line('100%', 64)}${line('100%', 64)}</div></div>
    <aside class="rail"><div class="card" style="display:flex;flex-direction:column;gap:12px">${line('40%', 12)}${line('100%')}${line('100%')}${line('80%')}</div></aside></div>`;
}

/* ------------------------------------------------------------ overview: what should I review today? */

const REASONS = [
  ['statistical', 'Unusual compared with similar records', 'compare'],
  ['historical', 'Unusual compared with earlier periods', 'history'],
  ['ml', 'Unusual combination of answers', 'combo'],
  ['contextual', 'Uncommon occupation for similar people', 'work'],
  ['rules', 'A documented questionnaire rule is not met', 'rule'],
];
const BAND_ORDER = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];
const BAND_WORD = { CRITICAL: 'Highest', HIGH: 'High', MEDIUM: 'Medium', LOW: 'Low' };

async function overview() {
  crumbs(['Overview']);
  const [o, next, rev, agg, grp] = await Promise.all([
    overviewData(true),
    api(url('/api/cases', { run: S.run, priority_band: 'CRITICAL', review_status: 'UNREVIEWED', limit: 3, summaries: true })),
    api(url('/api/reviews', { run: S.run })),
    api(url('/api/aggregates', { run: S.run, level: 'state', limit: 1 })).catch(() => ({ available: false, notable: [] })),
    api(url('/api/groups', { run: S.run, band: 'ALERTS', limit: 3 })).catch(() => ({ rows: [], total: 0 })),
  ]);
  const bands = Object.fromEntries(o.bands.map(b => [b.band, b]));
  const top = bands.CRITICAL?.records || 0;
  const topDone = bands.CRITICAL?.reviewed || 0;
  const remaining = top - topDone;
  const r = o.review;
  const groups = Object.fromEntries(o.groups.map(g => [g.band, g.groups]));
  const groupAlerts = (groups.HIGH || 0) + (groups.MEDIUM || 0);
  const areaAlerts = o.aggregate_alerts;
  const reasons = o.highest_reasons || {};
  const share = Math.round((1 - (o.unusual_threshold ?? UNUSUAL)) * 100);
  const reasonRows = REASONS.filter(([k]) => reasons[k] != null && (k !== 'rules' || reasons[k] > 0));
  const maxReason = Math.max(1, ...reasonRows.map(([k]) => reasons[k]), reasons.combined_only || 0);
  const donePct = top ? (topDone / top) * 100 : 0;
  const donePctText = donePct === 0 ? '0' : donePct < 1 ? '<1' : String(Math.floor(donePct));

  // Hero card 1: the ranked list by priority group, one dot column per group (dots scaled to the largest group; counts exact).
  const maxBand = Math.max(1, ...BAND_ORDER.map(b => bands[b]?.records || 0));
  const dotCols = BAND_ORDER.filter(b => bands[b]).map(b => {
    const v = bands[b].records, dots = Math.max(1, Math.round((v / maxBand) * 5));
    return `<a class="dcol ${b === 'CRITICAL' ? 'hot' : ''}" href="#/cases" data-band="${b}" title="${esc(bands[b].label)}: ${n(v)} records">
      <span class="dn">${n(v)}</span><span class="dots">${'<i></i>'.repeat(dots)}</span><span class="dl">${BAND_WORD[b]}</span></a>`;
  }).join('');

  // Explorer panels: real records, FSUs, area changes and decisions only.
  const first = next.rows[0];
  const nextRows = next.rows.map((c, i) => {
    const f = splitFinding(c.unusual);
    return `<a class="mrow" href="#/case/${encodeURIComponent(c.case_id)}?pos=${i + 1}" data-queue>
      <span class="mpos">${i + 1}</span>
      <span class="mtxt"><b>${esc(f.value || f.label)}</b><small>${esc(f.typical ? `typical ${f.typical}` : f.label)} · ${esc(c.location_label)}</small></span>
      <span class="marr">${icon('right')}</span></a>`;
  }).join('');
  const firstFocus = first?.comparison ? `<div class="mc white m-focus">
      <div class="mc-k">${icon('spark')}Case 1 in your queue</div>
      <div class="mf-v">${bigValue(fmt(first.comparison.observed, first.comparison.unit))}</div>
      <p class="mf-s">Reported ${esc(first.comparison.short)} · typical ${esc(fmt(first.comparison.typical, first.comparison.unit))}</p>
      ${miniRange(first.comparison)}
      <div class="mf-tags">${reasonTags(first)}</div></div>` : '';
  const darkStat = (value, label, href, id = '') => `<div class="mc dark m-stat"><div class="ms-v">${value}</div><p>${label}</p><a class="btn light sm" href="${href}" ${id}>View all</a></div>`;
  const groupRows = grp.rows.map(g => `<a class="mrow" href="#/group/${encodeURIComponent(g.fsu)}?state=${encodeURIComponent(g.state)}">
      <span class="mpos v">${icon('people')}</span>
      <span class="mtxt"><b>FSU ${esc(g.fsu)}</b><small>${esc(g.patterns[0]?.text || g.location_label)}</small></span><span class="marr">${icon('right')}</span></a>`).join('');
  const areaRows = (agg.notable || []).slice(0, 3).map(a => `<a class="mrow" href="#/areas?${new URLSearchParams({ level: a.level, indicator: a.indicator, area: a.area_label })}">
      <span class="mpos r">${slopeGlyph(a.change)}</span>
      <span class="mtxt"><b>${esc(a.area_label)}</b><small>${esc(shortIndicator(a.indicator_label))}: ${esc(indicatorValue(a.indicator, a.previous_value))} → ${esc(indicatorValue(a.indicator, a.value))} · ${esc(a.period_label)}</small></span><span class="marr">${icon('right')}</span></a>`).join('');
  const decisionRows = rev.rows.slice(0, 4).map(x => `<a class="mrow" href="#/case/${encodeURIComponent(x.case_id)}?from=reviewed">
      <span class="mpos av">${esc(initials(x.actor))}</span>
      <span class="mtxt"><b>${esc(x.record_label)}</b><small>${esc(STATUS_TEXT[x.decision] || x.decision)} · ${esc(x.actor)} · ${esc(when(x.decided_at_utc))}</small></span><span class="marr">${icon('right')}</span></a>`).join('');
  const actors = [...new Map(rev.rows.map(x => [x.actor, x])).keys()];

  const TABS = [
    ['next', 'Up next', 'cases', 'Up next in your queue'],
    ['groups', 'Group alerts', 'groups', 'Whole FSUs that differ from comparable FSUs'],
    ['areas', 'Area trends', 'areas', 'Unusual changes in area indicators'],
    ['decisions', 'Recent decisions', 'reviewed', 'What has already been decided'],
  ];
  const panels = {
    next: `<div class="mc white m-list"><div class="mc-k">${icon('cases')}Up next in your queue</div>${nextRows || '<p class="empty-line">No highest-priority record is waiting for a decision.</p>'}</div>
      ${firstFocus}${darkStat(count(remaining), 'highest-priority records waiting', '#/cases', 'data-open-critical')}`,
    groups: `<div class="mc white m-list"><div class="mc-k">${icon('people')}Strongest group differences ${tag('Whole FSU', 'violet')}</div>${groupRows || '<p class="empty-line">No FSU-level group alert in this survey round.</p>'}</div>
      <div class="mc white m-note"><div class="mc-k">${icon('info')}About group alerts</div><p>These describe whole FSUs, not individual records. An alert does not mean that any person's record is wrong.</p>
        <div class="pbar"><span class="seg v" style="flex:${groups.HIGH || 0}">${n(groups.HIGH || 0)} clear</span><span class="seg vl" style="flex:${groups.MEDIUM || 0}">${n(groups.MEDIUM || 0)} some</span></div></div>
      ${darkStat(count(groupAlerts), 'FSUs with a group difference', '#/groups')}`,
    areas: `<div class="mc white m-list"><div class="mc-k">${icon('areas')}Largest unusual changes</div>${areaRows || `<p class="empty-line">${areaAlerts == null ? 'No historical run is attached to this survey round.' : 'No unusual change in area indicators.'}</p>`}</div>
      ${darkStat(areaAlerts == null ? '—' : count(areaAlerts), 'period-on-period changes that stand out from other areas', '#/areas')}`,
    decisions: `<div class="mc white m-list"><div class="mc-k">${icon('reviewed')}Recent decisions</div>${decisionRows || '<p class="empty-line">No decisions have been recorded for this survey round yet.</p>'}</div>
      ${darkStat(count(r.decided), `cases decided${r.last_decision_utc ? ` · last ${esc(when(r.last_decision_utc))}` : ''}`, '#/reviewed')}`,
  };

  app.innerHTML = `
    <section class="hero rv" aria-labelledby="heroTitle">
      <div class="hero-art" aria-hidden="true">${streaks()}<div class="hero-floor">${floor('rgba(255,255,255,.085)')}</div></div>
      <div class="hero-body">
        <span class="hero-tile" aria-hidden="true"><svg viewBox="0 0 64 40"><path d="M2 30 C10 30 12 22 18 22 S26 32 32 28 40 6 44 6 50 30 62 26" stroke="#8b8b90" stroke-width="2" fill="none"/><path d="M2 32 C12 32 16 26 22 27 S30 34 36 30 44 16 48 18 56 30 62 24" stroke="#f15d4d" stroke-width="2" fill="none"/></svg></span>
        <h1 id="heroTitle" class="display">What should I review today?</h1>
        <p class="hero-sub">${remaining > 0 ? `<b>${count(remaining)}</b> highest-priority ${plural(remaining, 'record')} waiting for a decision` : top ? 'Every highest-priority record has a decision' : 'No record is in the highest-priority group'} — ${esc(runLabel(currentRun()))}</p>
        <div class="hero-actions">
          ${remaining > 0 ? `<button class="btn light lg" id="start">Start review ${icon('right')}</button>`
            : `<button class="btn light lg" id="continueHigh">Continue with high priority ${icon('right')}</button>`}
          <a class="btn glass lg" href="#/cases" id="viewAll">See the full ranked list</a>
        </div>
      </div>
      <div class="hero-cards">
        <div class="fcard">
          <div class="fc-head"><span class="fc-sq">${MARK}</span><span class="fc-t"><b>${n(o.priority_rows)}</b> records ranked <br><small>by priority group</small></span></div>
          <div class="dotm" role="img" aria-label="${esc(BAND_ORDER.filter(b => bands[b]).map(b => `${bands[b].label}: ${n(bands[b].records)}`).join('; '))}">${dotCols}</div>
        </div>
        <div class="fcard">
          <div class="fc-row"><div class="fc-k">${icon('info')}Highest priority · ${n(topDone)} of ${n(top)} decided</div>
            <div class="pbar">${remaining > 0 ? `<span class="seg y" style="flex:${remaining}">${n(remaining)} waiting</span>` : ''}${topDone ? `<span class="seg g" style="flex:${topDone}">${n(topDone)} decided</span>` : ''}${!top ? '<span class="seg e" style="flex:1">No records</span>' : ''}</div></div>
          <div class="fc-row"><div class="fc-k">${icon('info')}Alerts outside the record queue</div>
            <div class="pbar"><a class="seg v" href="#/groups" style="flex:${groupAlerts || 1}" title="FSUs with a group difference">${n(groupAlerts)} FSUs</a>${areaAlerts != null ? `<a class="seg r" href="#/areas" style="flex:${areaAlerts || 1}" title="Unusual changes in area indicators">${n(areaAlerts)} areas</a>` : ''}</div></div>
        </div>
      </div>
    </section>

    <div class="duo">
      <section class="panel rv reasons-card">
        ${tag('Why these records are here')}
        <h2 class="display h2">What puts ${n(top)} records at the top of the list</h2>
        <p class="body-l">Each check compares a record with similar records, with earlier periods, or with the answers people usually give together. A record can have more than one reason, so the rows add up to more than ${n(top)}.</p>
        <div class="reasons">
          ${reasonRows.map(([k, label, ic]) => `<button class="reason" data-reason="${k}" ${k === 'rules' ? 'disabled' : ''}><span class="ri">${icon(ic)}</span><span class="t">${esc(label)}</span><span class="n">${count(reasons[k])}</span><span class="bar"><i style="--w:${(reasons[k] / maxReason) * 100}%"></i></span>${k !== 'rules' ? `<span class="go">${icon('right')}</span>` : ''}</button>`).join('')}
          ${reasons.combined_only != null ? `<div class="reason muted-r"><span class="ri">${icon('layers')}</span><span class="t">No single check stands out — placed here by several checks together and by its potential effect</span><span class="n">${count(reasons.combined_only)}</span><span class="bar"><i style="--w:${(reasons.combined_only / maxReason) * 100}%"></i></span></div>` : ''}
        </div>
        <p class="note">“Unusual” means the check puts the record among the ${share}% most unusual records it assessed. Select a reason to open those records.</p>
      </section>

      <section class="panel rv progress-card">
        <div class="pc-top">
          <p class="pc-q">${actors.length ? 'Decisions recorded by' : 'No decisions recorded yet'}</p>
          <a class="avatars" href="${actors.length ? '#/reviewed' : '#/cases'}" ${actors.length ? '' : 'data-open-critical'}>
            ${actors.slice(0, 3).map((a, i) => `<span class="av a${i}" title="${esc(a)}">${esc(initials(a))}</span>`).join('')}
            <span class="av plus" title="${actors.length ? 'All reviewed cases' : 'Start reviewing'}">${icon('plus')}</span></a>
        </div>
        <div class="pc-bottom">
          ${tag('Your progress')}
          <div class="giant"><span class="g">${/^\d+$/.test(donePctText) ? count(donePctText) : esc(donePctText)}<sup>%</sup></span>
            <p class="gl">of the highest-priority queue has a decision · <b>${n(topDone)} of ${n(top)}</b>${r.last_decision_utc ? `<br>Last decision ${esc(when(r.last_decision_utc))}` : ''}</p></div>
          <div class="pstats">
            <a class="pstat" href="#/reviewed"><i class="ink"></i><b>${n(r.decided)}</b><span>Reviewed</span></a>
            <a class="pstat" href="#/reviewed?decision=CONFIRMED_VALID"><i class="green"></i><b>${n(r.decisions.CONFIRMED_VALID)}</b><span>Confirmed valid</span></a>
            <a class="pstat" href="#/reviewed?decision=CONFIRMED_ISSUE"><i class="red"></i><b>${n(r.decisions.CONFIRMED_ISSUE)}</b><span>Issues confirmed</span></a>
            <a class="pstat" href="#/reviewed?decision=INCONCLUSIVE_NEEDS_FOLLOW_UP"><i class="amber"></i><b>${n(r.decisions.INCONCLUSIVE_NEEDS_FOLLOW_UP)}</b><span>Needs follow-up</span></a>
          </div>
        </div>
      </section>
    </div>

    <section class="panel rv explorer">
      <div class="ex-side">
        ${tag('Where to look next')}
        <h2 class="h3">Everything waiting for you, in one place</h2>
        <div class="vtabs" role="tablist" aria-label="Explore">
          ${TABS.map(([k, l, ic], i) => `<button role="tab" class="${i ? '' : 'on'}" aria-selected="${!i}" aria-controls="mp-${k}" data-tab="${k}">${icon(ic)}<span>${esc(l)}</span></button>`).join('')}
        </div>
      </div>
      <div class="ex-main">
        <div class="media">
          <div class="media-label"><i></i><span id="mediaLabel">${esc(TABS[0][3])}</span></div>
          ${TABS.map(([k], i) => `<div class="mpanel mp-${k} ${i ? '' : 'on'}" id="mp-${k}" role="tabpanel" ${i ? 'aria-hidden="true"' : ''}>${panels[k]}</div>`).join('')}
        </div>
        <details class="acc"><summary><span class="acc-ico">${icon('compare')}</span><span class="acc-t">About the size of the review list</span><span class="acc-h">${n(o.priority_rows)} of ${n(o.records_processed)} records have a priority</span>${icon('chev', 'acc-chev')}</summary>
          <div class="acc-body">
            <div class="band-table">${['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'NOT_ASSESSABLE'].filter(b => bands[b]).map(b => `<div>${bandChip(b, bands[b].label)}<span>${n(bands[b].records)} records · ${n(bands[b].reviewed)} decided</span></div>`).join('')}</div>
            <p class="note">${n(o.priority_rows)} of ${n(o.records_processed)} records (${pct(o.priority_rows, o.records_processed)}) received a priority. This does <b>not</b> mean they contain errors: every record that could be compared with similar records gets a place in one ranked list. The priority groups are fixed score ranges, not workload targets, and no review cut-off has been set, so work from the top.
            ${o.not_prioritised ? ` ${n(o.not_prioritised)} records have no priority, mostly because no earnings or hours question applies to them (for example students, people in domestic duties, children). They are still checked against the documented rules and appear at the end of the list.` : ''}</p>
          </div></details>
        <details class="acc"><summary><span class="acc-ico">${icon('balance')}</span><span class="acc-t">Unusual does not mean incorrect</span><span class="acc-h">how to read a flag</span>${icon('chev', 'acc-chev')}</summary>
          <div class="acc-body"><p class="note">A flag says that a record stands out from comparable records, from earlier periods or from the answers people usually give together. Many unusual values are genuine. Only your review against the schedule can decide whether a value is correct; your decision is recorded with your name in the audit trail.</p></div></details>
      </div>
    </section>

    <section class="panel rv cta">
      <div class="cta-floor" aria-hidden="true">${floor('rgba(12,12,12,.075)')}</div>
      <span class="cta-mark" aria-hidden="true">${MARK}</span>
      <h2 class="display">One case at a time, highest priority first</h2>
      <p>Cases open in priority order. Your decision, your name and a snapshot of the evidence are added to the audit trail — the survey data are never changed.</p>
      ${remaining > 0 ? `<button class="btn dark lg" id="start2">Start review ${icon('right')}</button>` : '<a class="btn dark lg" href="#/cases">Open the ranked list</a>'}
    </section>`;

  const queue = () => { S.filters = { priority_band: 'CRITICAL', review_status: 'UNREVIEWED' }; S.page = 1; saveFilters(); };
  document.querySelector('#start')?.addEventListener('click', () => { queue(); openPosition(1); });
  document.querySelector('#start2')?.addEventListener('click', () => { queue(); openPosition(1); });
  document.querySelector('#continueHigh')?.addEventListener('click', () => { S.filters = { priority_band: 'HIGH', review_status: 'UNREVIEWED' }; S.page = 1; saveFilters(); openPosition(1); });
  app.querySelectorAll('[data-queue]').forEach(a => a.addEventListener('click', queue));
  app.querySelectorAll('[data-open-critical]').forEach(a => a.addEventListener('click', e => { e.preventDefault(); openList({ priority_band: 'CRITICAL', review_status: 'UNREVIEWED' }); }));
  document.querySelector('#viewAll').onclick = () => { S.filters = {}; S.page = 1; saveFilters(); };
  app.querySelectorAll('.dcol[data-band]').forEach(a => a.onclick = e => { e.preventDefault(); openList({ priority_band: a.dataset.band }); });
  app.querySelectorAll('[data-reason]').forEach(b => b.onclick = () => openList({ priority_band: 'CRITICAL', strong_source: b.dataset.reason }));
  // vertical tabs drive the media panel (cross-fade, as in the reference)
  const tabs = [...app.querySelectorAll('.vtabs [data-tab]')];
  const select = btn => {
    tabs.forEach(t => { const on = t === btn; t.classList.toggle('on', on); t.setAttribute('aria-selected', String(on)); });
    app.querySelectorAll('.mpanel').forEach(p => { const on = p.id === `mp-${btn.dataset.tab}`; p.classList.toggle('on', on); p.toggleAttribute('aria-hidden', !on); if (on) p.querySelectorAll('[data-count]').forEach(countUp); });
    document.querySelector('#mediaLabel').textContent = TABS.find(t => t[0] === btn.dataset.tab)[3];
  };
  tabs.forEach((t, i) => {
    t.onclick = () => select(t);
    t.onkeydown = e => { const d = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[e.key]; if (d) { e.preventDefault(); const nxt = tabs[(i + d + tabs.length) % tabs.length]; nxt.focus(); select(nxt); } };
  });
}

/* ------------------------------------------------------------ case list */

const REASON_CHIPS = [['statistical_rank', 'Similar records'], ['historical_rank', 'Earlier periods'], ['ml_rank', 'Answer combination'], ['contextual_rank', 'Occupation']];
const BAND_CHIPS = [['', 'All'], ['CRITICAL', 'Highest'], ['HIGH', 'High'], ['MEDIUM', 'Medium'], ['LOW', 'Low'], ['NOT_ASSESSABLE', 'Not calculated']];
const REVIEW_CHIPS = [['', 'All'], ['UNREVIEWED', 'Not yet reviewed'], ['REVIEWED', 'Reviewed'], ['CONFIRMED_ISSUE', 'Issue confirmed'], ['CONFIRMED_VALID', 'Confirmed valid'], ['INCONCLUSIVE_NEEDS_FOLLOW_UP', 'Needs follow-up']];
const STRONG_SOURCES = [['', 'Any reason'], ['statistical', 'Unusual compared with similar records'], ['historical', 'Unusual compared with earlier periods'], ['ml', 'Unusual combination of answers'], ['contextual', 'Uncommon occupation']];

// Splits the stored one-line summary (fusion/explain.py) into finding, value and comparison so each can be
// typeset on its own. Wording is never changed; any other form of summary is shown whole.
function splitFinding(text) {
  const [lead, ...rest] = String(text || '').split(' — ');
  const m = /^(Reported .+?) (₹?[-−]?[\d,.]+(?: hours?| years)?|not recorded)$/.exec(lead);
  const c = /^(above|below|within) the usual range; typical (.+) for ([\d,]+ comparable records?)$/.exec(rest.join(' — '));
  return { label: m ? m[1] : lead, value: m ? m[2] : '', dir: c?.[1] || '', typical: c?.[2] || '', peers: c?.[3] || '', other: c ? '' : rest.join(' — ') };
}

function reasonTags(r) {
  const tags = [
    ...(r.rule_violation ? ['<span class="rtag">Questionnaire rule</span>'] : []),
    ...REASON_CHIPS.filter(([k]) => Number(r[k]) >= UNUSUAL).map(([, l]) => `<span class="rtag">${l}</span>`),
    ...(Number(r.pattern_notable_checks) > 0 ? ['<span class="rtag v" title="Context about the whole FSU; it does not move the record up the list">FSU context</span>'] : []),
  ];
  return tags.length ? tags.join('') : '<span class="rtag none">No single check stands out</span>';
}

// Where a value sits on a scale built from the stored 5% / 95% points (and the value itself).
// Far-outside values get a shortened scale, marked with a break, so the usual range stays readable.
function scaleFor(q05, q95, obs) {
  const span = Math.max(q95 - q05, 1e-9);
  if (obs > q95 + 1.5 * span) return { place: v => 3 + ((v - q05) / span) * 70, breakAt: 82, obsAt: 93 };
  if (obs < q05 - 1.5 * span) return { place: v => 27 + ((v - q05) / span) * 70, breakAt: 18, obsAt: 7 };
  const lo = Math.min(q05, obs), hi = Math.max(q95, obs), w = Math.max(hi - lo, 1e-9);
  const place = v => 4 + ((v - lo) / w) * 92;
  return { place, breakAt: null, obsAt: place(obs) };
}
// Compact strip for lists: usual range (9 in 10), typical, and this record.
function miniRange(c) {
  const vals = [c.low, c.typical, c.high, c.observed].map(Number);
  if (!vals.every(Number.isFinite)) return '';
  const [q05, med, q95, obs] = vals;
  const { place, breakAt, obsAt } = scaleFor(q05, q95, obs);
  const x05 = place(q05), x95 = place(q95), x50 = place(med);
  return `<div class="mini-range" role="img" aria-label="Reported ${esc(fmt(obs, c.unit))}; typical ${esc(fmt(med, c.unit))}; 9 in 10 similar records between ${esc(fmt(q05, c.unit))} and ${esc(fmt(q95, c.unit))}">
    <span class="mr-track"></span><span class="mr-band" style="left:${x05}%;width:${Math.max(x95 - x05, 1)}%"></span>
    <span class="mr-med" style="left:${x50}%"></span>${breakAt ? `<span class="mr-brk" style="left:${breakAt}%"></span>` : ''}
    <span class="mr-obs ${c.position === 'CENTRAL_REFERENCE_RANGE' ? 'calm' : ''}" style="left:${obsAt}%"></span></div>`;
}

function caseCard(r, { href, feature = false } = {}) {
  const c = r.comparison;
  const f = splitFinding(r.unusual);
  const done = r.review_status && r.review_status !== 'UNREVIEWED';
  const unit = c?.unit || '';
  const value = c && c.observed != null ? fmt(c.observed, unit) : f.value;
  const label = c ? `Reported ${c.short}` : f.value ? f.label : '';
  const compact = !c && !value; // no applicable value to compare: one calm line, no empty figure area
  const why = c && c.position ? leadSentence({ observed_value: c.observed, quantile_0_05: c.low, quantile_0_95: c.high, distribution_position: c.position, peer_median: c.typical }, unit) : f.other;
  const figs = c ? `<div class="cc-figs">
      <div><span>Typical</span><b>${esc(fmt(c.typical, unit))}</b></div>
      <div><span>Usual range</span><b>${esc(fmt(c.low, unit))}–${esc(fmt(c.high, unit))}</b></div>
      <div><span>Comparable records</span><b>${n(c.comparable)}</b></div></div>` : '';
  return `<a class="case-card${feature ? ' feature' : ''}${compact ? ' compact' : ''}${done ? ' done' : ''} b-${esc(r.priority_band)}" href="${href}">
    <div class="cc-a">
      ${feature ? '<span class="cc-start"><i></i>Start here · highest in this list</span>' : ''}
      <div class="cc-top">${r.position ? `<span class="cc-pos">${n(r.position)}</span>` : ''}${bandChip(r.priority_band, r.band_label)}${done ? statusChip(r.review_status) : ''}</div>
      ${label ? `<div class="cc-label">${esc(label)}</div>` : ''}
      ${value ? `<div class="cc-value">${bigValue(value)}</div>` : ''}
      ${why ? `<p class="cc-why">${esc(why)}</p>` : ''}
    </div>
    <div class="cc-b">${c ? `${miniRange(c)}${figs}` : `<p class="cc-none">${esc(r.unusual || 'No comparison is available for this record.')}</p>`}</div>
    <div class="cc-c">
      <div class="cc-reasons">${reasonTags(r)}</div>
      <div class="cc-loc">${icon('pin')}<span>${esc(r.location_label)} · FSU ${esc(r.fsu)}</span></div>
      <div class="cc-rec">${esc(r.record_label)}</div>
      <span class="cc-go">${done ? 'Open case' : 'Review case'} ${icon('right')}</span>
    </div>
  </a>`;
}

function caseRows(rows, { positions = true, from = '' } = {}) {
  if (!rows.length) return `<div class="panel">${emptyState('No cases match these filters.', 'Try removing a filter, or choose another priority group.')}</div>`;
  return `<div class="case-list">${rows.map(r => caseCard({ ...r, position: positions ? r.position : null },
    { href: `#/case/${encodeURIComponent(r.case_id)}${positions ? `?pos=${r.position}` : from ? `?from=${from}` : ''}` })).join('')}</div>`;
}

// The work queue: the first case on the first page is set apart; every card reads value → why → comparison → reasons → open.
function queueRows(rows, offset) {
  if (!rows.length) return `<div class="panel">${emptyState('No cases match these filters.', 'Try removing a filter, or choose another priority group.')}</div>`;
  return `<div class="case-list">${rows.map((r, i) => caseCard(r, { href: `#/case/${encodeURIComponent(r.case_id)}?pos=${r.position}`, feature: offset === 0 && i === 0 && r.review_status === 'UNREVIEWED' })).join('')}</div>`;
}

async function cases() {
  crumbs(['Cases to review']);
  const f = S.filters;
  const o = await overviewData().catch(() => null);
  const counts = o ? Object.fromEntries(o.bands.map(b => [b.band, b.records])) : {};
  const start = (S.page - 1) * PAGE_SIZE + 1;
  const states = Object.entries(S.labels.states).map(([c, l]) => `<option value="${c}" ${f.state === c ? 'selected' : ''}>${esc(l)}</option>`).join('');
  // Priority and status are always visible in their controls; only the tucked-away filters need chips.
  const active = [
    f.strong_source && ['strong_source', STRONG_SOURCES.find(c => c[0] === f.strong_source)?.[1]],
    f.state && ['state', `State/UT: ${S.labels.states[f.state] || f.state}`],
    f.sector && ['sector', `Sector: ${S.labels.sectors[f.sector] || f.sector}`],
    f.fsu && ['fsu', `FSU ${f.fsu}`],
    f.q && ['q', `Search: “${f.q}”`],
  ].filter(Boolean);
  const anyFilter = Object.values(f).some(Boolean);
  const moreOpen = Boolean(S.moreOpen);
  app.innerHTML = `
    <section class="panel q-hero rv">
      <div class="qh-main">
        ${tag('Review queue')}
        <h1 class="display">Cases to review</h1>
        <p class="lede">${esc(runLabel(currentRun()))}. Each case shows what was reported, what similar people usually report, and which checks flagged it.</p>
        <div class="qh-actions">
          <button class="btn dark lg" id="startHere">Review in this order ${icon('right')}</button>
          <a class="btn line lg" id="export" href="${esc(url('/api/export/queue', listParams()))}">${icon('download')}<span id="exportLabel">Download this list (CSV)</span></a>
        </div>
        <p class="qh-hint">${start === 1 ? 'Starts with the highest-ranked case, then works down the list.' : `Starts at case ${n(start)}, then works down the list.`}</p>
      </div>
      <div class="qh-count"><span class="g" id="countBig">—</span><span class="gl" id="meta">Loading…</span></div>
      <div class="q-filters">
        <div class="ptabs" role="group" aria-label="Priority">${BAND_CHIPS.map(([v, l]) => {
          const on = (f.priority_band || '') === v;
          return `<button class="p-${v || 'ALL'}${on ? ' on' : ''}" aria-pressed="${on}" data-band="${v}">${v ? '<i></i>' : ''}<span>${esc(v ? l : 'All priorities')}</span>${v && counts[v] != null ? `<small>${n(counts[v])}</small>` : ''}</button>`;
        }).join('')}</div>
        <div class="qf-row">
          <div class="dtabs" role="group" aria-label="Review status">${REVIEW_CHIPS.map(([v, l]) => { const on = (f.review_status || '') === v; return `<button class="${on ? 'on' : ''}" aria-pressed="${on}" data-status="${v}">${esc(v ? l : 'Any status')}</button>`; }).join('')}</div>
          <button class="btn line sm q-more${active.length ? ' set' : ''}" id="moreBtn" aria-expanded="${moreOpen}" aria-controls="moreFilters">${icon('filter')}More filters${active.length ? ` <b>${active.length}</b>` : ''}${icon('chev', 'chev')}</button>
        </div>
        <div class="q-panel" id="moreFilters" ${moreOpen ? '' : 'hidden'}>
          <label class="fld"><span>Reason</span><select id="fReason">${STRONG_SOURCES.map(([v, l]) => `<option value="${v}" ${f.strong_source === v ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select></label>
          <label class="fld"><span>State/UT</span><select id="fState"><option value="">All States/UTs</option>${states}</select></label>
          <label class="fld"><span>Sector</span><select id="fSector"><option value="">Rural and urban</option><option value="1" ${f.sector === '1' ? 'selected' : ''}>Rural</option><option value="2" ${f.sector === '2' ? 'selected' : ''}>Urban</option></select></label>
          <label class="fld"><span>FSU</span><input id="fFsu" value="${esc(f.fsu || '')}" placeholder="FSU number" inputmode="numeric"></label>
          <label class="fld wide"><span>Search</span><span class="search">${icon('search')}<input type="search" id="fQ" value="${esc(f.q || '')}" placeholder="Record key, case reference or FSU"></span></label>
          <button class="btn dark" id="apply">Apply</button>
        </div>
        ${anyFilter ? `<div class="active-filters">${active.length ? '<span>Also filtered by</span>' : ''}${active.map(([k, l]) => `<span class="fchip">${esc(l)}<button data-remove="${k}" aria-label="Remove filter ${esc(l)}">${icon('plus')}</button></span>`).join('')}<button class="link" id="clear">Clear all filters</button></div>` : ''}
      </div>
    </section>
    <div id="rows"><div class="case-list">${Array.from({ length: 4 }, (_, i) => `<div class="case-card sk${i ? '' : ' feature'}"><div class="cc-a"><span class="skeleton" style="height:22px;width:40%"></span><span class="skeleton" style="height:14px;width:60%"></span><span class="skeleton" style="height:48px;width:70%"></span></div><div class="cc-b"><span class="skeleton" style="height:12px;width:100%"></span><span class="skeleton" style="height:36px;width:90%"></span></div><div class="cc-c"><span class="skeleton" style="height:26px;width:80%"></span><span class="skeleton" style="height:14px;width:60%"></span></div></div>`).join('')}</div></div>
    <div class="pager"><span id="range"></span><div class="btns"><button class="btn line" id="prev">${icon('left')} Previous</button><span id="page"></span><button class="btn line" id="next">Next ${icon('right')}</button></div></div>`;

  const set = (key, value) => { S.filters = { ...S.filters, [key]: value }; S.page = 1; saveFilters(); cases(); };
  app.querySelectorAll('.ptabs button').forEach(b => b.onclick = () => set('priority_band', b.dataset.band));
  app.querySelectorAll('.dtabs button').forEach(b => b.onclick = () => set('review_status', b.dataset.status));
  document.querySelector('#moreBtn').onclick = e => {
    S.moreOpen = !S.moreOpen;
    e.currentTarget.setAttribute('aria-expanded', S.moreOpen);
    document.querySelector('#moreFilters').hidden = !S.moreOpen;
  };
  app.querySelectorAll('[data-remove]').forEach(b => b.onclick = () => { const next = { ...S.filters }; delete next[b.dataset.remove]; S.filters = next; S.page = 1; saveFilters(); cases(); });
  const apply = () => {
    S.filters = { ...S.filters, strong_source: document.querySelector('#fReason').value, state: document.querySelector('#fState').value, sector: document.querySelector('#fSector').value,
      fsu: document.querySelector('#fFsu').value.trim(), q: document.querySelector('#fQ').value.trim() };
    S.page = 1; saveFilters(); cases();
  };
  document.querySelector('#apply').onclick = apply;
  ['#fState', '#fSector', '#fReason'].forEach(s => { document.querySelector(s).onchange = apply; });
  ['#fFsu', '#fQ'].forEach(s => document.querySelector(s).onkeydown = e => { if (e.key === 'Enter') apply(); });
  const clear = document.querySelector('#clear');
  if (clear) clear.onclick = () => { S.filters = {}; S.page = 1; saveFilters(); cases(); };
  document.querySelector('#startHere').onclick = () => openPosition((S.page - 1) * PAGE_SIZE + 1);
  reveal();

  const offset = (S.page - 1) * PAGE_SIZE;
  const data = await api(url('/api/cases', listParams({ offset, limit: PAGE_SIZE, summaries: true })));
  const rowsBox = document.querySelector('#rows');
  rowsBox.innerHTML = queueRows(data.rows, offset);
  rowsBox.querySelectorAll('.case-card').forEach((el, i) => { el.style.setProperty('--i', Math.min(i, 8)); el.classList.add('rise'); });
  const big = document.querySelector('#countBig');
  big.dataset.count = data.total; countUp(big);
  document.querySelector('#meta').innerHTML = `${plural(data.total, 'case')} in this list, <br>highest priority first`;
  document.querySelector('#exportLabel').textContent = `Download all ${n(data.total)} (CSV)`;
  const pages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
  document.querySelector('#range').textContent = data.total ? `Showing ${n(offset + 1)}–${n(Math.min(offset + PAGE_SIZE, data.total))} of ${n(data.total)}` : '';
  document.querySelector('#page').textContent = data.total ? `Page ${n(S.page)} of ${n(pages)}` : '';
  const prev = document.querySelector('#prev'), next = document.querySelector('#next');
  prev.disabled = S.page === 1; next.disabled = offset + PAGE_SIZE >= data.total;
  document.querySelector('#startHere').disabled = !data.total;
  prev.onclick = () => { S.page -= 1; saveFilters(); cases(); window.scrollTo(0, 0); };
  next.onclick = () => { S.page += 1; saveFilters(); cases(); window.scrollTo(0, 0); };
}

async function openPosition(pos) {
  const r = await api(url('/api/queue/position', listParams({ position: pos })));
  if (!r.case_id) { S.flash = { text: pos > 1 ? 'You have reached the end of this list.' : 'There are no cases in this list.', kind: 'ok' }; go('#/cases'); return; }
  go(`#/case/${encodeURIComponent(r.case_id)}?pos=${pos}`);
}

/* ------------------------------------------------------------ case page */

const DECISION_OPTIONS = [
  ['CONFIRMED_VALID', '✓', 'Confirmed valid', 'The unusual value is correct.'],
  ['CONFIRMED_ISSUE', '!', 'Issue confirmed', 'The record contains an error.'],
  ['INCONCLUSIVE_NEEDS_FOLLOW_UP', '?', 'Needs follow-up', 'More information is required.'],
];
const VAR_UNITS = { cws_earnings_salaried: 'rupees', cws_earnings_self_employed: 'rupees', day7_total_hours: 'hours', age: 'years' };
const VAR_SHORT = { cws_earnings_salaried: 'salaried earnings', cws_earnings_self_employed: 'self-employment earnings', day7_total_hours: 'hours worked on day 7' };
const CASE_SECTIONS = [['summary', 'Why this needs attention', 'spark'], ['evidence', 'What supports this finding', 'compare'], ['checks', 'What should you check?', 'check'], ['decision', 'What did you conclude?', 'reviewed'], ['fsu', 'About this FSU', 'people']];
const EV_ICON = { rules: 'rule', statistical: 'compare', historical: 'history', ml_combination: 'combo', ml_conditional: 'model', ml: 'combo', contextual: 'work' };

function fmt(value, unit) {
  const v = Number(value);
  if (value == null || value === '' || !Number.isFinite(v)) return 'not recorded';
  const whole = nf.format(Math.round(Math.abs(v)));
  const sign = v < 0 ? '−' : '';
  if (unit === 'rupees') return `₹${sign}${whole}`;
  if (unit === 'hours') return `${sign}${Math.abs(v) % 1 ? Math.abs(v) : whole} hour${Math.abs(v) === 1 ? '' : 's'}`;
  if (unit === 'years') return `${sign}${whole} years`;
  return `${sign}${Math.abs(v) % 1 ? Math.abs(v) : whole}`;
}

// One plain sentence about the lead value, from the stored 5% / 95% points of the comparison group.
function leadSentence(lead, unit) {
  const obs = Number(lead.observed_value), q05 = Number(lead.quantile_0_05), q95 = Number(lead.quantile_0_95);
  if (lead.distribution_position === 'UPPER_TAIL') return `This is ${q95 > 0 && obs >= 2 * q95 ? 'much higher' : 'higher'} than what similar people usually reported.`;
  if (lead.distribution_position === 'LOWER_TAIL') return `This is ${obs <= q05 / 2 ? 'much lower' : 'lower'} than what similar people usually reported.`;
  return `This is within the range that similar people usually reported (typical ${fmt(lead.peer_median, unit)}).`;
}
// Which other record-level checks point the same way (adds information; never restates the lead).
function alsoSentence(s, stat) {
  const parts = [];
  for (const r of s.reasons) {
    if (r.level !== 'record' || r.source === 'statistical' || r.source === 'rules') continue;
    if (r.source === 'historical') parts.push('compared with similar people in earlier periods');
    else if (r.source === 'contextual') parts.push('in its occupation code');
    else if (r.source === 'ml') parts.push(r.text.includes('model estimate') ? 'against the model estimate for similar profiles' : 'in the overall combination of answers');
  }
  const unique = [...new Set(parts)];
  if (unique.length) return `It also stands out ${unique.length === 1 ? unique[0] : `${unique.slice(0, -1).join(', ')} and ${unique.at(-1)}`}.`;
  return stat ? 'No other check singles this record out strongly.' : '';
}

// Where the reported value sits, drawn only from the stored 5/25/50/75/95% points.
function rangeViz(lead, unit, historical = false) {
  const q = ['quantile_0_05', 'quantile_0_25', historical ? 'reference_median' : 'peer_median', 'quantile_0_75', 'quantile_0_95'].map(k => Number(lead[k]));
  const obs = Number(lead.observed_value);
  if (![...q, obs].every(Number.isFinite)) return '';
  const [q05, q25, med, q75, q95] = q;
  const { place, breakAt, obsAt } = scaleFor(q05, q95, obs);
  const x05 = place(q05), x25 = place(q25), x50 = place(med), x75 = place(q75), x95 = place(q95);
  const size = Number(historical ? lead.reference_size : lead.peer_group_size) || 0;
  const ticks = [[x05, 'Low end', q05], [x95, 'High end', q95]];
  if (Math.abs(x50 - x05) > 14 && Math.abs(x95 - x50) > 14) ticks.push([x50, 'Typical', med]);
  return `<div class="range" role="img" aria-label="Reported ${esc(fmt(obs, unit))} compared with ${n(size)} ${historical ? 'earlier' : 'similar'} records: typical ${esc(fmt(med, unit))}, 9 in 10 between ${esc(fmt(q05, unit))} and ${esc(fmt(q95, unit))}.">
    <div class="track">
      <div class="axis"></div>
      <div class="outer" style="left:${x05}%;width:${Math.max(x95 - x05, .6)}%" title="9 in 10 ${historical ? 'earlier' : 'similar'} records: ${esc(fmt(q05, unit))} – ${esc(fmt(q95, unit))}"></div>
      <div class="inner" style="left:${x25}%;width:${Math.max(x75 - x25, .6)}%" title="Middle half: ${esc(fmt(q25, unit))} – ${esc(fmt(q75, unit))}"></div>
      <div class="med" style="left:${x50}%" title="Typical: ${esc(fmt(med, unit))}"></div>
      ${breakAt ? `<div class="brk" style="left:${breakAt}%" title="Scale shortened here"></div>` : ''}
      <div class="obs ${historical ? 'hist' : ''} ${obsAt > 72 ? 'r' : obsAt < 28 ? 'l' : ''}" style="left:${obsAt}%"><span class="lab">This record ${esc(fmt(obs, unit))}</span><span class="stem"></span><span class="pt"></span></div>
    </div>
    <div class="ticks">${ticks.map(([x, l, v]) => `<span style="left:${x}%">${l}<b>${esc(fmt(v, unit))}</b></span>`).join('')}</div>
    <div class="legend"><span><i class="lg-inner"></i>Middle half of ${historical ? 'earlier' : 'similar'} records</span><span><i class="lg-outer"></i>9 in 10 records</span><span><i class="lg-med"></i>Typical</span><span><i class="lg-obs"></i>This record</span>${breakAt ? '<span>Scale shortened at the break</span>' : ''}</div>
  </div>`;
}

function numbers(items) { return items && items.length ? `<table class="numbers">${items.map(i => `<tr><td>${esc(i.label)}</td><td>${esc(i.value)}</td></tr>`).join('')}</table>` : ''; }
function kv(items) { return `<dl class="kv">${items.map(i => `<dt>${esc(i.label)}</dt><dd>${esc(i.value)}</dd>`).join('')}</dl>`; }
const techBlock = (data, label = 'Technical details') => (data ? `<details class="tech"><summary>${icon('technical')}${label}${icon('chev', 'tchev')}</summary><pre>${esc(JSON.stringify(data, null, 2))}</pre></details>` : '');
const foot = text => (text ? `<div class="ev-foot">${icon('info')}<span>${esc(text)}</span></div>` : '');
function parseCounts(text) {
  const m = /([\d,]+)\s+of\s+([\d,]+)/.exec(String(text || ''));
  if (!m) return null;
  const a = Number(m[1].replace(/,/g, '')), b = Number(m[2].replace(/,/g, ''));
  return b ? { part: a, whole: b } : null;
}

// Evidence rows: level 1 is the row (finding + one fact); level 2 the expansion; level 3 the nested technical details.
function evidenceRows(s) {
  const by = id => s.evidence.find(e => e.id === id);
  const missing = Object.fromEntries(s.unavailable.map(u => [u.source, u.text]));
  const rows = [];
  const na = (key, name, text) => rows.push({ key, name, na: true, fact: text });

  const rules = by('rules');
  if (rules) rows.push({ key: 'rules', name: 'Questionnaire rules', strength: rules.strength, fact: rules.observed, action: 'View rule',
    body: `<p class="lead-text">${esc(rules.comparison)}</p>${numbers(rules.facts)}${foot(rules.matters)}${techBlock(rules.technical)}` });

  const stat = by('statistical');
  if (stat) {
    const lead = stat.lead, unit = VAR_UNITS[lead.target_variable];
    rows.push({ key: 'statistical', name: 'Similar records', strength: stat.strength, action: 'View comparison',
      fact: `<b>${esc(fmt(lead.observed_value, unit))}</b> vs typical ${esc(fmt(lead.peer_median, unit))}`,
      body: `<p class="lead-text">${esc(stat.comparison)}</p>
        ${stat.comparison_group?.length ? `<div class="groupdims">${stat.comparison_group.map(g => `<span><b>${esc(g.label)}</b>${esc(g.value)}</span>`).join('')}</div>` : ''}
        ${stat.comparison_note ? `<p class="note">${esc(stat.comparison_note)}</p>` : ''}
        ${numbers(stat.facts)}
        ${stat.other_values?.length ? `<div class="sub">Other values checked for this person</div>${numbers(stat.other_values.map(o => ({ label: `${o.label}: ${o.observed} (typical ${o.typical}, ${n(o.comparable)} similar records)`, value: o.position })))}` : ''}
        ${techBlock(stat.technical)}` });
  } else na('statistical', 'Similar records', missing.statistical);

  const hist = by('historical');
  if (hist) {
    const lead = hist.lead, unit = VAR_UNITS[lead.target_variable];
    rows.push({ key: 'historical', name: 'Earlier periods', strength: hist.strength, action: 'View earlier periods',
      fact: `${esc(fmt(lead.observed_value, unit))} vs typical ${esc(fmt(lead.reference_median, unit))} in ${esc(lead.reference_periods || 'earlier periods')}`,
      body: `<p class="lead-text">${esc(hist.comparison)}</p>${rangeViz(lead, unit, true)}${numbers(hist.facts)}${foot(hist.matters)}${techBlock(hist.technical)}` });
  } else na('historical', 'Earlier periods', missing.historical);

  const comb = by('ml_combination'), cond = by('ml_conditional'), sim = by('ml_similarity');
  if (comb) rows.push({ key: 'ml_combination', name: 'Combination of answers', strength: comb.strength, action: 'View details', fact: esc(comb.meaning),
    body: `<p class="lead-text">${esc(comb.observed)} ${esc(comb.comparison)}</p>${numbers(comb.facts)}
      ${sim ? `<div class="sub">Identical answer sets in the same FSU</div><p class="lead-text">${esc(sim.meaning)} ${esc(sim.matters)}</p>` : ''}
      ${foot(comb.matters)}${techBlock({ combination: comb.technical, identical_answers: sim?.technical || null })}` });
  if (cond) rows.push({ key: 'ml_conditional', name: 'Model estimate', strength: cond.strength, action: 'View model estimate', fact: esc(cond.facts?.[0]?.value || cond.meaning),
    body: `<p class="lead-text">${esc(cond.comparison)}</p>${numbers(cond.facts)}${foot(cond.matters)}${techBlock(cond.technical)}` });
  if (!comb && !cond) na('ml', 'Combination of answers', missing.ml);

  const ctx = by('contextual');
  if (ctx) rows.push({ key: 'contextual', name: 'Occupation', strength: ctx.strength, action: 'View occupation check',
    fact: `Code ${esc(ctx.code)} · ${esc(String(ctx.facts?.[0]?.value || '').replace(' (', ' similar records ('))}`,
    body: `<p class="lead-text">${esc(ctx.comparison)}</p>
      <div class="freq">${ctx.facts.map(f => { const c = parseCounts(f.value); return `<div class="fl"><span>${esc(f.label)}</span><span class="bar"><i style="width:${c ? (c.part / c.whole) * 100 : 0}%"></i></span><span class="n">${esc(f.value)}</span></div>`; }).join('')}</div>
      ${foot(ctx.matters)}${techBlock(ctx.technical)}` });
  else na('contextual', 'Occupation', missing.contextual);
  return rows;
}

function evidenceHtml(rows) {
  return `<div class="ev">${rows.map((r, i) => r.na
    ? `<div class="ev-row na"><div class="ev-sum" style="cursor:default"><span class="ev-ico">${icon(EV_ICON[r.key] || 'info')}</span><span class="name">${esc(r.name)}</span><span class="strength">Not available</span><span class="fact">${esc(r.fact || 'Not available for this record.')} This is not evidence for or against the record.</span><span></span></div></div>`
    : `<div class="ev-row" data-ev="${r.key}">
        <button class="ev-sum" aria-expanded="false" aria-controls="ev-${i}"><span class="ev-ico">${icon(EV_ICON[r.key] || 'info')}</span><span class="name">${esc(r.name)}</span>${strengthBadge(r.strength)}<span class="fact">${r.fact}</span><span class="act"><span class="act-t">${esc(r.action)}</span>${icon('chev')}</span></button>
        <div class="ev-body" id="ev-${i}"><div><div class="ev-inner">${r.body}</div></div></div>
      </div>`).join('')}</div>`;
}

function importanceCard(imp, d, ov) {
  const rank = imp.position && imp.total ? `<div class="imp-rank"><span class="g">${n(imp.position)}</span><span class="gl">ranked of <br>${n(imp.total)} records</span></div>` : '';
  if (!imp.levels?.unusualness) {
    return `<div class="card imp"><h4>Place in the review list</h4>${rank}<p class="plain">${esc(imp.summary)}</p><p class="note">${esc(imp.limitation)}</p></div>`;
  }
  const meter = level => { const k = { Low: 1, Moderate: 2, High: 3, 'Very high': 4 }[level] || 0; return `<span class="m">${[1, 2, 3, 4].map(i => `<i class="${i <= k ? 'on' : ''}"></i>`).join('')}</span>`; };
  return `<div class="card imp">
    <h4>Why it's high on the review list</h4>
    ${rank}
    <p class="plain">${esc(imp.plain || imp.explanation)}</p>
    <div class="levels">
      <div class="lvl"><span>Unusualness</span><b>${esc(imp.levels.unusualness)}</b>${meter(imp.levels.unusualness)}</div>
      ${imp.levels.influence ? `<div class="lvl"><span>Potential influence</span><b>${esc(imp.levels.influence)}</b>${meter(imp.levels.influence)}</div>` : ''}
    </div>
    <p class="note">This is a review-prioritisation measure, not an estimate of the actual effect on official PLFS estimates.</p>
    <details class="disclose"><summary>How this was calculated${icon('chev')}</summary><div class="body">
      ${rankBar(imp.position, imp.total, ov)}
      ${numbers(imp.points)}
      <p class="note" style="margin-top:8px">${esc(imp.explanation)} ${esc(imp.limitation)}</p>
      ${techBlock({ priority_score: d.priority_score, priority_rank: d.priority_rank, risk_score: d.risk_score, influence_score: d.influence_score, raw_influence: d.raw_influence, influence_target: d.influence_target, override_applied: d.override_applied })}
    </div></details>
  </div>`;
}

function rankBar(position, total, ov) {
  if (!position || !total) return '';
  const bands = ov ? Object.fromEntries(ov.bands.map(b => [b.band, b.records])) : {};
  const ranked = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].filter(b => bands[b]);
  const sum = ranked.reduce((a, b) => a + bands[b], 0);
  const segs = sum === total ? ranked.map(b => `<span class="seg-${b}" style="flex:${bands[b]}" title="${esc(S.labels.bands[b])}: ${n(bands[b])}"></span>`).join('') : '';
  const at = Math.min(100, Math.max(0, ((position - .5) / total) * 100));
  return `<div class="rankbar" aria-label="Ranked ${n(position)} of ${n(total)}"><div class="track">${segs}<span class="marker" style="left:${at}%"></span></div>
    <div class="meta"><span>Top</span><span>Ranked ${n(position)} of ${n(total)}</span><span>End</span></div></div>`;
}

// Paired bars: this FSU versus comparable FSUs, from the stored pattern details only.
function pairBars(item) {
  const t = item.technical || {}, d = t.details || {};
  const unit = VAR_UNITS[item.variable] || '';
  let own, ref, ownLabel = 'This FSU', refLabel = 'Comparable FSUs', share = true;
  if (item.component === 'digit_heaping' && d.fsu_share_ending_0_or_5 != null) {
    own = d.fsu_share_ending_0_or_5; ref = d.reference_share_ending_0_or_5; ownLabel = 'This FSU — ending in 0 or 5';
  } else if (item.component === 'fsu_distribution_shift' && Array.isArray(d.categories) && d.categories.length) {
    const p = d.fsu_proportions || [], q = d.reference_proportions || [];
    if (p.length !== d.categories.length || q.length !== d.categories.length) return '';
    const i = d.categories.reduce((best, _, k) => (Math.abs(p[k] - q[k]) > Math.abs(p[best] - q[best]) ? k : best), 0);
    own = p[i]; ref = q[i];
  } else if (item.component === 'fsu_distribution_shift' && d.fsu_median != null) {
    own = d.fsu_median; ref = d.reference_median; share = false; ownLabel = 'This FSU (typical)'; refLabel = 'Comparable FSUs (typical)';
  } else if (item.component === 'reduced_variance_concentration' && d.fsu_share_close_to_own_median != null) {
    own = d.fsu_share_close_to_own_median; ref = d.expected_share; ownLabel = 'This FSU — close to its typical value';
  } else return '';
  if (!Number.isFinite(Number(own)) || !Number.isFinite(Number(ref))) return '';
  const top = share ? 1 : Math.max(Math.abs(own), Math.abs(ref), 1e-9);
  const width = v => Math.max(0, Math.min(100, (Math.abs(v) / top) * 100));
  const label = v => (share ? `${(v * 100).toFixed(0)}%` : fmt(v, unit));
  return `<div class="pair">
    <div class="pl fsu"><span>${esc(ownLabel)}</span><span class="bar"><i style="width:${width(own)}%"></i></span><span class="n">${esc(label(own))}</span></div>
    <div class="pl ref"><span>${esc(refLabel)}</span><span class="bar"><i style="width:${width(ref)}%"></i></span><span class="n">${esc(label(ref))}</span></div>
  </div>`;
}

const fsuItem = it => `<div class="item"><div class="t"><span>${esc(it.title)}</span>${strengthBadge(it.strength, true)}</div><p>${esc(it.text)}</p>${pairBars(it)}</div>`;

function fsuBlock(d, s) {
  const p = s.evidence.find(e => e.id === 'pattern');
  const missing = s.unavailable.find(u => u.source === 'pattern');
  const groupChecks = s.checks.filter(c => c.level === 'group');
  return `<section class="fsu-block" id="fsu">
    <div class="block-head"><div>${tag('Whole FSU — not this individual record', 'violet')}<h2>About this FSU</h2></div><span class="fsu-glyph" aria-hidden="true">${'<i></i>'.repeat(9)}</span></div>
    ${p ? `<p class="lead-text">${esc(p.observed)} ${esc(p.meaning)}</p>
      <div style="margin-top:12px">${strengthBadge(p.strength, true)}</div>
      ${p.notable ? p.items.map(fsuItem).join('') : `<details class="disclose v"><summary>Show the closest FSU check${icon('chev')}</summary><div class="body">${p.items.map(fsuItem).join('')}</div></details>`}
      ${groupChecks.length ? `<ul class="gchecks">${groupChecks.map(c => `<li>${esc(c.text)}</li>`).join('')}</ul>` : ''}
      <div class="ev-foot">${icon('info')}<span>${esc(p.matters)} An FSU is a sampling unit; it is not linked to any individual enumerator.</span></div>
      <div style="margin-top:16px"><a class="btn violet" href="#/group/${encodeURIComponent(d.fsu)}?state=${encodeURIComponent(d.state)}">Open FSU ${esc(d.fsu)} ${icon('right')}</a></div>
      ${techBlock(p.technical)}`
    : `<p class="lead-text">${esc(missing?.text || 'No FSU-level information is available for this record.')}</p>`}
  </section>`;
}

function historyHtml(events) {
  const decisions = events.filter(e => e.event_type === 'DECISION_MADE');
  const views = events.filter(e => e.event_type === 'CASE_VIEWED').length;
  return `<details class="acc" ${decisions.length ? 'open' : ''}><summary><span class="acc-ico">${icon('history')}</span><span class="acc-t">Audit trail</span><span class="acc-h">${decisions.length} ${plural(decisions.length, 'decision')} · opened ${views} ${plural(views, 'time')}</span>${icon('chev', 'acc-chev')}</summary>
    <div class="acc-body"><ul class="timeline">${decisions.length ? decisions.slice().reverse().map(e => `<li><time>${esc(when(e.event_timestamp_utc))}</time>${statusChip(e.decision)}<span>${esc(e.actor)}</span>${e.comment ? `<span class="muted">“${esc(e.comment)}”</span>` : ''}</li>`).join('') : '<li class="muted">No decision recorded yet.</li>'}</ul>
    <p class="note" style="margin-top:8px">Entries are only ever added. Earlier decisions are kept when a new one is recorded; the latest decision is the current status.</p></div></details>`;
}

async function casePage(caseId, params) {
  const pos = parseInt(params.get('pos') || '', 10) || null;
  const from = params.get('from');
  const [d, place, ov] = await Promise.all([
    api(url(`/api/cases/${encodeURIComponent(caseId)}`, { run: S.run })),
    pos ? api(url('/api/queue/position', listParams({ position: pos }))) : Promise.resolve(null),
    overviewData().catch(() => null),
  ]);
  fetch(url(`/api/cases/${encodeURIComponent(caseId)}/events`, { run: S.run }), { method: 'POST', headers: { 'Content-Type': 'application/json', ...(authToken() ? { Authorization: `Bearer ${authToken()}` } : {}) }, body: JSON.stringify({ event_type: 'CASE_VIEWED', actor: reviewer() || 'local-supervisor' }) }).catch(() => {});
  const s = d.story;
  crumbs(['Cases to review', s.record.title]);
  const total = place?.total;
  const back = from === 'reviewed' ? ['#/reviewed', 'Reviewed cases'] : from === 'group' ? [`#/group/${encodeURIComponent(d.fsu)}?state=${encodeURIComponent(d.state)}`, `FSU ${d.fsu}`] : ['#/cases', 'Back to list'];
  const lastDecision = [...d.audit_history].reverse().find(e => e.event_type === 'DECISION_MADE');
  const stat = s.evidence.find(e => e.id === 'statistical');
  const rules = s.evidence.find(e => e.id === 'rules');
  const lead = stat?.lead;
  const unit = lead ? VAR_UNITS[lead.target_variable] : '';
  const recordChecks = s.checks.filter(c => c.level !== 'group');
  const checkKey = `l:MoSPI.checks.${S.run}.${caseId}`;
  const noteKey = `l:MoSPI.note.${S.run}.${caseId}`;
  const ticked = new Set(store.get(checkKey, []));
  const rows = evidenceRows(s);
  const location = s.record.location.filter(l => ['State/UT', 'Sector'].includes(l.label)).map(l => l.value).join(' · ');

  const title = lead ? `<span class="sum-label">Reported ${esc(VAR_SHORT[lead.target_variable] || 'value')}</span><span class="val">${bigValue(fmt(lead.observed_value, unit))}</span>`
    : rules ? 'A documented questionnaire rule is not met' : 'Record in the review list';
  const why = rules ? 'The recorded answers do not satisfy a documented questionnaire rule.'
    : lead && lead.distribution_position !== 'CENTRAL_REFERENCE_RANGE' ? leadSentence(lead, unit)
    : s.reasons.find(r => r.level === 'record') ? `${capital(s.reasons.find(r => r.level === 'record').text)}.` : s.headline;
  const also = alsoSentence(s, stat);

  app.innerHTML = `
    <div class="case-nav">
      <a class="btn line" href="${back[0]}">${icon('left')} <span class="label">${esc(back[1])}</span></a>
      <span class="where">${pos && total ? `Case <b>${n(pos)}</b> of ${n(total)}${filterSummary()}` : 'Opened directly'}</span>
      <div class="btns"><button class="btn line sm only-narrow" id="navDecide">Decide</button>${pos ? `<button class="btn sq" id="prevCase" ${pos <= 1 ? 'disabled' : ''} title="Previous case (P)" aria-label="Previous case">${icon('left')}</button><button class="btn sq dark" id="nextCase" ${total && pos >= total ? 'disabled' : ''} title="Next case (N)" aria-label="Next case">${icon('right')}</button>` : ''}</div>
    </div>

    <div class="case-layout">
      <div class="case-main">
        <section class="panel summary rv b-${esc(d.priority_band)}" id="summary">
          <div class="top">${bandChip(d.priority_band, s.importance.band_label)}${statusChip(d.review_status)}</div>
          <div class="sum-grid">
            <div class="sum-value">
              <h1 class="${lead ? '' : 'plain-title'}">${title}</h1>
              <p class="rec">${icon('pin')}${esc(s.record.title)} · ${esc(location)}</p>
            </div>
            ${lead ? `<div class="sum-figs">
              <div class="fig"><span class="l">Typical</span><span class="v">${bigValue(fmt(lead.peer_median, unit))}</span></div>
              <div class="fig"><span class="l">Usual range (9 in 10)</span><span class="v sm">${esc(fmt(lead.quantile_0_05, unit))}–${esc(fmt(lead.quantile_0_95, unit))}</span></div>
            </div>` : ''}
          </div>
          ${!s.details_available ? '<div class="notice error">Detailed source evidence for this survey round was not found on this computer, so only summary statements can be shown.</div>' : ''}
          <div class="why-box"><span class="k">Why it needs attention</span><div><p>${esc(why)}</p>${also ? `<p class="also">${esc(also)}</p>` : ''}</div></div>
          ${lead ? `<div class="compare">
            <div class="head"><b>Similar people</b><button class="link" id="whoSimilar">${n(lead.peer_group_size)} similar records · who are they? ${icon('chev')}</button></div>
            ${rangeViz(lead, unit)}
          </div>` : ''}
          <p class="caveat-line">${icon('balance')}Unusual does not mean incorrect. Only your review can decide that.</p>
        </section>

        <section class="panel block rv" id="evidence">
          <div class="block-head"><div>${tag('Step 1')}<h2>What supports this finding</h2></div><span class="aside">Select a check to see the comparison behind it</span></div>
          ${evidenceHtml(rows)}
          <div class="ev-foot">${icon('info')}<span>These checks share some of the same answers (earnings feed several of them), so read them as complementary views, not independent confirmations.</span></div>
        </section>

        <section class="panel block rv" id="checks">
          <div class="block-head"><div>${tag('Step 2')}<h2>What should you check?</h2></div>${recordChecks.length ? '<span class="check-progress" id="checkProgress"></span>' : ''}</div>
          ${recordChecks.length ? `<ul class="checks">${recordChecks.map((c, i) => `<li class="${ticked.has(i) ? 'checked' : ''}" data-check="${i}" role="checkbox" aria-checked="${ticked.has(i)}" tabindex="0">
              <span class="box">${icon('check')}</span><div><div class="k">Check ${i + 1}</div><div class="t">${esc(c.text)}</div>${c.detail ? `<div class="d">${esc(c.detail)}</div>` : ''}</div></li>`).join('')}</ul>
            <p class="note" style="margin-top:12px">These checks follow from the evidence above. Ticks are a personal aid kept on this computer; write what you found in the note below.</p>`
            : '<p class="muted">No specific check follows from the available evidence. Review the record as a whole against the schedule.</p>'}
        </section>

        <section class="panel block decide rv" id="decision">
          <div class="block-head"><div>${tag('Step 3')}<h2>What did you conclude?</h2></div><span class="aside">Keys <kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd></span></div>
          ${lastDecision ? `<div class="last-decision">Current decision: ${statusChip(lastDecision.decision)} by <b>${esc(lastDecision.actor)}</b> on ${esc(when(lastDecision.event_timestamp_utc))}${lastDecision.comment ? ` — “${esc(lastDecision.comment)}”` : ''}. A new decision is added on top; the earlier one is kept.</div>` : ''}
          <div class="choices" role="radiogroup" aria-label="Decision">
            ${DECISION_OPTIONS.map(([v, ic, l, h], i) => `<label class="choice ${v}"><input type="radio" name="decision" value="${v}"><span class="ic" aria-hidden="true">${ic}</span><strong>${l}</strong><span>${h}</span><kbd>${i + 1}</kbd></label>`).join('')}
          </div>
          <label for="comment" class="field-label">What you checked and what you found (optional)</label>
          <textarea id="comment" placeholder="For example: confirmed against the schedule; the amount was entered with an extra zero.">${esc(store.get(noteKey, ''))}</textarea>
          <div class="decision-actions">
            ${pos ? `<button class="btn dark lg" id="saveNext">Save and go to next case ${icon('right')}</button><button class="btn line lg" id="save">Save only</button>`
              : '<button class="btn dark lg" id="save">Save decision</button>'}
            <span class="small muted" id="who">${reviewer() ? `Saving as ${esc(reviewer())}` : 'Add your name at the top right so the audit trail shows who decided.'}</span>
          </div>
          <div id="savedBox"></div>
          <div class="after">${icon('info')}<span><b>What happens next:</b> your decision, your name and a snapshot of this evidence are added to the audit trail. The survey data are not changed, and earlier decisions on this case are kept.${pos ? ' You then move to the next case in this list.' : ''}</span></div>
        </section>

        ${fsuBlock(d, s)}

        <section class="panel block rv more-block">
          <details class="acc"><summary><span class="acc-ico">${icon('pin')}</span><span class="acc-t">Record details</span><span class="acc-h">location, survey and identifiers</span>${icon('chev', 'acc-chev')}</summary>
            <div class="acc-body kv-grid">
              <div>${kv(s.record.location)}</div><div>${kv(s.record.survey)}</div>
              <div>${kv([{ label: 'Record key', value: s.record.record_key }, { label: 'Case reference', value: d.case_id }])}</div>
            </div></details>
          <div id="historyBox">${historyHtml(d.audit_history)}</div>
          <details class="acc"><summary><span class="acc-ico">${icon('technical')}</span><span class="acc-t">Technical details for this case</span><span class="acc-h">scores, ranks, provenance</span>${icon('chev', 'acc-chev')}</summary><div class="acc-body">
            <pre class="code">${esc(JSON.stringify({
              priority: { priority_score: d.priority_score, priority_rank: d.priority_rank, priority_band: d.priority_band, risk_score: d.risk_score, influence_score: d.influence_score, raw_influence: d.raw_influence, override_applied: d.override_applied, available_evidence_count: d.available_evidence_count },
              source_ranks: { statistical: d.statistical_rank, contextual: d.contextual_rank, ml: d.ml_rank, historical: d.historical_rank, pattern: d.pattern_rank },
              source_status: { statistical: d.statistical_status, contextual: d.contextual_status, ml: d.ml_status, pattern: d.pattern_status },
              design_weight: d.design_weight, provenance: d.provenance, source_run_directories: s.source_runs, stored_evidence_card: d.evidence_card,
            }, null, 2))}</pre></div></details>
        </section>
      </div>

      <aside class="rail" aria-label="Case context">
        <div class="card steps-card"><h4>On this page</h4>
          <ol class="steps">${CASE_SECTIONS.map(([id, t, ic]) => `<li><a href="#" data-step="${id}" class="${id === 'decision' && lastDecision ? 'done' : ''}">${icon(ic)}<span>${esc(t)}</span></a></li>`).join('')}</ol>
          <button class="btn dark" id="toDecision">Go to decision ${icon('right')}</button>
          <p class="hint"><kbd>N</kbd> next · <kbd>P</kbd> previous · <kbd>D</kbd> decision · <kbd>1</kbd>–<kbd>3</kbd> choose</p>
        </div>
        ${importanceCard(s.importance, d, ov)}
        <div class="card"><h4>This person</h4>${s.record.person.length ? kv(s.record.person) : '<p class="muted small">Person details are not available on this computer.</p>'}</div>
      </aside>
    </div>`;

  // evidence rows: one open at a time keeps the page calm
  const toggleRow = (row, open = !row.classList.contains('open')) => {
    if (open) app.querySelectorAll('.ev-row.open').forEach(o => { if (o !== row) { o.classList.remove('open'); o.querySelector('.ev-sum').setAttribute('aria-expanded', 'false'); } });
    row.classList.toggle('open', open);
    row.querySelector('.ev-sum').setAttribute('aria-expanded', String(open));
  };
  app.querySelectorAll('.ev-row[data-ev] .ev-sum').forEach(b => b.onclick = () => toggleRow(b.closest('.ev-row')));
  document.querySelector('#whoSimilar')?.addEventListener('click', () => {
    const row = app.querySelector('.ev-row[data-ev="statistical"]');
    if (row) { toggleRow(row, true); row.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
  });

  // checklist (a personal aid kept on this computer only)
  const updateChecks = () => { const el = document.querySelector('#checkProgress'); if (el) el.innerHTML = `<b>${ticked.size}</b> of ${recordChecks.length} checked`; };
  app.querySelectorAll('[data-check]').forEach(li => {
    const flip = () => { const i = Number(li.dataset.check); const on = !ticked.has(i); if (on) ticked.add(i); else ticked.delete(i); li.classList.toggle('checked', on); li.setAttribute('aria-checked', String(on)); store.set(checkKey, [...ticked]); updateChecks(); };
    li.onclick = flip;
    li.onkeydown = e => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); flip(); } };
  });
  updateChecks();

  // section navigator with scroll position
  const scrollTo = id => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  app.querySelectorAll('[data-step]').forEach(a => a.onclick = e => { e.preventDefault(); scrollTo(a.dataset.step); });
  document.querySelector('#toDecision').onclick = () => scrollTo('decision');
  document.querySelector('#navDecide').onclick = () => scrollTo('decision');
  const links = [...app.querySelectorAll('[data-step]')];
  if ('IntersectionObserver' in window) {
    S.spy = new IntersectionObserver(entries => {
      const visible = entries.filter(x => x.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (visible) links.forEach(a => a.classList.toggle('current', a.dataset.step === visible.target.id));
    }, { rootMargin: '-140px 0px -55% 0px' });
    CASE_SECTIONS.forEach(([id]) => { const el = document.getElementById(id); if (el) S.spy.observe(el); });
  }

  // decision
  const choices = app.querySelectorAll('.choice');
  const choose = value => choices.forEach(x => { const input = x.querySelector('input'); if (value) input.checked = input.value === value; x.classList.toggle('selected', input.checked); });
  choices.forEach(o => o.querySelector('input').onchange = () => choose());
  const comment = document.querySelector('#comment');
  comment.oninput = () => store.set(noteKey, comment.value);
  const save = async goNext => {
    const choice = app.querySelector('input[name=decision]:checked');
    if (!choice) { notice('Choose a decision first: confirmed valid, issue confirmed, or needs follow-up.', 'error'); scrollTo('decision'); return; }
    const event = await api(url(`/api/cases/${encodeURIComponent(caseId)}/events`, { run: S.run }), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_type: 'DECISION_MADE', decision: choice.value, comment: comment.value.trim() || null, actor: reviewer() || 'local-supervisor' }),
    });
    store.set(noteKey, '');
    S.ov = null; // review counts changed
    const label = STATUS_TEXT[event.decision];
    if (goNext && pos) {
      S.flash = { text: `Saved “${label}” for ${s.record.title}. This is the next case.`, kind: 'ok' };
      return openPosition(nextPositionAfterDecision(pos));
    }
    notice('');
    const fresh = await api(url(`/api/cases/${encodeURIComponent(caseId)}`, { run: S.run, story: false }));
    document.querySelector('#savedBox').innerHTML = `<div class="saved"><span>${icon('check')} Saved to the audit trail: <b>${esc(label)}</b> by ${esc(event.actor)} at ${esc(when(event.event_timestamp_utc))}.</span>${pos ? `<button class="btn dark" id="afterNext">Go to next case ${icon('right')}</button>` : ''}</div>`;
    document.querySelector('#historyBox').innerHTML = historyHtml(fresh.audit_history);
    app.querySelector('#summary .top').innerHTML = `${bandChip(d.priority_band, s.importance.band_label)}${statusChip(event.decision)}`;
    links.find(a => a.dataset.step === 'decision')?.classList.add('done');
    document.querySelector('#afterNext')?.addEventListener('click', () => openPosition(nextPositionAfterDecision(pos)));
  };
  document.querySelector('#save').onclick = () => save(false).catch(e => notice(e.message, 'error'));
  document.querySelector('#saveNext')?.addEventListener('click', () => save(true).catch(e => notice(e.message, 'error')));
  if (pos) {
    document.querySelector('#prevCase').onclick = () => openPosition(pos - 1);
    document.querySelector('#nextCase').onclick = () => openPosition(pos + 1);
  }
  S.keys = e => {
    if (e.ctrlKey || e.metaKey || e.altKey || /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
    const key = e.key.toLowerCase();
    if (key === 'n' && pos && !(total && pos >= total)) openPosition(pos + 1);
    else if (key === 'p' && pos && pos > 1) openPosition(pos - 1);
    else if (key === 'd') scrollTo('decision');
    else if (['1', '2', '3'].includes(key)) { choose(DECISION_OPTIONS[Number(key) - 1][0]); scrollTo('decision'); }
  };
  document.addEventListener('keydown', S.keys);
}

// When the list hides reviewed cases, the decided case leaves the list and the
// next case moves up into the same position.
function nextPositionAfterDecision(pos) { return S.filters.review_status === 'UNREVIEWED' ? pos : pos + 1; }

function filterSummary() {
  const f = S.filters, parts = [];
  if (f.priority_band) parts.push(S.labels.bands[f.priority_band]);
  if (f.review_status) parts.push(REVIEW_CHIPS.find(c => c[0] === f.review_status)?.[1]);
  if (f.strong_source) parts.push(STRONG_SOURCES.find(c => c[0] === f.strong_source)?.[1]);
  if (f.state) parts.push(S.labels.states[f.state] || `State ${f.state}`);
  if (f.sector) parts.push(S.labels.sectors[f.sector]);
  if (f.fsu) parts.push(`FSU ${f.fsu}`);
  if (f.q) parts.push(`“${f.q}”`);
  return parts.length ? ` <span class="muted">· ${esc(parts.join(' · '))}</span>` : '';
}

/* ------------------------------------------------------------ group alerts (whole FSUs) */

const GROUP_CHIPS = [['ALERTS', 'All alerts'], ['HIGH', 'Clear difference'], ['MEDIUM', 'Some difference'], ['LOW', 'No notable difference'], ['NOT_ASSESSABLE', 'Not assessed'], ['', 'All FSUs']];

function patternItemHtml(p) {
  return `<div class="pattern-item"><div class="t"><span>${esc(p.title)}</span>${strengthBadge(p.strength, true)}</div><p>${esc(p.text)}</p>${pairBars(p)}<p class="note">${esc(p.basis)}</p>${techBlock(p.technical, 'How this was calculated')}</div>`;
}
// Visual vocabulary for the two scopes: a cluster for a whole FSU, a single point for one record.
const fsuGlyph = (cls = '') => `<span class="fsu-glyph ${cls}" aria-hidden="true">${'<i></i>'.repeat(9)}</span>`;

async function groups(_, params) {
  crumbs(['Group alerts']);
  const page = parseInt(params.get('page') || '1', 10);
  const band = params.get('band') ?? 'ALERTS';
  const state = params.get('state') || '';
  const [data, o] = await Promise.all([api(url('/api/groups', { run: S.run, offset: (page - 1) * GROUP_PAGE, limit: GROUP_PAGE, band, state })), overviewData().catch(() => null)]);
  const counts = o ? Object.fromEntries(o.groups.map(g => [g.band, g.groups])) : {};
  const alerts = (counts.HIGH || 0) + (counts.MEDIUM || 0);
  const link = (p, b = band, st = state) => `#/groups?${new URLSearchParams(Object.entries({ page: p > 1 ? p : '', band: b, state: st }).filter(([k, v]) => v || k === 'band')).toString()}`;
  const states = Object.entries(S.labels.states).map(([c, l]) => `<option value="${c}" ${state === c ? 'selected' : ''}>${esc(l)}</option>`).join('');
  app.innerHTML = `
    <section class="panel g-hero rv">
      <div class="gh-main">
        ${tag('Group alerts', 'violet')}
        <h1 class="display">Which FSUs look unusual as a whole?</h1>
        <p class="lede">FSUs whose overall pattern of answers differs from comparable FSUs in the same State, sector and stratum — for example in how ages are reported, or in the mix of activity statuses.</p>
        <div class="qh-count inline"><span class="g">${count(alerts)}</span><span class="gl">FSUs with a group <br>difference</span></div>
      </div>
      <div class="scope-compare" role="note" aria-label="A group alert describes a whole FSU, not an individual record">
        <div class="scope on"><span class="tile violet">${fsuGlyph('big')}</span><b>Whole FSU</b><span>What a group alert describes: the FSU's answers taken together.</span></div>
        <span class="ne" aria-hidden="true">≠</span>
        <div class="scope"><span class="tile"><span class="one"></span></span><b>Individual record</b><span>Not judged by a group alert. Each record has its own evidence on its case page.</span></div>
      </div>
    </section>
    <div class="group-intro">${icon('people')}<div><b>Whole FSU — not individual records.</b> An alert describes the FSU as a whole. It does not mean that any particular person's record is wrong, and an FSU is a sampling unit, not an enumerator. A difference can reflect a genuinely different place as much as how interviews were recorded.</div></div>
    <div class="bar-controls rv">
      <div class="ptabs" role="group" aria-label="Group difference">${GROUP_CHIPS.map(([v, l]) => `<a class="${band === v ? 'on' : ''} ${v === 'HIGH' || v === 'MEDIUM' || v === 'ALERTS' ? 'pv' : ''}" href="${link(1, v)}">${v === 'HIGH' || v === 'MEDIUM' ? '<i></i>' : ''}<span>${esc(l)}</span>${v === 'ALERTS' ? `<small>${n(alerts)}</small>` : v && counts[v] != null ? `<small>${n(counts[v])}</small>` : ''}</a>`).join('')}</div>
      <label class="fld inline"><span>State/UT</span><select id="gState"><option value="">All States/UTs</option>${states}</select></label>
    </div>
    <div class="list-meta"><span><b>${n(data.total)}</b> ${plural(data.total, 'FSU')}, strongest difference first</span></div>
    ${data.rows.length ? `<div class="group-grid">${data.rows.map((g, i) => `
      <a class="group-card rise" style="--i:${Math.min(i, 8)}" href="#/group/${encodeURIComponent(g.fsu)}?state=${encodeURIComponent(g.state)}">
        <div class="top">${fsuGlyph()}${groupChip(g.group_priority_band, g.band_label)}</div>
        <span class="scope-tag">Whole FSU</span>
        <h3>FSU ${esc(g.fsu)}</h3><div class="loc">${esc(g.location_label)}</div>
        ${g.patterns.length ? `<p class="finding">${esc(g.patterns[0].text)}</p>${g.patterns.length > 1 ? `<span class="more">+ ${g.patterns.length - 1} more ${plural(g.patterns.length - 1, 'difference')}</span>` : ''}` : '<span class="more">No pattern details found.</span>'}
        <div class="foot"><span>${n(g.records)} people interviewed</span><span class="go">Open FSU ${icon('right')}</span></div>
      </a>`).join('')}</div>`
      : `<div class="panel">${emptyState('No FSUs match', 'No FSU-level pattern information is available for this survey round, or none matches these filters.')}</div>`}
    <div class="pager"><span>${data.total ? `Showing ${n(data.offset + 1)}–${n(Math.min(data.offset + GROUP_PAGE, data.total))} of ${n(data.total)}` : ''}</span>
      <div class="btns"><a class="btn line" ${page > 1 ? `href="${link(page - 1)}"` : 'aria-disabled="true"'}>${icon('left')} Previous</a>
      <a class="btn line" ${data.offset + GROUP_PAGE < data.total ? `href="${link(page + 1)}"` : 'aria-disabled="true"'}>Next ${icon('right')}</a></div></div>
    <details class="acc panel-acc"><summary><span class="acc-ico">${icon('technical')}</span><span class="acc-t">How FSUs are compared</span><span class="acc-h">method</span>${icon('chev', 'acc-chev')}</summary><div class="acc-body"><p class="note">Each check compares an FSU with the other FSUs of the same State, sector and stratum (the FSU itself excluded). FSUs are ordered by their strongest check after allowing for the many FSUs compared (Benjamini–Hochberg q-value): a clear difference has q &lt; 0.01, some difference q &lt; 0.05. Group alerts never change an individual record's place in the review list.</p></div></details>`;
  document.querySelector('#gState').onchange = e => go(link(1, band, e.target.value));
}

async function groupPage(fsu, params) {
  const state = params.get('state') || '';
  const [d, members] = await Promise.all([
    api(url(`/api/groups/${encodeURIComponent(fsu)}`, { run: S.run, state })),
    api(url('/api/cases', { run: S.run, fsu, state, limit: 50, summaries: true })),
  ]);
  const g = d.group;
  crumbs(['Group alerts', `FSU ${g.fsu}`]);
  const notable = d.patterns.filter(p => p.notable);
  const rest = d.patterns.filter(p => !p.notable);
  app.innerHTML = `
    <div class="case-nav"><a class="btn line" href="#/groups">${icon('left')} <span class="label">Group alerts</span></a><span class="where"></span><span></span></div>
    <section class="panel group-hero rv">
      <div class="gh-main">
        ${tag('Group alert · whole FSU', 'violet')}
        <div class="gh-title"><h1 class="display">FSU ${esc(g.fsu)}</h1>${groupChip(g.group_priority_band, g.band_label)}</div>
        <p class="meta">${icon('pin')}${esc(g.location_label)} · ${n(g.records)} people interviewed</p>
        <p class="scope-note">${icon('info')}<span>This describes the FSU as a whole. It does not by itself establish an error in any individual record. An FSU is a sampling unit; it is not linked to any individual enumerator.</span></p>
      </div>
      <div class="gh-glyph"><span class="tile violet">${fsuGlyph('big')}</span><span>Whole FSU</span></div>
    </section>
    <section class="panel block rv">
      <div class="block-head"><div>${tag('Evidence about the group', 'violet')}<h2>What differs in this FSU</h2></div><span class="aside">Compared with other FSUs in the same State, sector and stratum</span></div>
      ${notable.length ? notable.map(patternItemHtml).join('') : '<p class="muted">None of the FSU-level checks show a notable difference.</p>'}
      ${rest.length ? `<details class="acc"><summary><span class="acc-ico">${icon('layers')}</span><span class="acc-t">Other FSU-level checks</span><span class="acc-h">${rest.length} not notably different</span>${icon('chev', 'acc-chev')}</summary><div class="acc-body">${rest.map(patternItemHtml).join('')}</div></details>` : ''}
    </section>
    <section class="panel block rv">
      <div class="block-head"><div>${tag('Individual records')}<h2>Records from this FSU in the review list</h2></div>${members.total ? `<button class="btn dark" id="reviewFsu">Review these one after another ${icon('right')}</button>` : ''}</div>
      <p class="note" style="margin-bottom:16px">${n(members.total)} ${plural(members.total, 'record')}, in priority order. Each record's own evidence is on its case page; the FSU alert does not change their order.</p>
      ${caseRows(members.rows, { positions: false, from: 'group' })}
    </section>`;
  document.querySelector('#reviewFsu')?.addEventListener('click', () => { S.filters = { fsu: g.fsu, state: g.state }; S.page = 1; saveFilters(); openPosition(1); });
}

/* ------------------------------------------------------------ reviewed */

async function reviewed(_, params) {
  crumbs(['Reviewed cases']);
  const decision = params.get('decision') || '';
  const [data, all] = await Promise.all([api(url('/api/reviews', { run: S.run, decision })), decision ? api(url('/api/reviews', { run: S.run })) : null]);
  const every = (all || data).rows;
  const tally = k => every.filter(r => r.decision === k).length;
  const chips = [['', 'All decisions'], ['CONFIRMED_VALID', 'Confirmed valid'], ['CONFIRMED_ISSUE', 'Issue confirmed'], ['INCONCLUSIVE_NEEDS_FOLLOW_UP', 'Needs follow-up']];
  app.innerHTML = `
    <section class="panel q-hero rv">
      <div class="qh-main">
        ${tag('Audit trail')}
        <h1 class="display">Reviewed cases</h1>
        <p class="lede">What has already been decided: the latest decision for each case, newest first. Earlier decisions remain in each case's audit trail.</p>
        <div class="pstats wide">
          <a class="pstat ${decision === 'CONFIRMED_VALID' ? 'on' : ''}" href="#/reviewed?decision=CONFIRMED_VALID"><i class="green"></i><b>${n(tally('CONFIRMED_VALID'))}</b><span>Confirmed valid</span></a>
          <a class="pstat ${decision === 'CONFIRMED_ISSUE' ? 'on' : ''}" href="#/reviewed?decision=CONFIRMED_ISSUE"><i class="red"></i><b>${n(tally('CONFIRMED_ISSUE'))}</b><span>Issues confirmed</span></a>
          <a class="pstat ${decision === 'INCONCLUSIVE_NEEDS_FOLLOW_UP' ? 'on' : ''}" href="#/reviewed?decision=INCONCLUSIVE_NEEDS_FOLLOW_UP"><i class="amber"></i><b>${n(tally('INCONCLUSIVE_NEEDS_FOLLOW_UP'))}</b><span>Needs follow-up</span></a>
        </div>
      </div>
      <div class="qh-count"><span class="g">${count(every.length)}</span><span class="gl">${plural(every.length, 'case')} with <br>a decision</span></div>
      <div class="q-filters"><div class="dtabs">${chips.map(([v, l]) => `<a class="${decision === v ? 'on' : ''}" href="#/reviewed${v ? `?decision=${v}` : ''}">${esc(l)}</a>`).join('')}</div></div>
    </section>
    <div class="list-meta"><span><b>${n(data.total)}</b> reviewed ${plural(data.total, 'case')}</span></div>
    ${data.rows.length ? `<div class="rev-list">${data.rows.map((r, i) => `<a class="rev-card rise" style="--i:${Math.min(i, 8)}" href="#/case/${encodeURIComponent(r.case_id)}?from=reviewed">
        <div class="rv-a">${statusChip(r.decision)}<b>${esc(r.record_label)}</b><span class="muted">${esc(r.location_label)}</span></div>
        <div class="rv-b">${r.comment ? `<p>“${esc(r.comment)}”</p>` : '<p class="muted">No review note</p>'}${r.decision_count > 1 ? `<span class="muted small">${r.decision_count} decisions recorded</span>` : ''}</div>
        <div class="rv-c"><span class="av">${esc(initials(r.actor))}</span><span><b>${esc(r.actor)}</b><small>${esc(when(r.decided_at_utc))}</small></span></div>
        <div class="rv-d">${bandChip(r.band, r.band_label)}<span class="go">${icon('right')}</span></div>
      </a>`).join('')}</div>`
      : `<div class="panel">${emptyState(`No decisions have been recorded${decision ? ' with this outcome' : ''} for this survey round yet.`, 'Decisions appear here as soon as they are saved on a case page.', '<a class="btn dark" href="#/cases">Go to cases to review</a>')}</div>`}`;
}

/* ------------------------------------------------------------ area trends */

const INDICATOR_UNITS = { lfpr_cws_15plus: 'share', wpr_cws_15plus: 'share', ur_cws_15plus: 'share', median_salaried_earnings: 'rupees', mean_day7_hours_workers: 'hours' };
const INDICATOR_BASE = { median_salaried_earnings: ['salaried_earners', 'salaried earners'], mean_day7_hours_workers: ['workers', 'workers'] };
function indicatorValue(indicator, v) { const u = INDICATOR_UNITS[indicator]; if (v == null) return '—'; return u === 'share' ? `${(v * 100).toFixed(1)}%` : u === 'rupees' ? `₹${nf.format(Math.round(v))}` : `${Number(v).toFixed(1)} hours`; }
const shortIndicator = label => String(label || '').replace(/ \(₹\)$/, '');
function baseText(r) {
  const [field, words] = INDICATOR_BASE[r.indicator] || ['persons_15plus', 'persons aged 15+'];
  return r[field] != null ? `Based on ${n(r[field])} ${words} in this area and period` : '';
}
// Direction glyph for a change (up or down only; the values are always written beside it).
const slopeGlyph = change => `<svg viewBox="0 0 28 20" aria-hidden="true"><path d="${change > 0 ? 'M4 15 L24 5' : 'M4 5 L24 15'}" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/><circle cx="4" cy="${change > 0 ? 15 : 5}" r="2.6" fill="#fff" stroke="currentColor" stroke-width="1.6"/><circle cx="24" cy="${change > 0 ? 5 : 15}" r="3" fill="currentColor"/></svg>`;

function trendChart(points, indicator) {
  // x = every period of the design period, so a period without a value stays visible as a gap.
  const valid = points.filter(p => Number.isFinite(p.value));
  if (valid.length < 2) return '<p class="muted small" style="margin-top:16px">Not enough periods with a value to draw a trend for this area.</p>';
  const w = 760, h = 300, pad = { l: 64, r: 28, t: 44, b: 40 };
  const x = i => pad.l + (i * (w - pad.l - pad.r)) / Math.max(points.length - 1, 1);
  const lo = Math.min(...valid.map(p => p.value)), hi = Math.max(...valid.map(p => p.value));
  const span = hi - lo || Math.abs(hi) || 1;
  // rounded axis ticks (1, 2, 2.5 or 5 × a power of ten) that enclose the stored values
  const raw = (span * 1.4) / 3, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map(k => k * mag).find(k => k >= raw);
  const y0 = Math.floor((lo - span * .2) / step) * step, y1 = Math.ceil((hi + span * .2) / step) * step;
  const y = v => pad.t + (1 - (v - y0) / (y1 - y0)) * (h - pad.t - pad.b);
  const grid = Array.from({ length: Math.round((y1 - y0) / step) + 1 }, (_, i) => y0 + i * step);
  const runs = []; let cur = [];
  points.forEach((p, i) => { if (Number.isFinite(p.value)) cur.push([x(i), y(p.value)]); else { if (cur.length) runs.push(cur); cur = []; } });
  if (cur.length) runs.push(cur);
  const missing = points.map((p, i) => [p, i]).filter(([p]) => !Number.isFinite(p.value));
  const unit = INDICATOR_UNITS[indicator];
  const changeLabel = r => (r.change == null ? '' : (r.change > 0 ? '+' : '−') + (unit === 'share' ? `${Math.abs(r.change * 100).toFixed(1)} pts` : indicatorValue(indicator, Math.abs(r.change))));
  return `<div class="trend-wrap"><svg viewBox="0 0 ${w} ${h}" class="trend" role="img" aria-label="Indicator value by period">
    <defs><linearGradient id="trendFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#0c0c0c" stop-opacity=".09"/><stop offset="1" stop-color="#0c0c0c" stop-opacity="0"/></linearGradient></defs>
    <g class="grid">${grid.map(v => `<line x1="${pad.l}" x2="${w - pad.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${pad.l - 12}" y="${y(v) + 4}" text-anchor="end">${esc(indicatorValue(indicator, v))}</text>`).join('')}</g>
    ${runs.filter(r => r.length > 1).map(r => `<polygon class="area" points="${r[0][0]},${h - pad.b} ${r.map(q => q.join(',')).join(' ')} ${r.at(-1)[0]},${h - pad.b}"/><polyline class="line" pathLength="1" points="${r.map(q => q.join(',')).join(' ')}"/>`).join('')}
    ${points.map((p, i) => (p.notable && i > 0 && Number.isFinite(points[i - 1].value) ? `<line class="seg-notable" x1="${x(i - 1)}" y1="${y(points[i - 1].value)}" x2="${x(i)}" y2="${y(p.value)}"/>` : '')).join('')}
    ${missing.map(([p, i]) => `<g><line x1="${x(i)}" x2="${x(i)}" y1="${pad.t}" y2="${h - pad.b}" class="gap"/><text class="xl" x="${x(i)}" y="${pad.t - 24}" text-anchor="${i === 0 ? 'start' : i === points.length - 1 ? 'end' : 'middle'}">no value</text><text class="xl" x="${x(i)}" y="${h - 12}" text-anchor="middle">${esc(p.label)}</text></g>`).join('')}
    ${points.map((p, i) => (!Number.isFinite(p.value) ? '' : `<g>${p.notable ? `<circle class="halo" cx="${x(i)}" cy="${y(p.value)}" r="15"/>` : ''}<circle class="pt ${p.notable ? 'notable' : ''}" cx="${x(i)}" cy="${y(p.value)}" r="${p.notable ? 6.5 : 4.5}"/>
      ${p.notable ? `<g class="flag"><rect x="${x(i) - 34}" y="${y(p.value) - 42}" width="68" height="24" rx="12"/><text x="${x(i)}" y="${y(p.value) - 26}" text-anchor="middle">${esc(changeLabel(p.row))}</text></g>`
        : `<text class="vl" x="${x(i)}" y="${y(p.value) - 14}" text-anchor="middle">${esc(indicatorValue(indicator, p.value))}</text>`}
      <text class="xl" x="${x(i)}" y="${h - 12}" text-anchor="middle">${esc(p.label)}</text>
      <circle class="hit" cx="${x(i)}" cy="${y(p.value)}" r="18" data-i="${i}" tabindex="0"/></g>`)).join('')}
  </svg><div class="tip" id="tip"></div></div>
  ${missing.length ? `<p class="note gap-note">${icon('info')}${missing.length === 1 ? 'One period has' : `${missing.length} periods have`} no value for this area, so the line is broken there rather than joined across the gap.</p>` : ''}`;
}

async function areas(_, params) {
  crumbs(['Area trends']);
  const level = params.get('level') || 'state';
  let indicator = params.get('indicator');
  let data = await api(url('/api/aggregates', { run: S.run, level, indicator: indicator || 'ur_cws_15plus', limit: 5000 }));
  if (!data.available) {
    app.innerHTML = `<section class="panel q-hero"><div class="qh-main">${tag('Area trends')}<h1 class="display">Area trends</h1></div></section><div class="panel">${emptyState('No historical layer for this survey round', 'Area trends need the historical layer; none is attached to this survey round.')}</div>`;
    return;
  }
  const atLevel = data.notable.filter(r => r.level === level);
  if (!indicator) {
    indicator = atLevel[0]?.indicator || 'ur_cws_15plus';
    if (indicator !== 'ur_cws_15plus') data = await api(url('/api/aggregates', { run: S.run, level, indicator, limit: 5000 }));
  }
  const areasList = [...new Map(data.rows.map(r => [r.area_label, r])).keys()];
  const chosen = params.get('area') || atLevel.find(r => r.indicator === indicator)?.area_label || areasList[0];
  const seriesRows = data.rows.filter(r => r.area_label === chosen);
  const byPeriod = new Map(seriesRows.map(r => [r.period_label, r]));
  const periodLabels = data.periods?.length ? data.periods : seriesRows.map(r => r.period_label);
  const series = periodLabels.map(label => { const r = byPeriod.get(label); return { label, value: r && r.value != null ? r.value : NaN, notable: Boolean(r?.notable_change), row: r || {} }; });
  const label = shortIndicator(data.indicators.find(i => i.indicator === indicator)?.indicator_label);
  const link = extra => `#/areas?${new URLSearchParams({ level, indicator, ...extra }).toString()}`;
  const unit = INDICATOR_UNITS[indicator];
  const change = r => (r.change == null ? '—' : (r.change > 0 ? '+' : '−') + (unit === 'share' ? `${Math.abs(r.change * 100).toFixed(1)} points` : indicatorValue(indicator, Math.abs(r.change))));
  const selectedChange = seriesRows.filter(r => r.notable_change).sort((a, b) => Math.abs(b.robust_z) - Math.abs(a.robust_z))[0];
  const levelWord = { national: 'All India', state: 'States/UTs', district: 'Districts' }[level];
  const missingCount = series.filter(p => !Number.isFinite(p.value)).length;
  const statement = selectedChange
    ? `${esc(label)} ${selectedChange.change > 0 ? 'rose' : 'fell'} from <b>${esc(indicatorValue(indicator, selectedChange.previous_value))}</b> to <b>${esc(indicatorValue(indicator, selectedChange.value))}</b> in ${esc(selectedChange.period_label)}`
    : `No unusual change in ${esc(label.toLowerCase())} for this area`;

  app.innerHTML = `
    <section class="panel q-hero a-hero rv">
      <div class="qh-main">
        ${tag('Area trends')}
        <h1 class="display">Where are unusual changes occurring?</h1>
        <p class="lede">Changes in weighted area indicators from one period to the next, compared with the changes seen in other areas over the same period.</p>
      </div>
      <div class="qh-count"><span class="g">${count(atLevel.length)}</span><span class="gl">unusual ${plural(atLevel.length, 'change')} <br>${esc(levelWord)}</span></div>
      <div class="q-filters a-controls">
        <div class="dtabs" role="group" aria-label="Area level">${[['state', 'States/UTs'], ['national', 'All India'], ['district', 'Districts']].map(([v, l]) => `<a class="${level === v ? 'on' : ''}" href="#/areas?${new URLSearchParams({ level: v })}">${l}</a>`).join('')}</div>
        <div class="a-picks">
          <label class="fld inline"><span>Indicator</span><select id="aInd">${data.indicators.map(i => `<option value="${esc(i.indicator)}" ${i.indicator === indicator ? 'selected' : ''}>${esc(shortIndicator(i.indicator_label))}</option>`).join('')}</select></label>
          <label class="fld inline"><span>Area</span><select id="aArea">${areasList.map(a => `<option ${a === chosen ? 'selected' : ''}>${esc(a)}</option>`).join('')}</select></label>
          <span class="periods">${icon('history')}${esc(data.periods?.[0] || '')}${data.periods?.length > 1 ? ` – ${esc(data.periods.at(-1))}` : ''}</span>
        </div>
      </div>
    </section>
    <div class="areas-grid">
      <section class="panel chart-card rv">
        ${tag('What changed?')}
        <h2 class="a-state">${statement}</h2>
        <p class="a-area">${icon('pin')}${esc(chosen || '')} · ${esc(label)}, by period</p>
        ${trendChart(series, indicator)}
        <div class="legend tl"><span><i class="lg-line"></i>${esc(label)}</span><span><i class="lg-obs"></i>Unusual change from the period before</span>${missingCount ? '<span><i class="lg-gap"></i>No value for this period</span>' : ''}</div>
        <div class="a-why">
          <div><h4>${icon('spark')}Why it matters</h4><p>${selectedChange ? 'This change is much larger than the changes seen in other areas over the same period. It is a prompt to look at the records from this area and period — not a finding of error, and not an official estimate.' : 'Changes from period to period are in line with those in other areas, so nothing here asks for a closer look.'}</p></div>
          <div><h4>${icon('compare')}Evidence</h4><p>${selectedChange ? `${esc(baseText(selectedChange))}. Compared with the change in every other ${level === 'district' ? 'district' : 'area'} over the same period.` : `${n(series.filter(p => Number.isFinite(p.value)).length)} of ${n(series.length)} periods have a value for this area.`}${missingCount ? ` ${n(missingCount)} ${plural(missingCount, 'period has', 'periods have')} no value and ${missingCount === 1 ? 'is' : 'are'} left as a gap.` : ''}</p></div>
        </div>
        <details class="acc"><summary><span class="acc-ico">${icon('cases')}</span><span class="acc-t">View details</span><span class="acc-h">values, changes and sample sizes</span>${icon('chev', 'acc-chev')}</summary><div class="acc-body">
          <div class="table-wrap"><table class="table"><thead><tr><th>Period</th><th>Value</th><th>Change</th><th>Persons 15+</th><th>Change status</th></tr></thead><tbody>
            ${seriesRows.map(r => `<tr><td>${esc(r.period_label)}</td><td class="tabular">${esc(indicatorValue(indicator, r.value))}</td><td class="tabular">${esc(change(r))}</td><td class="tabular">${n(r.persons_15plus)}</td>
              <td>${r.notable_change ? '<span class="chip red"><span class="dot"></span>Unusual change</span>' : r.change_status === 'ASSESSABLE' ? '<span class="chip plain"><span class="dot"></span>Usual change</span>' : `<span class="muted small">${esc(String(r.change_reason || 'not assessed').replace(/_/g, ' ').toLowerCase())}</span>`}</td></tr>`).join('')}
          </tbody></table></div></div></details>
      </section>
      <section class="panel changes-card rv">
        ${tag('All unusual changes')}
        <h3>${esc(levelWord)} · all indicators · largest first</h3>
        ${atLevel.length ? `<ul class="changes">${atLevel.map((r, i) => `<li ${i >= 8 && !(r.area_label === chosen && r.indicator === indicator) ? 'class="extra hidden"' : ''}><a class="${r.area_label === chosen && r.indicator === indicator ? 'sel' : ''}" href="${link({ indicator: r.indicator, area: r.area_label })}">
            <span class="ch-tile ${r.change > 0 ? 'up' : 'down'}">${slopeGlyph(r.change)}</span>
            <span class="ch-txt"><b>${esc(r.area_label)}</b><span class="stmt">${esc(shortIndicator(r.indicator_label))} ${r.change > 0 ? 'rose' : 'fell'} from ${esc(indicatorValue(r.indicator, r.previous_value))} to ${esc(indicatorValue(r.indicator, r.value))}</span><span class="base">${esc(baseText(r))}</span></span>
            <span class="ch-tag">${esc(r.period_label)}</span></a></li>`).join('')}</ul>
          ${atLevel.length > 8 ? `<button class="btn line sm" id="showAll">Show all ${n(atLevel.length)} changes</button>` : ''}`
          : emptyState('No unusual changes at this level', 'No period-on-period change stands out from the changes in other areas.')}
      </section>
    </div>
    <details class="acc panel-acc"><summary><span class="acc-ico">${icon('technical')}</span><span class="acc-t">How unusual changes are identified</span><span class="acc-h">method and limits</span>${icon('chev', 'acc-chev')}</summary><div class="acc-body"><div class="note" style="max-width:85ch;display:flex;flex-direction:column;gap:8px">
      <p><b>Screening values, not official estimates.</b> ${data.limitations.map(esc).join(' ')} ${data.design_period === 'post_2025' ? 'January 2025 begins the redesigned survey and is never compared with earlier releases.' : ''}</p>
      <p>A change is marked unusual when it is at least 3.5 robust standard deviations from the typical change across areas in that period <b>and</b> at least 3 times its own simple-random-sampling standard error, so that small areas' sampling noise is not flagged. Design effects are ignored, so the screen is still somewhat liberal. It is a prompt to look at the area's records, not a finding of error.</p>
    </div></div></details>`;

  document.querySelector('#showAll')?.addEventListener('click', e => { app.querySelectorAll('.changes .extra').forEach(li => li.classList.remove('hidden')); e.currentTarget.remove(); });
  document.querySelector('#aInd').onchange = e => go(`#/areas?${new URLSearchParams({ level, indicator: e.target.value })}`);
  document.querySelector('#aArea').onchange = e => go(link({ area: e.target.value }));
  const tip = document.querySelector('#tip');
  const show = c => {
    const p = series[Number(c.dataset.i)], r = p.row, svg = c.ownerSVGElement, box = svg.getBoundingClientRect(), vb = svg.viewBox.baseVal;
    tip.innerHTML = `<b>${esc(p.label)}</b> · ${esc(indicatorValue(indicator, p.value))} <br>${r.change == null ? 'No earlier period to compare' : `Change ${esc(change(r))}`}${r.notable_change ? '<br><span class="w">Unusual change</span>' : ''}`;
    tip.style.left = `${(c.cx.baseVal.value / vb.width) * box.width}px`;
    tip.style.top = `${(c.cy.baseVal.value / vb.height) * box.height}px`;
    tip.classList.add('show');
  };
  app.querySelectorAll('svg.trend .hit').forEach(c => {
    c.addEventListener('mouseenter', () => show(c)); c.addEventListener('focus', () => show(c));
    c.addEventListener('mouseleave', () => tip.classList.remove('show')); c.addEventListener('blur', () => tip.classList.remove('show'));
  });
}

/* ------------------------------------------------------------ technical reference (secondary) */

const pct1 = v => (v == null || !Number.isFinite(v) ? '—' : `${(v * 100).toFixed(1)}%`);

function evaluationHtml(evaluation) {
  if (!evaluation.available) return `<p class="muted">No controlled evaluation has been run yet (<code>python -m evaluation.run --release 2024</code>).</p>`;
  return Object.values(evaluation.results).map(r => {
    const rows = Object.entries(r.experiments);
    const types = Object.keys(r.experiments['E6 full hybrid']?.recall_by_error_type_at_5pct || {});
    const g = r.group_level || {};
    // Errors that break a documented rule are listed first by design (and are already blocked by CAPI;
    // the real deliveries contain none), so they are separated out here.  Derived from stored per-type recall only.
    const RULE_TYPES = ['age_status_rule', 'status_earnings_rule'];
    const recordTypes = Object.entries(r.injected_by_type).filter(([k]) => k !== 'fsu_fabrication');
    const nonRule = recordTypes.filter(([k]) => !RULE_TYPES.includes(k));
    const nonRuleTotal = nonRule.reduce((a, [, v]) => a + v, 0);
    const nonRuleRecall = (e, cut) => {
      const byType = r.experiments[e]?.[`recall_by_error_type_at_${cut}`];
      return byType && nonRuleTotal ? nonRule.reduce((a, [k, v]) => a + (byType[k] || 0) * v, 0) / nonRuleTotal : null;
    };
    const nonRuleExps = ['E1 statistical', 'E3h historical', 'E3 machine learning', 'E2 contextual', 'E6 full hybrid'].filter(e => r.experiments[e]?.recall_by_error_type_at_1pct);
    const nonRuleHtml = nonRuleExps.length ? `<div class="table-wrap" style="margin-top:12px"><table class="table"><thead><tr><th>Errors that break no documented rule (${n(nonRuleTotal)} injected)</th>${nonRuleExps.map(e => `<th>${esc(e.split(' ').slice(1).join(' '))}</th>`).join('')}</tr></thead><tbody>
        <tr><td>Recall in top 1%</td>${nonRuleExps.map(e => `<td class="tabular">${pct1(nonRuleRecall(e, '1pct'))}</td>`).join('')}</tr>
        <tr><td>Recall in top 5%</td>${nonRuleExps.map(e => `<td class="tabular">${pct1(nonRuleRecall(e, '5pct'))}</td>`).join('')}</tr></tbody></table></div>
      <p class="note" style="margin-top:6px">The full hybrid's top-1% precision is mostly the ${n(recordTypes.filter(([k]) => RULE_TYPES.includes(k)).reduce((a, [, v]) => a + v, 0))} injected rule breaches, which are listed first by design and which CAPI already blocks (the real deliveries contain none). ${(() => { const single = Math.max(nonRuleRecall('E1 statistical', '1pct') ?? 0, nonRuleRecall('E3h historical', '1pct') ?? 0), hybrid = nonRuleRecall('E6 full hybrid', '1pct') ?? 0; return single > hybrid ? 'For the other errors, a single comparison (statistical or historical) finds more of them in the top 1% than the combined priority does.' : 'For the other errors, the combined priority finds at least as many in the top 1% as any single comparison.'; })()}</p>` : '';
    return `<h3 class="t-h3">${esc(r.release === '2025' ? 'Post-2025 design (2025, Jan–Jun)' : 'Pre-2025 design (2024)')} — ${n(r.records)} records, ${n(Object.entries(r.injected_by_type).filter(([k]) => k !== 'fsu_fabrication').reduce((a, [, v]) => a + v, 0))} injected record errors, ${n(r.injected_by_type.fsu_fabrication || 0)} fabricated FSUs</h3>
      <div class="table-wrap"><table class="table"><thead><tr><th>Experiment</th><th>Average precision</th><th>ROC-AUC</th><th>Precision @1%</th><th>Recall @1%</th><th>F0.5 @1%</th><th>Recall @5%</th></tr></thead><tbody>
      ${rows.map(([name, m]) => `<tr><td>${esc(name)}</td><td class="tabular">${m.average_precision != null ? m.average_precision.toFixed(3) : '—'} <span class="muted small">(chance ${m.chance_average_precision != null ? m.chance_average_precision.toFixed(3) : '—'})</span></td><td class="tabular">${m.roc_auc != null ? m.roc_auc.toFixed(3) : '—'}</td>
        <td class="tabular">${pct1(m.at_1pct?.precision)}</td><td class="tabular">${pct1(m.at_1pct?.recall)}</td><td class="tabular">${m.at_1pct ? m.at_1pct.f0_5.toFixed(3) : '—'}</td><td class="tabular">${pct1(m.at_5pct?.recall)}</td></tr>`).join('')}
      </tbody></table></div>
      <div class="table-wrap" style="margin-top:12px"><table class="table"><thead><tr><th>Error type — recall in top 5%</th>${['E1 statistical', 'E2 contextual', 'E3 machine learning', 'E3h historical', 'E0 rules only', 'E6 full hybrid'].map(e => `<th>${esc(e.split(' ').slice(1).join(' '))}</th>`).join('')}</tr></thead><tbody>
      ${types.map(t => `<tr><td>${esc(t.replace(/_/g, ' '))}</td>${['E1 statistical', 'E2 contextual', 'E3 machine learning', 'E3h historical', 'E0 rules only', 'E6 full hybrid'].map(e => `<td class="tabular">${pct1(r.experiments[e]?.recall_by_error_type_at_5pct?.[t])}</td>`).join('')}</tr>`).join('')}
      </tbody></table></div>
      ${nonRuleHtml}
      <p class="note" style="margin-top:10px">FSU fabrication (group level): ${pct1(g.recall_notable_q_lt_0_05)} of fabricated FSUs flagged (q &lt; 0.05); ${pct1(g.precision_among_notable)} of flagged FSUs were fabricated; ${pct1(g.false_positive_rate_clean_fsus)} of clean FSUs flagged. <b>Measured before the clustering (overdispersion) correction now applied to the FSU checks; the corrected FSU checks have not been re-evaluated.</b>
      Average record risk of people in fabricated FSUs ${g.member_vs_all_mean_risk ? g.member_vs_all_mean_risk.fabricated_fsu_members.toFixed(3) : '—'} vs all records ${g.member_vs_all_mean_risk ? g.member_vs_all_mean_risk.all_records.toFixed(3) : '—'} (group evidence does not raise individual risk).</p>`;
  }).join('') + `<p class="note" style="margin-top:10px"><b>Injected errors only.</b> Injected errors are the only known positives. Records not injected may still contain real errors, so precision is a lower bound and the false-positive rate an upper bound. These results show how the method behaves on realistic synthetic errors; they are not an accuracy figure for real PLFS errors, for which no confirmed labels exist.</p>`;
}

async function technical() {
  crumbs(['Technical reference']);
  const [{ report, metadata }, evaluation, integrity] = await Promise.all([api(url('/api/summary', { run: S.run })), api('/api/evaluation'), api(url('/api/integrity', { run: S.run }))]);
  const p = metadata.parameters || {};
  const v2 = String(metadata.fusion_version || '').includes('v2');
  const dist = d => (d && d.count ? `median ${d.p50.toFixed(3)} · 95th percentile ${d.p95.toFixed(3)} · range ${d.min.toFixed(3)}–${d.max.toFixed(3)}` : 'not available');
  const avail = report.source_availability || {};
  const totalRecords = report.records_processed || 1;
  const cov = (label, value) => `<div class="cl"><span>${esc(label)}</span><b>${n(value)} <span class="muted small">(${pct(value || 0, totalRecords)})</span></b><span class="bar"><i style="width:${((value || 0) / totalRecords) * 100}%"></i></span></div>`;
  const weights = p.source_weights || {};
  app.innerHTML = `
    <section class="panel q-hero rv">
      <div class="qh-main">
        ${tag('For researchers, technical staff and audit')}
        <h1 class="display">Technical reference</h1>
        <p class="lede">How the review list is produced, what data it uses, how it was evaluated, and its known limitations. Supervisors can complete every review without this page.</p>
      </div>
    </section>
    <div class="tech-banner"><b>Status labels used below.</b> <b>Validated</b>: checked against official documents or published magnitudes. <b>Evaluated</b>: measured on controlled injected errors. <b>Provisional</b>: an engineering choice not learned from confirmed PLFS errors. <b>Not assessable</b>: the data cannot support it. Nothing on this page is an accuracy figure for real PLFS errors.</div>
    ${v2 ? '' : '<div class="notice error">This is an earlier (V1) Fusion run. Its influence, FSU handling and earnings evidence have known defects; use a V2 run.</div>'}
    <div class="tech-grid">
      <section class="panel tp rv"><h2>How priority is calculated ${v2 ? '(V2)' : '(V1)'}</h2>
        <p>Each record-level evidence score is converted to a within-run percentile rank; a value equal to its comparison-group median counts as no evidence (rank 0). Unavailable sources are excluded, never treated as zero. <b>Provisional.</b></p>
        <div class="formula">risk = weighted mean of available record-level ranks <br>weights: ${Object.entries(weights).map(([k, w]) => `${esc(k)} ${w}`).join(', ')}</div>
        <div class="formula">if any record-level rank ≥ ${p.override_rank_threshold}: risk = max(risk, that rank)</div>
        <div class="formula">local score (per variable) = final weight × |reported − comparison-group median| ÷ weighted total of that variable in its State/UT × sector × quarter or month <br>influence = percentile rank of the largest local score</div>
        <div class="formula">priority = risk × influence; a documented-rule breach is listed first</div>
        <p>FSU (group) evidence is <b>not</b> part of risk; it forms its own queue, ordered by Benjamini–Hochberg q-values (clear difference q &lt; 0.01, difference q &lt; 0.05). Bands: ${(p.priority_bands || []).map(([b, t]) => `${esc(b)} ≥ ${t}`).join(' · ')} (provisional).</p>
        <p class="note">Supervisor wording: “Unusualness” and “Potential influence” on the case page are the risk and influence ranks put into words (very high ≥ 0.99, high ≥ 0.95, moderate ≥ 0.80, otherwise low). “Why these records are here” on the Overview counts highest-priority records with each source rank ≥ ${UNUSUAL}.</p>
      </section>
      <section class="panel tp rv"><h2>Coverage in this run</h2>
        <div class="cov">
          ${cov('Records processed', report.records_processed)}
          ${cov('Records with a calculated priority', report.priority_rows)}
          ${cov('Comparison with similar records (applicable values)', avail.statistical)}
          ${cov('Comparison with earlier periods', avail.historical)}
          ${cov('Occupation check', avail.contextual)}
          ${cov('Machine-learning checks', avail.ml)}
          ${cov('FSU pattern context attached', avail.pattern)}
        </div>
        <table class="numbers" style="margin-top:14px"><tr><td>Records breaking a documented rule</td><td>${n(report.rule_violation_records ?? 0)}</td></tr><tr><td>FSUs with a notable group difference</td><td>${n(report.notable_groups ?? 0)}</td></tr><tr><td>Fusion runtime</td><td>${esc(report.runtime_seconds)} s</td></tr></table>
        <p class="note" style="margin-top:10px">Risk: ${esc(dist(report.risk_distribution))} <br>Influence: ${esc(dist(report.influence_distribution))} <br>Priority: ${esc(dist(report.priority_distribution))} <br>Records without an applicable earnings or hours value have no influence and therefore no priority; they are listed as “priority not calculated”.</p>
      </section>
      <section class="panel tp wide rv"><h2>Controlled evaluation (E0–E7) <span class="chip amber"><span class="dot"></span>Evaluated on injected errors</span></h2>${evaluationHtml(evaluation)}</section>
      <section class="panel tp wide rv"><h2>Documented integrity rules <span class="chip green"><span class="dot"></span>Validated against PLFS documents</span></h2>
        ${integrity.available ? `<p class="muted small">${n(integrity.records_checked)} records checked with rule set ${esc(integrity.rule_set_version)}; ${n(integrity.records_with_violations)} with a violation. Rules are edited in <code>integrity/rules/plfs_person_rules.yaml</code>.</p>
        <div class="table-wrap" style="margin-top:10px"><table class="table"><thead><tr><th>Rule</th><th>Source</th><th>Records</th></tr></thead><tbody>${integrity.rules.map(r => `<tr><td><b>${esc(r.id)}</b><br><span class="small">${esc(r.message)}</span></td><td class="small">${esc(r.source)}</td><td class="tabular">${n((integrity.violations.find(v => v.rule_id === r.id) || {}).records || 0)}</td></tr>`).join('')}</tbody></table></div>`
          : '<p class="muted">No integrity run is attached to this Fusion run.</p>'}
      </section>
      <section class="panel tp rv"><h2>Online record check</h2>
        <p class="muted small">Checks one record — as it might arrive from CAPI/eSigma — against the documented rules and the stored comparison groups of this survey round. Nothing is stored. The fields start empty; enter the record's own values.</p>
        <form id="vForm" class="validate-form">
          ${[['state', 'State/UT code', '07'], ['sector', 'Sector (1 rural, 2 urban)', '2'], ['cws_status', 'Current weekly status', '31'], ['age', 'Age', '35'], ['education', 'General education code', '12'],
             ['occupation_code', 'Occupation code (3 digits)', '241'], ['industry_code', 'Industry code (NIC)', '64190'], ['earnings_salaried', 'Salaried earnings (₹, last month)', '45000'],
             ['earnings_self_employed', 'Self-employment earnings (₹, 30 days)', '0'], ['day7_hours', 'Hours on day 7', '8']].map(([k, l, v]) => `<label class="fld"><span>${esc(l)}</span><input name="${k}" placeholder="e.g. ${v}"></label>`).join('')}
          <button class="btn dark" type="submit">Check record</button>
        </form>
        <div id="vResult"></div>
      </section>
      <section class="panel tp rv"><h2>Audit findings (3 Oct 2026) — resolution</h2>
        <ul class="audit-list">
          ${[['RESOLVED', 'Salaried-earnings model: trained only on applicable earners, with State/UT and sector; estimate now centred (estimate ÷ group median 0.99, was 0.47); shown as a “model estimate”.'],
             ['RESOLVED', 'Questionnaire placeholders (0 for items not asked) are excluded from statistical, model, pattern, influence and historical evidence.'],
             ['RESOLVED', 'FSU evidence no longer enters record risk or the override; separate FSU queue by q-value.'],
             ['RESOLVED', 'Influence no longer mixes rupees and hours (per-variable share of a weighted domain total). Remains provisional.'],
             ['RESOLVED', 'Pattern: tested scores (G-test, Mann–Whitney, binomial), q-values, direction-safe statements, valid probabilities; age-only heaping.'],
             ['RESOLVED', 'LOF fitted on distinct points; no numerical explosions; too few distinct values is not assessable.'],
             ['PARTLY', 'Historical comparison and aggregate drift implemented within each design period; cross-release record linkage is not possible and is not attempted.'],
             ['RESOLVED', 'Controlled evaluation E0–E7 run on injected errors (see above).'],
             ['RESOLVED', 'Full CSV export (streamed), integrity rule facility, online record check, optional token authentication.'],
             ['OPEN', 'Weights, override and bands remain provisional; no confirmed real-error labels exist; no design-based standard errors for area trends.']]
            .map(([s, t]) => `<li><span class="sev ${s === 'RESOLVED' ? 'ok' : s === 'PARTLY' ? 'partly' : 'open'}">${s}</span><span>${esc(t)}</span></li>`).join('')}
        </ul>
        <p class="note" style="margin-top:10px">Original findings (before these fixes): <code>AUDIT_2026-10-03.md</code>. Current assessment against the MoSPI project brief: <code>docs/FINAL_EVALUATION_AGAINST_PROBLEM_STATEMENT.md</code>. UI audit: <code>docs/UI_AUDIT_2026-10-05.md</code>.</p>
      </section>
      <section class="panel tp rv"><h2>Known limitations</h2>
        <ul class="plain">
          <li><b>No confirmed real-error labels.</b> Performance is measured on injected errors only.</li>
          <li><b>Provisional weights and thresholds.</b> Source weights, the 0.995 override and the priority bands are engineering choices; the evaluation compares them but does not make them optimal.</li>
          <li><b>Provisional influence.</b> Uses the comparison-group median as the stand-in correct value and State/UT × sector × period weighted totals; not validated against official LFPR/WPR/UR or earnings estimates.</li>
          <li><b>Evidence independence not established.</b> Earnings feed several sources; they are complementary, not independent proofs.</li>
          <li><b>Historical scope.</b> Earlier periods are used only within the same survey design; nominal rupees are not deflated; 2025 history is limited to earlier 2025 months.</li>
          <li><b>Survey-design boundaries.</b> No pooling across the January 2025 redesign; area screening has no design-based standard errors.</li>
          <li><b>FSU tests</b> use large-sample approximations; small FSUs (10–15 people) have approximate p-values. No enumerator identifier exists; FSU patterns are never attributed to individuals.</li>
          <li><b>Revisit (panel) evidence</b> is computed for 2023–24 but not part of the first-visit review list.</li>
        </ul>
      </section>
      <section class="panel tp rv"><h2>Provenance</h2>
        <table class="numbers">
          <tr><td>Fusion run</td><td>${esc(metadata.run_id)} (${esc(metadata.fusion_version || 'v1')})</td></tr>
          <tr><td>Release / observation / design period</td><td>${esc(metadata.release)} / ${esc(metadata.observation)} / ${esc(metadata.design_period)}</td></tr>
          <tr><td>Preparation run</td><td>${esc(metadata.input_preprocessing_run_id)}</td></tr>
          ${Object.entries(metadata.source_runs || {}).map(([k, v]) => `<tr><td>${esc(k)} run</td><td>${esc(v)}</td></tr>`).join('')}
        </table>
        <p class="note" style="margin-top:10px">Case-page wording uses display conventions (e.g. “very unusual” for a record-level rank ≥ 0.99, “unusual” ≥ 0.95, “somewhat unusual” ≥ 0.80; “much higher than usual” when the value is at least twice the comparison group's 95th percentile; FSU wording from q-values). They choose words only and do not change any score.</p>
      </section>
    </div>
    <details class="acc panel-acc"><summary><span class="acc-ico">${icon('technical')}</span><span class="acc-t">Full run metadata</span><span class="acc-h">JSON</span>${icon('chev', 'acc-chev')}</summary><div class="acc-body"><pre class="code">${esc(JSON.stringify({ metadata, report }, null, 2))}</pre></div></details>`;
  document.querySelector('#vForm').onsubmit = async e => {
    e.preventDefault();
    const record = Object.fromEntries([...new FormData(e.target).entries()].filter(([, v]) => String(v).trim() !== ''));
    const result = await api(url('/api/validate/record', { run: S.run }), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ record }) });
    const comp = result.comparisons.map(c => c.status === 'ASSESSED'
      ? `<tr><td>${esc(c.target.replace(/_/g, ' '))}</td><td>${esc(_tailText(c.position))}; higher than about ${(c.percentile * 100).toFixed(1)}% of ${n(c.comparison_size)} comparable records (typical ${esc(fmt(c.median, VAR_UNITS[c.target]))})</td></tr>`
      : `<tr><td>${esc(c.target.replace(/_/g, ' '))}</td><td class="muted">${esc(c.status.replace(/_/g, ' ').toLowerCase())}</td></tr>`).join('');
    document.querySelector('#vResult').innerHTML = `<div class="${result.rule_violations.length ? 'notice error' : 'notice'}" style="margin-top:12px">${result.rule_violations.length ? result.rule_violations.map(v => `${esc(v.rule_id)}: ${esc(v.message)}`).join('<br>') : 'No documented rule is breached.'}</div>
      ${comp ? `<table class="numbers">${comp}</table>` : ''}<p class="note">${esc(result.note)}</p>`;
  };
}
function _tailText(position) { return { UPPER_TAIL: 'Above the usual range', LOWER_TAIL: 'Below the usual range' }[position] || 'Within the usual range'; }

/* ------------------------------------------------------------ sign-in */

function signIn() {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'signin';
    overlay.innerHTML = `<form class="panel"><span class="cta-mark">${MARK}</span><h2 class="display">Sign in</h2><p class="muted small">This workspace requires an access token issued by your administrator. It is kept only for this browser session.</p>
      <label class="fld"><span>Access token</span><input type="password" name="token" autocomplete="current-password" required></label>
      <button class="btn dark lg" type="submit">Sign in</button></form>`;
    document.body.appendChild(overlay);
    overlay.querySelector('input').focus();
    overlay.querySelector('form').onsubmit = e => { e.preventDefault(); store.set('s:MoSPI.token', overlay.querySelector('input').value.trim()); overlay.remove(); resolve(); };
  });
}

/* ------------------------------------------------------------ start */

runSelect.onchange = () => { S.run = runSelect.value; S.filters = {}; S.page = 1; S.ov = null; saveFilters(); store.set('l:MoSPI.run', S.run); route(); };
reviewerInput.value = store.get('l:MoSPI.reviewer', '');
setAvatar();
reviewerInput.oninput = setAvatar;
reviewerInput.onchange = () => { store.set('l:MoSPI.reviewer', reviewer()); const who = document.querySelector('#who'); if (who) who.textContent = reviewer() ? `Saving as ${reviewer()}` : 'Add your name at the top right so the audit trail shows who decided.'; };

(async () => {
  try {
    const required = await fetch('/api/session/required').then(r => r.json()).catch(() => ({ authentication: false }));
    if (required.authentication) {
      if (!authToken()) await signIn();
      const session = await api('/api/session');
      S.user = session.user;
      if (S.user) { reviewerInput.value = S.user.name; reviewerInput.readOnly = true; reviewerInput.title = `Signed in as ${S.user.name} (${S.user.role})`; setAvatar(); }
    }
    [S.runs, S.labels] = await Promise.all([api('/api/runs'), api('/api/labels')]);
    if (!S.runs.length) throw new Error('No Fusion run is available.');
    const remembered = store.get('l:MoSPI.run', null);
    S.run = S.runs.some(r => r.directory === remembered) ? remembered : S.runs[0].directory;
    runSelect.innerHTML = S.runs.map(r => `<option value="${esc(r.directory)}" ${r.directory === S.run ? 'selected' : ''}>${esc(runLabel(r))}</option>`).join('');
    const saved = store.get('s:MoSPI.filters', null);
    if (saved && saved.run === S.run) { S.filters = saved.filters || {}; S.page = saved.page || 1; }
    await route();
  } catch (e) {
    notice(e.message, 'error');
    app.innerHTML = `<div class="panel">${emptyState('No review list is available yet.', 'A Fusion run must be created first; this workspace never generates substitute data.')}</div>`;
  }
})();
