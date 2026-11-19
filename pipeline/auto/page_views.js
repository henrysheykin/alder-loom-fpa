// ---------------------------------------------------------------- auto helpers
const LOCS = ["LOC-01", "LOC-02", "LOC-03"];
const NM = { COMPANY: "Company", "LOC-01": "North Creek", "LOC-02": "River West", "LOC-03": "Oak Junction", HQ: "HQ" };
const LCOL = { "LOC-01": "--s1", "LOC-02": "--s3", "LOC-03": "--s4" };
const KP = e => DS.kpi_monthly.rows.filter(r => r.entity === e);
const P = () => KP("COMPANY").map(r => r.period);
const PER = { l12: () => P().slice(-12), l3: () => P().slice(-3), fy25: () => P().slice(0, 12), fy26: () => P().slice(12) };
const PNAME = { l12: "Last 12 months", l3: "Last 3 months (Aug–Oct 2026)", fy25: "FY2025 (Nov 24 – Oct 25)", fy26: "FY2026 (Nov 25 – Oct 26)" };
const NUMK = ["net_revenue", "budget_net_revenue", "labor_sales", "parts_sales", "concessions", "technician_labor", "budget_technician_labor", "parts_cogs", "budget_parts_cogs", "warranty_net", "budget_warranty_net",
  "inventory_loss", "sublet_cogs", "contribution", "budget_contribution", "shop_payroll", "hq_payroll", "rent", "overhead", "maintenance", "marketing", "merchant_fees", "ebitda", "budget_ebitda",
  "depreciation", "interest", "net_income", "budget_net_income", "customer_ros", "fleet_ros", "warranty_ros", "ro_net_sales", "fleet_net_sales", "book_hours", "cohort_clock_hours",
  "tech_available_hours", "tech_worked_hours", "tech_paid_hours", "warranty_clock_hours", "comebacks", "ad_spend", "leads", "booked_leads"];
function agg(e, periods) {
  const ps = new Set(periods), o = {}; NUMK.forEach(k => o[k] = 0);
  for (const r of DS.kpi_monthly.rows) if (r.entity === e && ps.has(r.period)) NUMK.forEach(k => o[k] += +r[k] || 0);
  const nr = o.net_revenue, lab = KP("COMPANY").length ? 0 : 0;
  return Object.assign(o, { ebitda_pct: nr ? o.ebitda / nr : null, contrib_pct: nr ? o.contribution / nr : null, vs_bud: o.budget_net_revenue ? nr / o.budget_net_revenue - 1 : null,
    aro: o.customer_ros ? o.ro_net_sales / o.customer_ros : null, parts_margin: o.parts_sales ? (o.parts_sales - o.parts_cogs) / o.parts_sales : null,
    eff: o.cohort_clock_hours ? o.book_hours / o.cohort_clock_hours : null, util: o.tech_available_hours ? o.tech_worked_hours / o.tech_available_hours : null,
    elr: o.book_hours ? null : null, cb_rate: o.customer_ros ? o.comebacks / o.customer_ros : null, lab_pct: nr ? o.technician_labor / nr : null, parts_pct: nr ? o.parts_cogs / nr : null,
    book_rate: o.leads ? o.booked_leads / o.leads : null, cpl: o.booked_leads ? o.ad_spend / o.booked_leads : null, fleet_share: o.ro_net_sales ? o.fleet_net_sales / o.ro_net_sales : null });
}
const kv = (e, p, k) => { const r = DS.kpi_monthly.rows.find(x => x.entity === e && x.period === p); return r ? r[k] : null; };
const ratio = (e, p, a, b) => { const x = kv(e, p, a), y = kv(e, p, b); return y ? x / y : null; };
const pct100 = (e, p, k) => { const v = kv(e, p, k); return v == null ? null : v / 100; };
const yago = p => { const [y, m] = p.split("-"); return (+y - 1) + "-" + m; };
const sgn$ = v => (v >= 0 ? "+" : "−") + fmt$(Math.abs(v));
const varSpan = (v, good = 1, compact) => el("span", { class: Math.abs(v) < .5 ? "flat" : v * good > 0 ? "up" : "down", text: (v >= 0 ? "+" : "−") + fmt$(Math.abs(v), compact) });
const locCell = e => e === "COMPANY" ? "Company" : NM[e] + (e === "HQ" ? "" : " (" + e + ")");

// ---------------------------------------------------------------- P&L engine
const GROUPS = [["Revenue", "Net revenue", 1, "Net revenue"], ["Technician labor", "Technician labor", -1], ["Parts COGS", "Parts cost of sales", -1], ["Warranty (net)", "Warranty, net of supplier recoveries", -1],
  ["Inventory loss", "Inventory loss", -1], ["Sublet COGS", "Sublet cost", -1, "Contribution"], ["Shop staff payroll", "Shop staff payroll", -1], ["HQ payroll", "HQ payroll", -1], ["Rent", "Rent", -1],
  ["Occupancy & overhead", "Utilities, insurance, software, overhead", -1], ["Equipment maintenance", "Equipment maintenance", -1], ["Marketing", "Marketing", -1], ["Merchant fees", "Merchant fees", -1, "EBITDA"],
  ["Depreciation", "Depreciation", -1], ["Interest", "Interest", -1, "Net income"]];
const DIRECT_G = ["Technician labor", "Parts COGS", "Warranty (net)", "Inventory loss", "Sublet COGS"], OPEX_G = ["Shop staff payroll", "HQ payroll", "Rent", "Occupancy & overhead", "Equipment maintenance", "Marketing", "Merchant fees"];
function pnlFor(periods, e = "COMPANY", basis = "actual") {
  const ps = new Set(periods), v = {}, g = {};
  for (const r of DS.pnl_monthly.rows) if (r.entity === e && ps.has(r.period)) { const x = r.account_type === "contra_revenue" ? -r[basis] : r[basis]; v[r.account_id] = (v[r.account_id] || 0) + x; g[r.group] = (g[r.group] || 0) + x; }
  const G = k => g[k] || 0, nr = G("Revenue"), dir = sum(DIRECT_G.map(G)), opx = sum(OPEX_G.map(G));
  return Object.assign(v, { "Net revenue": nr, "Contribution": nr - dir, "EBITDA": nr - dir - opx, "Net income": nr - dir - opx - G("Depreciation") - G("Interest"), _g: g });
}
const ACC = () => { const m = {}; DS.pnl_monthly.rows.forEach(r => m[r.account_id] = { line: r.line, group: r.group }); return m; };
function bridgeChart(host, A, B) {
  const d = ks => -(sum(ks.map(k => A._g[k] || 0)) - sum(ks.map(k => B._g[k] || 0)));
  const steps = [["Revenue", A["Net revenue"] - B["Net revenue"]], [["Tech", "labor"], d(["Technician labor"])], [["Parts", "COGS"], d(["Parts COGS"])], [["Warranty", "& other"], d(["Warranty (net)", "Inventory loss", "Sublet COGS"])],
    [["Payroll", "staff/HQ"], d(["Shop staff payroll", "HQ payroll"])], [["Rent &", "overhead"], d(["Rent", "Occupancy & overhead", "Equipment maintenance"])], [["Mktg &", "fees"], d(["Marketing", "Merchant fees"])]];
  let run = B["EBITDA"]; const labels = ["Budget"], data = [[0, run]], colors = [css("--muted")];
  steps.forEach(([s, v]) => { labels.push(s); data.push([run, run + v]); colors.push(v >= 0 ? css("--good") : css("--crit")); run += v; });
  labels.push("Actual"); data.push([0, A["EBITDA"]]); colors.push(css("--muted"));
  const lo = Math.min(0, ...data.flat());
  mkChart(host, { _label: "EBITDA bridge", type: "bar", data: { labels, datasets: [{ label: "Impact", data, backgroundColor: colors, borderRadius: 4, borderSkipped: false, maxBarThickness: 34 }] },
    options: { interaction: { mode: "nearest", intersect: true }, plugins: { tooltip: { callbacks: { label: c => { const [a, b] = c.raw; const i = c.dataIndex; return i === 0 || i === labels.length - 1 ? " " + fmt$(b) : " " + sgn$(b - a); } } } },
      scales: { x: { ticks: { autoSkip: false, maxRotation: 0, font: { size: 10 } } }, y: { min: lo < 0 ? undefined : 0 } } } });
}

// ---------------------------------------------------------------- OVERVIEW
function renderOverview() {
  const A = agg("COMPANY", PER.fy26()), B = agg("COMPANY", PER.fy25()); const per = P(), lab = per.map(mLabel); const K = KP("COMPANY"), last = K[K.length - 1];
  const low = cashLow();
  tiles($("#ovTiles"), [
    ["Net revenue, FY2026", fmt$(A.net_revenue, true), [chg(A.net_revenue / B.net_revenue - 1), " YoY · ", el("span", { class: A.vs_bud >= 0 ? "up" : "down", text: (A.vs_bud >= 0 ? "+" : "") + fmtPct(A.vs_bud) + " vs budget" })]],
    ["EBITDA, FY2026", fmt$(A.ebitda, true), [fmtPct(A.ebitda_pct) + " margin · ", chg(A.ebitda_pct - B.ebitda_pct, 1, "pts"), " YoY"]],
    ["EBITDA vs budget", (A.ebitda >= A.budget_ebitda ? "+" : "−") + fmt$(Math.abs(A.ebitda - A.budget_ebitda), true), ["budget " + fmt$(A.budget_ebitda, true) + " · ", chg(A.ebitda / A.budget_ebitda - 1)]],
    ["Customer ROs, FY2026", fmtN(A.customer_ros), [chg(A.customer_ros / B.customer_ros - 1), " · ARO $" + A.aro.toFixed(0) + " (", chg(A.aro / B.aro - 1), ")"]],
    ["Parts margin", fmtPct(A.parts_margin), [chg(A.parts_margin - B.parts_margin, 1, "pts"), " vs FY2025"]],
    ["Technician utilization", fmtPct(A.util), ["efficiency " + fmtPct(A.eff, 0)]],
    ["Bank cash, 31 Oct", fmt$(last.bank, true), ["13-week low ", el("b", { text: fmt$(low.v, true) }), " (" + low.w + ")"]],
  ]);
  mkChart($("#chRev"), { _stacked: true, _label: "Net revenue by shop", data: { labels: lab, datasets: [
    line("Budget", per.map(p => kv("COMPANY", p, "budget_net_revenue")), css("--ink-2"), { borderDash: [5, 4], borderWidth: 1.5, order: 0, stack: "b" }),
    ...LOCS.map(e => bar(NM[e], per.map(p => kv(e, p, "net_revenue")), css(LCOL[e]), { order: 1, borderRadius: 0 }))] }, options: { scales: { y: { stacked: true } } } });
  mkChart($("#chRatios"), { _fmt: "pct", _label: "Margins", data: { labels: lab, datasets: [line("Contribution", per.map(p => ratio("COMPANY", p, "contribution", "net_revenue")), css("--s1")),
    line("EBITDA", per.map(p => ratio("COMPANY", p, "ebitda", "net_revenue")), css("--s3")), line("Parts margin", per.map(p => pct100("COMPANY", p, "parts_margin_pct")), css("--s2"))] } });
  // margin bridge in points
  const pts = k => (A[k] / A.net_revenue - B[k] / B.net_revenue);
  const items = [["Parts COGS", ["parts_cogs"]], [["Tech", "labor"], ["technician_labor"]], ["Warranty", ["warranty_net", "inventory_loss", "sublet_cogs"]], [["Shop &", "HQ payroll"], ["shop_payroll", "hq_payroll"]],
    [["Rent &", "overhead"], ["rent", "overhead", "maintenance"]], [["Mktg &", "fees"], ["marketing", "merchant_fees"]]];
  let run = B.ebitda_pct; const labels = ["FY2025"], data = [[0, run]], cols = [css("--muted")];
  items.forEach(([n, ks]) => { const v = -sum(ks.map(pts)); labels.push(n); data.push([run, run + v]); cols.push(v >= 0 ? css("--good") : css("--crit")); run += v; });
  labels.push("FY2026"); data.push([0, A.ebitda_pct]); cols.push(css("--muted"));
  mkChart($("#chMarginBr"), { _fmt: "pct", _label: "EBITDA margin bridge", type: "bar", data: { labels, datasets: [{ label: "Margin", data, backgroundColor: cols, borderRadius: 4, borderSkipped: false, maxBarThickness: 30 }] },
    options: { interaction: { mode: "nearest", intersect: true }, plugins: { tooltip: { callbacks: { label: c => { const [a, b] = c.raw, i = c.dataIndex; return i === 0 || i === labels.length - 1 ? " " + fmtPct(b) : " " + ((b - a) >= 0 ? "+" : "") + ((b - a) * 100).toFixed(2) + " pts"; } } } },
      scales: { x: { ticks: { autoSkip: false, font: { size: 10 } } }, y: { min: .3 } } } });
  const own = {}; DS.owner_distributions.rows.forEach(r => own[r.date.slice(0, 7)] = (own[r.date.slice(0, 7)] || 0) + r.amount_usd);
  mkChart($("#chBank"), { _label: "Bank and distributions", data: { labels: lab, datasets: [line("Reserve", per.map(() => M.meta.cash_floor), css("--crit"), { borderDash: [5, 4], borderWidth: 1.5 }),
    line("Bank cash", K.map(r => r.bank), css("--s1"), { pointRadius: 2 }), bar("Owner distributions", per.map(p => own[p] || null), alpha(css("--s2"), .7))] } });
  const rows = [...LOCS, "HQ", "COMPANY"].map(e => ({ e, a: agg(e, PER.fy26()), b: agg(e, PER.fy25()), _cls: e === "COMPANY" ? "total" : "" }));
  table($("#tOv"), [
    { h: "Location", cls: "l", f: r => locCell(r.e) },
    { h: "Net revenue", f: r => fmt$(r.a.net_revenue, true) }, { h: "YoY", f: r => r.b.net_revenue ? chg(r.a.net_revenue / r.b.net_revenue - 1) : "—" },
    { h: "vs budget", f: r => r.a.budget_net_revenue ? chg(r.a.vs_bud) : "—" }, { h: "Contribution", f: r => r.a.net_revenue ? fmtPct(r.a.contrib_pct) : "—" },
    { h: "EBITDA", f: r => fmt$(r.a.ebitda, true) },
    { h: "Margin", f: r => r.a.net_revenue ? el("span", { class: "chip " + (r.a.ebitda_pct < .3 ? "unf" : r.a.ebitda_pct < .38 ? "est" : "neu"), text: fmtPct(r.a.ebitda_pct) }) : "—" },
    { h: "Margin chg", f: r => r.b.net_revenue ? chg(r.a.ebitda_pct - r.b.ebitda_pct, 1, "pts") : "—" },
    { h: "Customer ROs", f: r => r.a.customer_ros ? fmtN(r.a.customer_ros) : "—" }, { h: "ARO", f: r => r.a.aro ? "$" + r.a.aro.toFixed(0) : "—" },
    { h: "Utilization", f: r => r.a.util ? fmtPct(r.a.util) : "—" }, { h: "Comebacks", f: r => r.a.customer_ros ? fmtN(r.a.comebacks) : "—" }], rows);
  const box = $("#ovStories"); box.innerHTML = "";
  DS.stories.rows.forEach(s => box.append(el("div", { class: "story" }, el("b", { text: s.id + " · " }), s.story)));
}

// ---------------------------------------------------------------- MONTH
const mon = { p: null };
function renderMonth() {
  const all = P(); if (!mon.p) mon.p = all[all.length - 1];
  const s = $("#monSel"); if (!s.options.length) { [...all].reverse().forEach(p => s.append(el("option", { value: p, text: mLabel(p).replace(" ", " 20") }))); }
  s.value = mon.p; const p = mon.p, ly = yago(p), hasLy = all.includes(ly);
  $("#monLabel").textContent = hasLy ? "vs budget and " + mLabel(ly) : "vs budget (no prior-year month in the data)";
  $("#monSub").textContent = mLabel(p) + " · USD";
  const C = agg("COMPANY", [p]), L = hasLy ? agg("COMPANY", [ly]) : null;
  tiles($("#monTiles"), [
    ["Net revenue", fmt$(C.net_revenue, true), [el("span", { class: C.vs_bud >= 0 ? "up" : "down", text: (C.vs_bud >= 0 ? "+" : "") + fmtPct(C.vs_bud) + " vs budget" }), ...(L ? [" · ", chg(C.net_revenue / L.net_revenue - 1), " YoY"] : [])]],
    ["EBITDA", fmt$(C.ebitda, true), ["Budget " + fmt$(C.budget_ebitda, true) + " · ", varSpan(C.ebitda - C.budget_ebitda, 1, true)]],
    ["EBITDA margin", fmtPct(C.ebitda_pct), L ? [chg(C.ebitda_pct - L.ebitda_pct, 1, "pts"), " YoY"] : ""],
    ["Customer ROs", fmtN(C.customer_ros), ["ARO $" + C.aro.toFixed(0) + (L ? " · " : ""), ...(L ? [chg(C.aro / L.aro - 1)] : [])]],
    ["Utilization", fmtPct(C.util), ["efficiency " + fmtPct(C.eff, 0)]],
    ["Comebacks", fmtN(C.comebacks), [fmtPct(C.cb_rate, 1) + " of customer ROs"]]]);
  const rows = [...LOCS, "HQ", "COMPANY"].map(e => { const a = agg(e, [p]), b = hasLy ? agg(e, [ly]) : null; return { e, a, b, _cls: e === "COMPANY" ? "total" : "" }; });
  table($("#tMon"), [
    { h: "Location", cls: "l", f: r => locCell(r.e) },
    { h: "Net revenue", f: r => fmt$(r.a.net_revenue) }, { h: "Budget", f: r => fmt$(r.a.budget_net_revenue) }, { h: "vs budget", f: r => r.a.budget_net_revenue ? chg(r.a.vs_bud) : "—" },
    { h: "YoY", f: r => r.b && r.b.net_revenue ? chg(r.a.net_revenue / r.b.net_revenue - 1) : "—" },
    { h: "EBITDA", f: r => fmt$(r.a.ebitda) }, { h: "Budget EBITDA", f: r => fmt$(r.a.budget_ebitda) },
    { h: "ROs", f: r => r.a.customer_ros ? fmtN(r.a.customer_ros) : "—" }, { h: "ARO", f: r => r.a.aro ? "$" + r.a.aro.toFixed(0) : "—" },
    { h: "Utilization", f: r => r.a.util ? fmtPct(r.a.util) : "—" }, { h: "Comebacks", f: r => r.a.customer_ros ? fmtN(r.a.comebacks) : "—" }], rows);
  mkChart($("#chMon"), { _label: "Net revenue by shop", data: { labels: LOCS.map(e => NM[e]), datasets: [bar("Actual", LOCS.map(e => kv(e, p, "net_revenue")), css("--s1")),
    bar("Budget", LOCS.map(e => kv(e, p, "budget_net_revenue")), css("--muted")), ...(hasLy ? [bar("Same month last year", LOCS.map(e => kv(e, ly, "net_revenue")), css("--s4"))] : [])] } });
  bridgeChart($("#chMonBr"), pnlFor([p]), pnlFor([p], "COMPANY", "budget"));
}

// ---------------------------------------------------------------- BVA
const bva = { scope: "fy", sel: "FY2026", ent: "COMPANY" };
function bvaPeriods() {
  const all = P();
  if (bva.scope === "month") return { periods: [bva.sel], label: mLabel(bva.sel) };
  if (bva.scope === "quarter") { const i = all.indexOf(bva.sel); const ps = all.slice(i, i + 3); return { periods: ps, label: `Fiscal quarter ${mLabel(ps[0])} – ${mLabel(ps[2])}` }; }
  const ps = bva.sel === "FY2025" ? all.slice(0, 12) : all.slice(12); return { periods: ps, label: `${bva.sel} (${mLabel(ps[0])} – ${mLabel(ps[11])})` };
}
function fillBvaSel() {
  const s = $("#bvaSel"); s.innerHTML = ""; const all = P();
  const opts = bva.scope === "month" ? [...all].reverse().map(p => [p, mLabel(p)]) : bva.scope === "quarter" ? [0, 3, 6, 9, 12, 15, 18, 21].reverse().map(i => [all[i], `Q${(i % 12) / 3 + 1} ${i < 12 ? "FY2025" : "FY2026"} · ${mLabel(all[i])}–${mLabel(all[i + 2])}`]) : [["FY2026", "FY2026"], ["FY2025", "FY2025"]];
  opts.forEach(([v, t]) => s.append(el("option", { value: v, text: t }))); if (!opts.some(o => o[0] === bva.sel)) bva.sel = opts[0][0]; s.value = bva.sel;
}
function renderBva() {
  fillBvaSel(); $("#bvaEnt").value = bva.ent;
  const { periods, label } = bvaPeriods(), e = bva.ent; $("#bvaLabel").textContent = label; $("#bvaSub").textContent = (e === "COMPANY" ? "Company" : NM[e]) + " · " + label + " · USD";
  const A = pnlFor(periods, e), B = pnlFor(periods, e, "budget"), N = ACC();
  tiles($("#bvaTiles"), [["Net revenue", 1], ["Contribution", 1], ["EBITDA", 1], ["Net income", 1]].map(([k, sg]) => { const a = A[k], b = B[k], v = a - b;
    return [k, fmt$(a, true), ["Budget " + fmt$(b, true) + " · ", el("span", { class: Math.abs(v) < .5 ? "flat" : v * sg > 0 ? "up" : "down", text: sgn$(v).replace(/\.\d+$/, "") + (b ? " (" + (v / Math.abs(b) * 100).toFixed(1) + "%)" : "") })]]; }));
  const nr = A["Net revenue"], rows = [];
  const mk = (name, a, b, sign, cls) => ({ name, a, b, v: a - b, fav: (a - b) * sign, vp: b ? (a - b) / Math.abs(b) : null, _cls: cls });
  const accs = Object.keys(N).sort();
  for (const [grp, title, sign, subt] of GROUPS) {
    const ga = accs.filter(a => N[a].group === grp && ((A[a] || 0) || (B[a] || 0)));
    if (ga.length) { rows.push({ name: title, _cls: "sec" }); ga.forEach(a => rows.push(mk(N[a].line, A[a] || 0, B[a] || 0, sign, ""))); }
    if (subt) rows.push(mk(subt, A[subt], B[subt], 1, subt === "Net income" ? "total" : "sub"));
  }
  const tb = table($("#tPnl"), [{ h: "Line", k: "name" }, { h: "Actual", f: r => r._cls === "sec" ? "" : fmt$(r.a) }, { h: "Budget", f: r => r._cls === "sec" ? "" : fmt$(r.b) },
    { h: "Var $", f: r => r._cls === "sec" ? "" : el("span", { class: Math.abs(r.v) < .5 ? "flat" : r.fav > 0 ? "up" : "down", text: sgn$(r.v) }) },
    { h: "Var %", f: r => r._cls === "sec" || r.vp == null ? "" : (r.vp >= 0 ? "+" : "") + (r.vp * 100).toFixed(1) + "%" }, { h: "% rev", f: r => r._cls === "sec" || !nr ? "" : fmtPct(r.a / nr) },
    { h: "", f: r => r._cls === "sec" || Math.abs(r.v) < .5 ? "" : el("span", { class: "chip " + (r.fav > 0 ? "fav" : "unf"), text: r.fav > 0 ? "Fav" : "Unfav" }) }], rows);
  [...tb.children].forEach((tr, i) => { const r = rows[i]; if (r._cls === "sec") { tr.firstChild.colSpan = 7; while (tr.children.length > 1) tr.lastChild.remove(); } else if (!r._cls) tr.firstChild.classList.add("ind"); });
  bridgeChart($("#chBridge"), A, B);
  const all = P();
  for (const [id, k, col] of [["#chBvaRev", "Net revenue", "--s1"], ["#chBvaPt", "EBITDA", "--s3"]]) {
    const c = css(col);
    mkChart($(id), { _label: k, data: { labels: all.map(mLabel), datasets: [line("Budget", all.map(p => pnlFor([p], e, "budget")[k]), css("--ink-2"), { borderDash: [5, 4], borderWidth: 1.5, order: 0 }),
      bar("Actual", all.map(p => pnlFor([p], e)[k]), all.map(p => periods.includes(p) ? c : alpha(c, .35)), { order: 1 })] } });
  }
}

// ---------------------------------------------------------------- SHOPS
const sh = { period: "fy26" };
function renderShops() {
  const ps = PER[sh.period](), prev = sh.period === "fy26" ? PER.fy25() : sh.period === "l3" ? ps.map(yago) : null;
  $("#shLabel").textContent = PNAME[sh.period] + (prev ? " · change vs " + (sh.period === "fy26" ? "FY2025" : "same months last year") : "");
  $("#shSub").textContent = PNAME[sh.period] + " · before HQ costs";
  const rows = [...LOCS, "COMPANY"].map(e => ({ e, a: agg(e, ps), b: prev ? agg(e, prev) : null, _cls: e === "COMPANY" ? "total" : "" }));
  table($("#tSh"), [
    { h: "Shop", cls: "l", f: r => r.e === "COMPANY" ? "Company (incl. HQ)" : locCell(r.e) },
    { h: "Net revenue", f: r => fmt$(r.a.net_revenue) }, { h: "Change", f: r => r.b ? chg(r.a.net_revenue / r.b.net_revenue - 1) : "—" },
    { h: "vs budget", f: r => chg(r.a.vs_bud) }, { h: "Tech labor", f: r => fmtPct(r.a.lab_pct) }, { h: "Parts margin", f: r => fmtPct(r.a.parts_margin) },
    { h: "Contribution", f: r => fmtPct(r.a.contrib_pct) }, { h: "EBITDA", f: r => fmt$(r.a.ebitda) },
    { h: "Margin", f: r => el("span", { class: "chip " + (r.a.ebitda_pct < .3 ? "unf" : r.a.ebitda_pct < .38 ? "est" : "neu"), text: fmtPct(r.a.ebitda_pct) }) },
    { h: "Margin chg", f: r => r.b ? chg(r.a.ebitda_pct - r.b.ebitda_pct, 1, "pts") : "—" },
    { h: "ROs", f: r => fmtN(r.a.customer_ros) }, { h: "ARO", f: r => "$" + r.a.aro.toFixed(0) }, { h: "Efficiency", f: r => fmtPct(r.a.eff, 0) }, { h: "Utilization", f: r => fmtPct(r.a.util) },
    { h: "Comebacks", f: r => fmtN(r.a.comebacks) }], rows);
  const per = P(), lab = per.map(mLabel);
  mkChart($("#chShM"), { _fmt: "pct", _label: "EBITDA margin", data: { labels: lab, datasets: LOCS.map(e => line(NM[e], per.map(p => ratio(e, p, "ebitda", "net_revenue")), css(LCOL[e]))) } });
  mkChart($("#chShA"), { _fmt: "rate", _label: "ARO", data: { labels: lab, datasets: LOCS.map(e => line(NM[e], per.map(p => kv(e, p, "aro")), css(LCOL[e]))) } });
  const set = new Set(ps), mb = {};
  const F = ["ro_cohort_margin", "concessions", "idle_pto_labor", "warranty_labor", "labor_timing", "warranty_parts", "supplier_recoveries", "stock_writeoffs", "gl_contribution", "difference"];
  for (const r of DS.margin_bridge_monthly.rows) if (set.has(r.period) && r.entity !== "HQ") { const o = mb[r.entity] ||= { e: r.entity }; F.forEach(k => o[k] = (o[k] || 0) + r[k]); }
  $("#mbSub").textContent = PNAME[sh.period] + " · delivered-RO margin (allocated technician labor) to ledger contribution · negative = reduces contribution · difference must be 0";
  table($("#tMb"), [{ h: "Entity", cls: "l", f: r => locCell(r.e) }, { h: "RO cohort margin", f: r => fmt$(r.ro_cohort_margin) }, { h: "Concessions", f: r => fmt$(r.concessions) },
    { h: "Idle / PTO labor", f: r => fmt$(r.idle_pto_labor) }, { h: "Warranty labor", f: r => fmt$(r.warranty_labor) }, { h: "Warranty parts", f: r => fmt$(r.warranty_parts) },
    { h: "Supplier recoveries", f: r => fmt$(r.supplier_recoveries) }, { h: "Labor timing", f: r => fmt$(r.labor_timing) }, { h: "Stock write-offs", f: r => fmt$(r.stock_writeoffs) },
    { h: "GL contribution", f: r => el("b", { text: fmt$(r.gl_contribution) }) }, { h: "Difference", f: r => fmt$(r.difference) }],
    [...LOCS, "COMPANY"].map(e => Object.assign(mb[e] || { e }, { _cls: e === "COMPANY" ? "total" : "" })));
}

// ---------------------------------------------------------------- SERVICE MIX
const mx = { ent: "ALL" };
function renderMix() {
  const g = {}; const f1 = new Set(PER.fy25()), f2 = new Set(PER.fy26());
  for (const r of DS.service_mix_monthly.rows) { if (mx.ent !== "ALL" && r.location_id !== mx.ent) continue;
    const o = g[r.service_id] ||= { id: r.service_id, name: r.service, s1: 0, s2: 0, n1: 0, n2: 0, b2: 0, c2: 0, l2: 0, p2: 0, f2: 0 };
    if (f1.has(r.period)) { o.s1 += r.net_sales_usd; o.n1 += r.delivered_ros; } else if (f2.has(r.period)) { o.s2 += r.net_sales_usd; o.n2 += r.delivered_ros; o.b2 += r.book_hours; o.c2 += r.clock_hours; o.l2 += r.labor_sales_usd; o.p2 += r.parts_sales_usd; o.f2 += r.fleet_ros; } }
  const items = Object.values(g).sort((a, b) => b.s2 - a.s2);
  mkChart($("#chMx"), { _label: "Net sales by service", data: { labels: items.map(i => i.name), datasets: [bar("FY2026", items.map(i => i.s2), css("--s1")), bar("FY2025", items.map(i => i.s1), alpha(css("--s1"), .35))] }, options: { indexAxis: "y" } });
  const per = P(), e = mx.ent === "ALL" ? "COMPANY" : mx.ent;
  mkChart($("#chMxF"), { _stacked: true, _fmt: "number", _label: "Customer ROs", data: { labels: per.map(mLabel), datasets: [bar("Retail", per.map(p => kv(e, p, "customer_ros") - kv(e, p, "fleet_ros")), css("--s1"), { borderRadius: 0 }), bar("Fleet", per.map(p => kv(e, p, "fleet_ros")), css("--s4"))] } });
  const T = sum(items.map(i => i.s2));
  table($("#tMx"), [{ h: "Service", cls: "l", f: i => el("span", {}, el("span", { class: "mono muted", text: i.id + " " }), i.name) },
    { h: "Net sales FY26", f: i => fmt$(i.s2) }, { h: "Share", f: i => fmtPct(i.s2 / T) }, { h: "Sales chg", f: i => i.s1 ? chg(i.s2 / i.s1 - 1) : "new" },
    { h: "ROs FY26", f: i => fmtN(i.n2) }, { h: "ROs chg", f: i => i.n1 ? chg(i.n2 / i.n1 - 1) : "—" }, { h: "ARO FY26", f: i => i.n2 ? "$" + (i.s2 / i.n2).toFixed(0) : "—" },
    { h: "ARO chg", f: i => i.n1 && i.n2 ? chg((i.s2 / i.n2) / (i.s1 / i.n1) - 1) : "—" }, { h: "Parts share", f: i => fmtPct(i.p2 / i.s2) },
    { h: "Book h", f: i => fmtN(i.b2) }, { h: "Clock h", f: i => fmtN(i.c2) }, { h: "Efficiency", f: i => i.c2 ? fmtPct(i.b2 / i.c2, 0) : "—" }, { h: "Fleet ROs", f: i => fmtN(i.f2) }], items);
}

// ---------------------------------------------------------------- TECHNICIANS
function renderTech() {
  const A = agg("COMPANY", PER.fy26()), B = agg("COMPANY", PER.fy25()); const per = P(), lab = per.map(mLabel), last = KP("COMPANY").slice(-1)[0];
  const idle = A.tech_available_hours - A.tech_worked_hours, elr = last.effective_labor_rate;
  tiles($("#tcTiles"), [["Utilization, FY2026", fmtPct(A.util), [chg(A.util - B.util, 1, "pts"), " vs FY2025"]],
    ["Efficiency, FY2026", fmtPct(A.eff, 0), [chg(A.eff - B.eff, 1, "pts"), " · billed / clock"]],
    ["Billed hours, FY2026", fmtN(A.book_hours), [chg(A.book_hours / B.book_hours - 1), " vs FY2025"]],
    ["Idle available hours", fmtN(idle), ["FY2026 · " + fmtPct(idle / A.tech_available_hours) + " of available"]],
    ["Technicians, Oct 2026", String(last.technicians), ["18 bays · bay productive " + fmtPct(last.bay_productive_pct / 100)]],
    ["Effective labor rate, Oct", "$" + elr.toFixed(0), ["per billed hour"]]]);
  mkChart($("#chTcU"), { _fmt: "pct", _label: "Utilization", data: { labels: lab, datasets: LOCS.map(e => line(NM[e], per.map(p => pct100(e, p, "utilization_pct")), css(LCOL[e]))) } });
  mkChart($("#chTcE"), { _fmt: "pct", _label: "Efficiency", data: { labels: lab, datasets: LOCS.map(e => line(NM[e], per.map(p => pct100(e, p, "efficiency_pct")), css(LCOL[e]))) } });
  mkChart($("#chTcH"), { _fmt: "number", _label: "Hours", data: { labels: lab, datasets: [line("Paid", per.map(p => kv("COMPANY", p, "tech_paid_hours")), css("--s7")), line("Available", per.map(p => kv("COMPANY", p, "tech_available_hours")), css("--s2")),
    line("Worked", per.map(p => kv("COMPANY", p, "tech_worked_hours")), css("--s1")), line("Billed (book)", per.map(p => kv("COMPANY", p, "book_hours")), css("--s3"))] } });
  mkChart($("#chTcR"), { _fmt: "rate", _label: "Effective labor rate", data: { labels: lab, datasets: LOCS.map(e => line(NM[e], per.map(p => kv(e, p, "effective_labor_rate")), css(LCOL[e]))) } });
  const rows = [...LOCS, "COMPANY"].map(e => ({ e, a: agg(e, PER.fy26()), b: agg(e, PER.fy25()), last: KP(e).slice(-1)[0], _cls: e === "COMPANY" ? "total" : "" }));
  table($("#tTc"), [{ h: "Shop", cls: "l", f: r => locCell(r.e) }, { h: "Paid h", f: r => fmtN(r.a.tech_paid_hours) }, { h: "Available h", f: r => fmtN(r.a.tech_available_hours) },
    { h: "Worked h", f: r => fmtN(r.a.tech_worked_hours) }, { h: "Utilization", f: r => fmtPct(r.a.util) }, { h: "Chg", f: r => chg(r.a.util - r.b.util, 1, "pts") },
    { h: "Billed h", f: r => fmtN(r.a.book_hours) }, { h: "Efficiency", f: r => fmtPct(r.a.eff, 0) }, { h: "Chg", f: r => chg(r.a.eff - r.b.eff, 1, "pts") },
    { h: "Tech labor / revenue", f: r => fmtPct(r.a.lab_pct) }, { h: "Technicians (Oct)", f: r => String(r.last.technicians) }, { h: "Warranty clock h", f: r => fmtN(r.a.warranty_clock_hours) }], rows);
}

// ---------------------------------------------------------------- PARTS & WARRANTY
function renderParts() {
  const A = agg("COMPANY", PER.fy26()), B = agg("COMPANY", PER.fy25()); const per = P(), lab = per.map(mLabel);
  const oj = KP("LOC-03"), pre = sum(oj.filter(r => r.period < "2026-05").map(r => r.comebacks)), post = sum(oj.filter(r => r.period >= "2026-05").map(r => r.comebacks));
  tiles($("#ptTiles"), [["Parts margin, FY2026", fmtPct(A.parts_margin), [chg(A.parts_margin - B.parts_margin, 1, "pts"), " vs FY2025"]],
    ["Parts sales, FY2026", fmt$(A.parts_sales, true), [chg(A.parts_sales / B.parts_sales - 1), " · COGS ", chg(A.parts_cogs / B.parts_cogs - 1, -1)]],
    ["Warranty cost (net), FY2026", fmt$(A.warranty_net, true), ["FY2025 " + fmt$(B.warranty_net, true)]],
    ["Comebacks, FY2026", fmtN(A.comebacks), [fmtPct(A.cb_rate, 2) + " of customer ROs · FY25 " + fmtN(B.comebacks)]],
    ["Oak Junction comebacks", (post / 6).toFixed(1) + "/mo", ["May–Oct 2026 vs " + (pre / 18).toFixed(1) + "/mo before"]]]);
  mkChart($("#chPtM"), { _fmt: "pct", _label: "Parts margin", data: { labels: lab, datasets: LOCS.map(e => line(NM[e], per.map(p => pct100(e, p, "parts_margin_pct")), css(LCOL[e]))) } });
  mkChart($("#chPtC"), { _stacked: true, _fmt: "number", _label: "Comebacks", data: { labels: lab, datasets: LOCS.map(e => bar(NM[e], per.map(p => kv(e, p, "comebacks")), css(LCOL[e]), { borderRadius: 0 })) } });
  const rows = [...LOCS, "COMPANY"].map(e => ({ e, a: agg(e, PER.fy26()), b: agg(e, PER.fy25()), _cls: e === "COMPANY" ? "total" : "" }));
  table($("#tPt"), [{ h: "Shop", cls: "l", f: r => locCell(r.e) }, { h: "Parts sales", f: r => fmt$(r.a.parts_sales) }, { h: "Parts margin", f: r => fmtPct(r.a.parts_margin) },
    { h: "Chg", f: r => chg(r.a.parts_margin - r.b.parts_margin, 1, "pts") }, { h: "Warranty net", f: r => fmt$(r.a.warranty_net) }, { h: "FY25", f: r => fmt$(r.b.warranty_net) },
    { h: "Comebacks", f: r => fmtN(r.a.comebacks) }, { h: "FY25", f: r => fmtN(r.b.comebacks) }, { h: "Rate", f: r => fmtPct(r.a.cb_rate, 2) }], rows);
  const f2 = new Set(PER.fy26()), rr = {};
  for (const r of DS.comebacks_monthly.rows) if (f2.has(r.period)) { const o = rr[r.reason] ||= { reason: r.reason, "LOC-01": 0, "LOC-02": 0, "LOC-03": 0, t: 0, h: 0, c: 0 }; o[r.location_id] += r.comebacks; o.t += r.comebacks; o.h += r.corrective_hours; o.c += r.corrective_parts_cost_usd; }
  table($("#tPtR"), [{ h: "Reason", cls: "l", f: r => r.reason.replace(/_/g, " ") }, ...LOCS.map(e => ({ h: NM[e], f: r => fmtN(r[e]) })), { h: "Total", f: r => fmtN(r.t) }, { h: "Hours", f: r => fmtN(r.h) }, { h: "Parts", f: r => fmt$(r.c) }],
    Object.values(rr).sort((a, b) => b.t - a.t));
}

// ---------------------------------------------------------------- MARKETING
function renderMkt() {
  const A = agg("COMPANY", PER.fy26()), B = agg("COMPANY", PER.fy25()); const per = P(), lab = per.map(mLabel);
  tiles($("#mkTiles"), [["Ad spend, FY2026", fmt$(A.ad_spend, true), [chg(A.ad_spend / B.ad_spend - 1, -1), " · " + fmtPct(A.ad_spend / A.net_revenue, 2) + " of revenue"]],
    ["Leads, FY2026", fmtN(A.leads), [chg(A.leads / B.leads - 1), " vs FY2025"]], ["Booking rate", fmtPct(A.book_rate), [chg(A.book_rate - B.book_rate, 1, "pts"), " vs FY2025"]],
    ["Cost per booked lead", "$" + A.cpl.toFixed(2), ["FY2025 $" + B.cpl.toFixed(2)]]]);
  mkChart($("#chMkS"), { _stacked: true, _label: "Ad spend", data: { labels: lab, datasets: LOCS.map(e => bar(NM[e], per.map(p => kv(e, p, "ad_spend")), css(LCOL[e]), { borderRadius: 0 })) } });
  mkChart($("#chMkL"), { _stacked: true, _fmt: "number", _label: "Leads", data: { labels: lab, datasets: [bar("Booked leads", per.map(p => kv("COMPANY", p, "booked_leads")), css("--s1"), { borderRadius: 0 }), bar("Leads not booked", per.map(p => kv("COMPANY", p, "leads") - kv("COMPANY", p, "booked_leads")), css("--s2"))] } });
  const f2 = new Set(PER.fy26()), g = {};
  for (const r of DS.marketing_monthly.rows) if (f2.has(r.period)) { const o = g[r.location_id + r.channel] ||= { l: r.location_id, ch: r.channel, sp: 0, cl: 0, cv: 0, cvv: 0, ld: 0, bk: 0 };
    o.sp += r.spend_usd; o.cl += r.clicks; o.cv += r.claimed_conversions; o.cvv += r.claimed_value_usd; o.ld += r.leads; o.bk += r.booked_leads; }
  table($("#tMk"), [{ h: "Shop", cls: "l", f: r => NM[r.l] }, { h: "Channel", cls: "l", f: r => r.ch.replace(/_/g, " ") }, { h: "Spend", f: r => r.sp ? fmt$(r.sp) : "—" }, { h: "Clicks", f: r => r.cl ? fmtN(r.cl) : "—" },
    { h: "Claimed conv.", f: r => r.cv ? fmtN(r.cv) : "—" }, { h: "Claimed value", f: r => r.cvv ? fmt$(r.cvv) : "—" }, { h: "Leads", f: r => fmtN(r.ld) }, { h: "Booked", f: r => fmtN(r.bk) },
    { h: "Booking rate", f: r => r.ld ? fmtPct(r.bk / r.ld) : "—" }, { h: "Cost / booked", f: r => r.sp && r.bk ? "$" + (r.sp / r.bk).toFixed(2) : "—" }], Object.values(g).sort((a, b) => a.l.localeCompare(b.l) || b.sp - a.sp));
}

// ---------------------------------------------------------------- AR / AP / RO
const ro = { q: "", loc: "ALL" };
function renderWc() {
  const K = KP("COMPANY"), last = K[K.length - 1], per = P(), lab = per.map(mLabel), AR = DS.open_ar.rows, AP = DS.open_ap.rows;
  const fleetAr = sum(AR.filter(r => r.customer !== "Retail").map(r => r.open_usd)), over = sum(AR.filter(r => r.days_past_due > 0).map(r => r.open_usd));
  const rev3 = sum(K.slice(-3).map(r => r.net_revenue)), dso = last.ar / (rev3 / 92);
  tiles($("#wcTiles"), [["Open AR, 31 Oct", fmt$(last.ar, true), [AR.length + " invoices · fleet " + fmtPct(fleetAr / last.ar, 0)]], ["Past due", fmt$(over, true), [fmtPct(over / last.ar, 0) + " of AR"]],
    ["DSO (3-month)", dso.toFixed(0) + " days", ["AR / avg daily revenue Aug–Oct"]], ["Open AP, 31 Oct", fmt$(last.ap, true), [AP.length + " bills"]],
    ["Inventory + WIP", fmt$(last.inventory + last.wip, true), ["parts at FIFO cost"]], ["Payroll payable", fmt$(last.payroll_payable, true), ["earned Oct, funded 4 Nov"]]]);
  mkChart($("#chWc"), { _label: "Working capital", data: { labels: lab, datasets: [line("Receivables", K.map(r => r.ar), css("--s1")), line("Payables", K.map(r => r.ap), css("--s2")), line("Inventory", K.map(r => r.inventory), css("--s4")), line("Payroll payable", K.map(r => r.payroll_payable), css("--s7"))] } });
  const B = ["Current", "1–30", "31–60", "61–90", "90+"];
  mkChart($("#chAge"), { _stacked: true, _label: "AR aging", data: { labels: B, datasets: [bar("Retail", B.map(b => sum(AR.filter(r => r.bucket === b && r.customer === "Retail").map(r => r.open_usd))), css("--s1"), { borderRadius: 0 }),
    bar("Fleet", B.map(b => sum(AR.filter(r => r.bucket === b && r.customer !== "Retail").map(r => r.open_usd))), css("--s4"))] } });
  const gc = {}; AR.forEach(r => { const o = gc[r.customer] ||= { c: r.customer, n: 0, a: 0, pd: 0, mx: 0 }; o.n++; o.a += r.open_usd; if (r.days_past_due > 0) o.pd += r.open_usd; o.mx = Math.max(o.mx, r.days_past_due); });
  table($("#tAr"), [{ h: "Customer", cls: "l mono", k: "c" }, { h: "Invoices", f: r => fmtN(r.n) }, { h: "Open", f: r => fmt$(r.a) }, { h: "Past due", f: r => fmt$(r.pd) }, { h: "Max days late", f: r => r.mx > 0 ? String(r.mx) : "—" }],
    Object.values(gc).sort((a, b) => b.a - a.a));
  const gv = {}; AP.forEach(r => { const o = gv[r.vendor_id] ||= { v: r.vendor_id, n: 0, a: 0, d: "9999" }; o.n++; o.a += r.open_usd; if (r.expected_payment_date < o.d) o.d = r.expected_payment_date; });
  table($("#tAp"), [{ h: "Vendor", cls: "l mono", k: "v" }, { h: "Bills", f: r => fmtN(r.n) }, { h: "Open", f: r => fmt$(r.a) }, { h: "First payment", k: "d", cls: "l" }], Object.values(gv).sort((a, b) => b.a - a.a));
  renderRo();
}
function renderRo() {
  const q = ro.q.toLowerCase(), R = DS.ro_recent.rows.filter(r => (ro.loc === "ALL" || r.location_id === ro.loc) && (!q || [r.ro_id, r.invoice_id, r.service, r.technician, r.fleet].join(" ").toLowerCase().includes(q)));
  $("#roSub").textContent = `${fmtN(R.length)} repair orders · ${fmt$(sum(R.map(r => r.net_usd)))} net sales · showing up to 300 · warranty ROs carry no invoice`;
  table($("#tRo"), [{ h: "RO", k: "ro_id", cls: "l mono" }, { h: "Shop", f: r => NM[r.location_id], cls: "l" }, { h: "Opened", k: "opened", cls: "l" }, { h: "Delivered", k: "delivered", cls: "l" },
    { h: "Service", k: "service", cls: "l" }, { h: "Type", f: r => el("span", { class: "chip " + (r.warranty ? "unf" : r.fleet ? "est" : "neu"), text: r.warranty ? "Warranty" : r.fleet || "Retail" }) },
    { h: "Invoice", f: r => r.invoice_id || "—", cls: "l mono" }, { h: "Net", f: r => fmt$(r.net_usd) }, { h: "Labor", f: r => fmt$(r.labor_usd) }, { h: "Parts", f: r => fmt$(r.parts_usd) },
    { h: "Book h", f: r => r.book_hours.toFixed(2) }, { h: "Clock h", f: r => r.clock_hours.toFixed(2) }, { h: "Tech", k: "technician", cls: "l mono" }], R.slice(0, 300));
}

// ---------------------------------------------------------------- 13-WEEK CASH
const SCN = () => { const o = {}; for (const [k, v] of Object.entries(M.meta.scenarios)) o[k] = { sal: v.sales, ven: v.vendor, del: v.fleet_delay_weeks }; return o; };
const sc = { name: "base", sal: 100, ven: 100, del: 0, floor: 450000 };
const WEEK0 = Date.UTC(2026, 10, 1), DAY = 864e5;
const wkDate = (w, add = 0) => { const d = new Date(WEEK0 + ((w - 1) * 7 + add) * DAY); return MN[d.getUTCMonth()] + " " + d.getUTCDate(); };
const CATS = [["ar", "Open AR collections", 1], ["settle", "Card & undeposited settlement", 1], ["sales", "New sales receipts", 1], ["vendors", "Suppliers & vendors", -1], ["payroll", "Payroll", -1], ["tax", "Sales tax", -1], ["debt", "Debt service", -1]];
const catOf = t => t === "Open AR collection" ? "ar" : /Processor|Undeposited/.test(t) ? "settle" : /AP|PO|Contracts/.test(t) ? "vendors" : /Payroll|payroll/.test(t) ? "payroll" : /tax/i.test(t) ? "tax" : "debt";
let cashModel = null;
function computeCash(s = sc) {
  const D = M.meta.cash_drivers, W = [...Array(13).keys()].map(i => i + 1), flows = {}, items = {};
  const fleetInv = new Set(DS.open_ar.rows.filter(r => r.customer !== "Retail").map(r => r.invoice_id));
  W.forEach(w => { flows[w] = { rr: {}, known: 0, drv: 0 }; CATS.forEach(([k]) => flows[w][k] = 0); });
  const put = (w, k, r, amt) => { if (w > 13) return; flows[w][k] += amt; (items[w + k] ||= []).push(Object.assign({}, r, { amt })); if (r.certainty === "known") flows[w].known += amt; else flows[w].drv += amt; };
  for (const r of DS.cash_schedule_13w.rows) { const k = catOf(r.commitment_type); let w = r.week_index; if (k === "ar" && fleetInv.has(r.overlap_key)) w += s.del; put(w, k, r, r.amount_usd); }
  const lagW = Math.ceil(D.fleet_collection_lag_days / 7) + s.del;
  W.forEach(w => {
    put(w, "sales", { id: "DRV-RETAIL-W" + w, expected_cash_date: "", location_id: "ALL", commitment_type: "New retail sales (card/cash/ACH)", source: `trailing 8-week retail invoices × ${s.sal}%`, certainty: "driver" }, D.retail_receipts_weekly_usd * s.sal / 100);
    if (w - lagW >= 1) put(w, "sales", { id: "DRV-FLEET-W" + (w - lagW), expected_cash_date: "", location_id: "ALL", commitment_type: `Fleet invoices of week ${w - lagW}`, source: `fleet invoicing × ${s.sal}%, paid after ${lagW} weeks`, certainty: "driver" }, D.fleet_invoicing_weekly_usd * s.sal / 100);
    const rv = -D.supplier_vendor_payments_weekly_usd * s.ven / 100;
    if (rv < flows[w].vendors) { const extra = rv - flows[w].vendors; put(w, "vendors", { id: "DRV-VENDOR-W" + w, expected_cash_date: "", location_id: "ALL", commitment_type: "Purchases above known AP/PO/contracts", source: `trailing 8-week vendor payments × ${s.ven}%`, certainty: "driver" }, extra); }
  });
  let cash = M.meta.opening_cash; const closing = [], inflow = [], outflow = [];
  W.forEach(w => { const f = flows[w], i = f.ar + f.settle + f.sales, o = -(f.vendors + f.payroll + f.tax + f.debt); inflow.push(i); outflow.push(o); cash += i - o; closing.push(cash); });
  return { W, flows, items, closing, inflow, outflow, lab: W.map(w => wkDate(w)) };
}
function cashLow() { const c = computeCash(SCN().base); let i = 0; c.closing.forEach((v, j) => { if (v < c.closing[i]) i = j; }); return { v: c.closing[i], w: "week of " + c.lab[i] }; }
let drillSel = null;
function syncSliders() { $("#scSal").value = sc.sal; $("#scVen").value = sc.ven; $("#scDel").value = sc.del; $("#scSalV").textContent = sc.sal + "%"; $("#scVenV").textContent = sc.ven + "%"; $("#scDelV").textContent = sc.del + " wk";
  [...$("#scScen").children].forEach(b => b.setAttribute("aria-pressed", String(b.dataset.n === sc.name))); }
function renderCash() {
  syncSliders(); const c = cashModel = computeCash(), D = M.meta.cash_drivers;
  $("#cashIntro").textContent = `Opening bank ${fmt$(M.meta.opening_cash)} on 31 Oct 2026. Weeks run Sunday–Saturday from 1 Nov 2026 to 30 Jan 2027. Known items come from source documents; new sales (retail ${fmt$(D.retail_receipts_weekly_usd)}/wk, fleet ${fmt$(D.fleet_invoicing_weekly_usd)}/wk paid after ~${D.fleet_collection_lag_days} days), vendor run rate, future payroll and sales tax are driver-based.`;
  let lo = 0; c.closing.forEach((v, j) => { if (v < c.closing[lo]) lo = j; });
  const below = c.closing.filter(v => v < sc.floor).length, kn = sum(c.W.map(w => c.flows[w].known)), dv = sum(c.W.map(w => c.flows[w].drv));
  tiles($("#cashTiles"), [["Opening bank, 31 Oct", fmt$(M.meta.opening_cash, true), "plus " + fmt$(DS.cash_schedule_13w.rows.filter(r => r.commitment_type.match(/Processor|Undeposited/)).reduce((s, r) => s + r.amount_usd, 0), true) + " settling week 1"],
    ["Lowest week-end", fmt$(c.closing[lo], true), ["week of " + c.lab[lo] + " · ", el("span", { class: c.closing[lo] >= sc.floor ? "up" : "down", text: sgn$(c.closing[lo] - sc.floor).replace(/\.\d+/, "") + " vs reserve" })]],
    ["Closing, 30 Jan 2027", fmt$(c.closing[12], true), [chg(c.closing[12] / M.meta.opening_cash - 1), " vs opening"]],
    ["Weeks under reserve", String(below), ["reserve " + fmt$(sc.floor, true) + " (owner policy)"]],
    ["Distributable on 30 Jan", fmt$(Math.max(0, c.closing[12] - sc.floor), true), ["closing above reserve; no sweep assumed"]]], true);
  $("#cashChSub").textContent = "USD · dashed line is the " + fmt$(sc.floor, true) + " reserve";
  const imp = computeCash(SCN().improved).closing, st = computeCash(SCN().stress).closing;
  mkChart($("#chCash"), { _label: "Closing cash", data: { labels: c.lab, datasets: [line("Reserve", c.W.map(() => sc.floor), css("--crit"), { borderDash: [5, 4], borderWidth: 1.5 }),
    line("Improved", imp, alpha(css("--s3"), .8), { borderWidth: 1.5 }), line("Stress", st, alpha(css("--s2"), .8), { borderWidth: 1.5 }), line("Current scenario", c.closing, css("--s1"), { pointRadius: 3, borderWidth: 2.5 })] }, options: { scales: { y: { min: 0 } } } });
  const cats = CATS.map(([k, n]) => n), kv2 = CATS.map(([k]) => sum((c.W.flatMap(w => c.items[w + k] || [])).filter(r => r.certainty === "known").map(r => r.amt))), dv2 = CATS.map(([k]) => sum((c.W.flatMap(w => c.items[w + k] || [])).filter(r => r.certainty !== "known").map(r => r.amt)));
  mkChart($("#chFlows"), { _stacked: true, _label: "Known vs driver", data: { labels: ["AR", "Settlement", "New sales", "Vendors", "Payroll", "Sales tax", "Debt"], datasets: [bar("Known", kv2, css("--s1"), { borderRadius: 0 }), bar("Driver-based", dv2, css("--s4"))] }, options: { indexAxis: "y" } });
  const t = $("#tCash"); t.innerHTML = "";
  t.append(el("thead", {}, el("tr", {}, el("th", { text: "USD" }), c.W.map(w => el("th", { text: "W" + w + " · " + c.lab[w - 1] })), el("th", { text: "13 weeks" }))));
  const tb = el("tbody"); const row = (name, vals, cls, key) => { const tr = el("tr", cls ? { class: cls } : {}); tr.append(el("td", { text: name }));
    vals.forEach((v, i) => { const w = i + 1, td = el("td", { text: v == null ? "" : fmt$(v) }); if (key && v) { td.className = "click" + (drillSel === w + key ? " sel" : ""); td.onclick = () => { drillSel = w + key; renderCash(); }; }
      if (cls === "total" && v != null && v < sc.floor) td.className = "lowcash"; tr.append(td); });
    if (cls !== "total") tr.append(el("td", { text: fmt$(sum(vals)) })); else tr.append(el("td")); tb.append(tr); };
  row("Opening cash", c.W.map(w => w > 1 ? c.closing[w - 2] : M.meta.opening_cash), "sub");
  CATS.forEach(([k, n, sg]) => row((sg > 0 ? "+ " : "− ") + n, c.W.map(w => Math.abs(c.flows[w][k])), "", k));
  row("Net cash flow", c.W.map((w, i) => c.inflow[i] - c.outflow[i]), "sub");
  row("Closing cash", c.closing, "total"); t.append(tb);
  if (drillSel) { const w = parseInt(drillSel), k = drillSel.replace(/^\d+/, ""); drill(w, k); } else $("#drill").hidden = true;
  const ul = $("#cashRules"); ul.innerHTML = ""; [...M.meta.cash_rules, M.meta.cash_floor_note, "Scenarios: Improved = new sales 105%, vendors 98%; Stress = new sales 90%, vendors 105%, fleet payments (open AR and new) 2 weeks later."].forEach(s => ul.append(el("li", { text: s })));
}
function drill(w, k) {
  const c = cashModel, box = $("#drill"); box.hidden = false; box.innerHTML = "";
  const its = (c.items[w + k] || []).slice().sort((a, b) => Math.abs(b.amt) - Math.abs(a.amt)); const name = CATS.find(x => x[0] === k)[1];
  box.append(el("div", { class: "card-head" }, el("div", {}, el("h3", { text: `${name} · week ${w} (${wkDate(w)} – ${wkDate(w, 6)})` }), el("div", { class: "sub", text: fmt$(Math.abs(c.flows[w][k])) + " in this week · " + its.length + " lines" })),
    el("button", { class: "ghost", type: "button", text: "Close", onclick: () => { drillSel = null; box.hidden = true; renderCash(); } })));
  table(box.appendChild(el("div", { class: "tbl-wrap", style: "max-height:360px;overflow:auto" })).appendChild(el("table")), [{ h: "ID", k: "id", cls: "l mono" }, { h: "Date", f: r => r.expected_cash_date || "—", cls: "l" }, { h: "Loc.", k: "location_id", cls: "l" },
    { h: "Type", k: "commitment_type", cls: "wrap" }, { h: "Source", k: "source", cls: "l" },
    { h: "Basis", f: r => el("span", { class: "chip " + (r.certainty === "known" ? "known" : "est"), text: r.certainty === "known" ? "Known" : "Driver" }) }, { h: "Amount", f: r => fmt$(r.amt) }], its.slice(0, 200));
}

// ---------------------------------------------------------------- SOURCES & QUALITY
function renderSources() {
  const S = DS.data_sources.rows;
  tiles($("#srcTiles"), [["Source systems", String(S.length), "simulated"], ["Tables", fmtN(M.meta.source_tables), "logical tables"], ["Files", fmtN(M.meta.source_files), "CSV files"],
    ["Records", fmtN(M.meta.source_rows), "Nov 2024 – Oct 2026"], ["Data as of", M.meta.cutoff, "snapshot date"]]);
  const g = $("#srcGrid"); g.innerHTML = "";
  [...S].sort((a, b) => b.records - a.records).forEach(s => g.append(el("div", { class: "src" },
    el("div", { class: "src-top" }, el("span", { class: "mono-badge", "aria-hidden": "true", text: s.source.slice(0, 1).toUpperCase() }), el("div", {}, el("b", { text: s.source[0].toUpperCase() + s.source.slice(1) }), el("div", { class: "sub", text: s.description })), el("span", { class: "pill ok" }, el("span", { class: "dot" }), s.status)),
    el("dl", { class: "src-stats" }, el("div", {}, el("dt", { text: "Records" }), el("dd", { text: fmtN(s.records) })), el("div", {}, el("dt", { text: "Tables" }), el("dd", { text: String(s.tables) }))),
    el("div", { class: "note", text: s.usage }))));
  table($("#tEv"), [{ h: "Date", k: "date", cls: "l" }, { h: "Event", k: "event", cls: "wrap" }, { h: "Evidence", k: "evidence", cls: "wrap" }], DS.business_events.rows);
}
function renderQuality() {
  const R = DS.reconciliations.rows, pass = R.filter(r => r.status === "PASS").length;
  tiles($("#dqTiles"), [["Checks passed", `${pass} / ${R.length}`, pass === R.length ? el("span", { class: "up", text: "All tie out to the cent" }) : el("span", { class: "down", text: (R.length - pass) + " need attention" })],
    ["Control totals", "1,560", "metric × month × entity comparisons"], ["Package verifier", fmtN(M.meta.package_checks) + " checks", "validation_summary.json: PASS"], ["Source rows read", fmtN(M.meta.source_rows), M.meta.source_files + " CSV files"],
    ["Model built", M.meta.generated_at.slice(0, 16).replace("T", " ") + " UTC", "cutoff " + M.meta.cutoff]]);
  $("#dqSub").textContent = "Money checks in integer cents, zero tolerance.";
  table($("#tDq"), [{ h: "Status", f: r => el("span", { class: "chip " + (r.status === "PASS" ? "fav" : "unf"), text: r.status === "PASS" ? "✓ Pass" : "✕ Fail" }) }, { h: "Area", k: "area", cls: "l" }, { h: "Check", k: "check", cls: "wrap" }, { h: "Detail", k: "detail", cls: "wrap" }], R);
}

// ---------------------------------------------------------------- tabs
let current = "overview";
const VIEWS = { overview: renderOverview, month: renderMonth, bva: renderBva, shops: renderShops, mix: renderMix, tech: renderTech, parts: renderParts, mkt: renderMkt, wc: renderWc, cash: renderCash, sources: renderSources, quality: renderQuality };
function show(v) { current = v; document.querySelectorAll(".tab").forEach(t => t.setAttribute("aria-selected", String(t.dataset.view === v))); document.querySelectorAll(".view").forEach(s => s.hidden = s.id !== "v-" + v); VIEWS[v](); try { history.replaceState(null, "", "#" + v); } catch (e) {} }
document.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => show(t.dataset.view)));
const rerender = () => { if (!M) return; chartTheme(); show(current); };
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", rerender);
new MutationObserver(rerender).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
addEventListener("hashchange", () => { const h = location.hash.slice(1); if (VIEWS[h] && h !== current) show(h); });
const setHdr = () => document.documentElement.style.setProperty("--hdr", $("#top").offsetHeight + "px"); addEventListener("resize", setHdr);
$("#monSel").addEventListener("change", e => { mon.p = e.target.value; renderMonth(); });
$("#monAsk").addEventListener("click", () => ask(`Explain ${mLabel(mon.p)} for ABC Auto: net revenue and EBITDA vs budget and vs the same month last year, by shop. Rank the drivers.`));
seg("#bvaScope", "scope", bva, () => { bva.sel = null; renderBva(); }); $("#bvaSel").addEventListener("change", e => { bva.sel = e.target.value; renderBva(); });
$("#bvaEnt").addEventListener("change", e => { bva.ent = e.target.value; renderBva(); });
$("#bvaAsk").addEventListener("click", () => { const { label, periods } = bvaPeriods(); ask(`Explain the main P&L variances vs budget for ${bva.ent === "COMPANY" ? "the company" : bva.ent} in ${label} (months ${periods.join(", ")}). Rank the drivers by EBITDA impact.`); });
seg("#shPeriod", "period", sh, renderShops);
$("#mxEnt").addEventListener("change", e => { mx.ent = e.target.value; renderMix(); });
$("#roQ").addEventListener("input", e => { ro.q = e.target.value; renderRo(); }); $("#roLoc").addEventListener("change", e => { ro.loc = e.target.value; renderRo(); });
$("#scScen").addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return; sc.name = b.dataset.n; Object.assign(sc, SCN()[sc.name]); renderCash(); });
for (const [id, k] of [["#scSal", "sal"], ["#scVen", "ven"], ["#scDel", "del"]]) $(id).addEventListener("input", e => { sc[k] = +e.target.value; sc.name = "custom"; renderCash(); });
$("#scFloor").addEventListener("change", e => { sc.floor = +e.target.value; renderCash(); });
