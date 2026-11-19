function intro() {
  const box = el("div", { class: "msg bot" }); box.innerHTML = md("Ask me anything about ABC Auto's numbers. I read the same data as the dashboards, cite shop IDs (LOC-01–LOC-03, HQ) and repair orders, and can draw a new chart or table on request.");
  const sg = el("div", { class: "sugg" });
  ["Why did EBITDA margin fall in FY2026 while revenue grew?", "Which shop has the worst comeback problem, and what does it cost?", "How much idle technician capacity do we have?", "What is the cash low point in the next 13 weeks?", "Chart parts margin by shop by month"].forEach(s => sg.append(el("button", { type: "button", text: s, onclick: () => ask(s) })));
  box.append(sg); msgs.append(box);
}
function contextBlock() {
  const ents = ["COMPANY", ...LOCS, "HQ"];
  const km = DS.kpi_monthly.rows.filter(r => ents.includes(r.entity)).map(r => [r.period, r.entity, Math.round(r.net_revenue), Math.round(r.budget_net_revenue), Math.round(r.contribution), Math.round(r.ebitda), Math.round(r.budget_ebitda),
    r.customer_ros, r.aro, r.parts_margin_pct, r.utilization_pct, r.efficiency_pct, r.comebacks, Math.round(r.bank), Math.round(r.ar), Math.round(r.ap)]);
  const cm = cashModel || computeCash();
  const cw = cm.W.map((w, i) => [cm.lab[i], Math.round(cm.inflow[i]), Math.round(cm.outflow[i]), Math.round(cm.closing[i])]);
  return `COMPANY: ${M.meta.company} — DEMO COMPANY, SYNTHETIC DATA (never present as a real client). ${M.meta.business}. USD. ${M.meta.fiscal_year_note}.
Locations: ${LOCS.map(e => e + " = " + NM[e]).join("; ")}; HQ = shared office (no bays, no revenue).
Data cutoff ${M.meta.cutoff}. Actual months ${M.meta.first_period}..${M.meta.last_period}. Reconciliation checks: ${M.meta.recon_pass}/${M.meta.recon_total} pass; package verifier ${M.meta.package_checks} checks PASS.
ACCOUNTING RULES: P&L from trial-balance period activity. Net revenue = labor (4000) + parts (4010) + shop fees (4020) + sublet (4030) sales − customer concessions (4090), excluding sales tax. Contribution = net revenue − technician payroll (5000-5015, ALL earned incl. idle/PTO), delivered parts FIFO COGS (5100), net warranty (5110 − supplier recoveries 5120), stock loss (5130), sublet cost (5200). EBITDA excludes depreciation 6600 and interest 6700; HQ counted once. Budget = original, approved 2024-10-18, never revised. Revenue is recognized on vehicle delivery; free warranty comeback ROs have no invoice. Efficiency = billed book hours / actual clock of the same delivered ROs (can exceed 100%); utilization = worked / available technician minutes. Platform-claimed ad conversions overlap and are not revenue. Owner distributions are equity, not expense.
EVENTS: ${DS.business_events.rows.map(r => r.date + " " + r.event).join(" | ")}
CASH: ${M.meta.cash_rules.join(" ")} Reserve ${M.meta.cash_floor}: ${M.meta.cash_floor_note}
KNOWN STORIES: ${DS.stories.rows.map(s => s.id + ": " + s.story).join(" | ")}
USER IS VIEWING tab "${current}"; month review ${mon.p || M.meta.last_period}; P&L scope ${bvaPeriods().label} for ${bva.ent}; cash scenario ${sc.name}: new sales ${sc.sal}%, vendors ${sc.ven}%, extra fleet delay ${sc.del} weeks, reserve ${sc.floor}.
MONTHLY KPIs [period, entity, net_revenue, budget_net_revenue, contribution, ebitda, budget_ebitda, customer_ros, aro, parts_margin_pct, utilization_pct, efficiency_pct, comebacks, bank, ar, ap]:
${JSON.stringify(km)}
13-WEEK CASH (current scenario; weeks Sun–Sat from 2026-11-01) [week, inflows, outflows, closing]: opening ${M.meta.opening_cash}; ${JSON.stringify(cw)}
DATASETS you can query with query_data:
${Object.entries(DS).map(([k, v]) => `- ${k} (${v.rows.length} rows; grain ${v.grain}): ${v.columns.join(", ")}. ${v.description}`).join("\n")}`;
}
const RULES = () => `You are the AI financial analyst inside the ABC Auto FP&A Studio dashboard. Answer using ONLY the data below and the page tools.
- Use the context tables when they already answer; call query_data or get_pnl for detail. Never invent numbers. Do arithmetic carefully.
- Cite location IDs (LOC-01, LOC-02, LOC-03, HQ), months (YYYY-MM) and record IDs (RO-…, INV-…, BILL-…, FLEET-…) when relevant.
- When a visual helps or the user asks for a chart, call show_chart (or show_table) with exact numbers. One unit per chart: never mix dollars and percentages.
- Answer in the language the user writes in. Lead with the answer, then 2–5 bullets with numbers ($ rounded, % to 1 decimal). Plain text with **bold** and "-" bullets; no markdown tables (use show_table).
- End with one short line "Sources: <dataset names>".
- This is a demo company with synthetic data; say so if asked about real-world facts.
${contextBlock()}`;
