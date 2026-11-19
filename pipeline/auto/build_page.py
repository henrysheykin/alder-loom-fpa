# Assembles private/auto/dashboard.html from the shared ABC Restaurants page shell (CSS, chart/table
# helpers, AI analyst plumbing) plus the auto-specific parts in this folder:
#   page_body.html (markup), page_views.js (tabs), page_ai.js (analyst context and rules).
# Usage: python3 pipeline/auto/build_page.py
import os, re

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
R = open(os.path.join(ROOT, "private", "restaurants", "dashboard.html"), encoding="utf-8").read().split("\n")
def L(a, b): return "\n".join(R[a - 1:b])
def find(prefix, start=0):
    for i in range(start, len(R)):
        if R[i].startswith(prefix): return i + 1
    raise SystemExit("shell marker not found: " + prefix)

end_head = find("</head>")
h0 = find('"use strict";') - 2                      # "(() => {" line
h1 = find("const seg = ")                           # last generic helper
a0 = find('const chatEl = $("#chat")')
a1 = find('function addMsg(')
q0 = find("function applyQuery(")
q1 = find("async function ask(") ; q1 = next(i for i in range(q1, len(R)) if R[i - 1] == "}")

head = L(1, end_head).replace("ABC Restaurants FP&amp;A Studio", "ABC Auto FP&amp;A Studio")
read = lambda f: open(os.path.join(HERE, f), encoding="utf-8").read()
ai1 = L(a0, a1).replace('company: "abc-restaurants"', 'company: "abc-auto"')
ai2 = L(q0, q1)
ai2 = ai2.replace("one entity (COMPANY, R01, R02, R03, HQ): every GL account plus subtotals (Net revenue, Cost of goods sold, Gross profit, Labor, Prime cost, EBITDA, Pretax income)",
                  "one entity (COMPANY, LOC-01, LOC-02, LOC-03, HQ): every GL account (concessions negative) plus subtotals (Net revenue, Contribution, EBITDA, Net income)")
ai2 = ai2.replace('enum: ["COMPANY", "R01", "R02", "R03", "HQ"]', 'enum: ["COMPANY", "LOC-01", "LOC-02", "LOC-03", "HQ"]')
boot = '''
// ---------------------------------------------------------------- boot
async function boot() {
  const onSite = !IN_CLAUDE && location.pathname.startsWith("/auto");
  setHdr(); if (onSite) $("#signout").hidden = false;
  try { const r = await fetch(onSite ? "/api/data/auto" : "datamart.json", { cache: "no-store" }); if (r.status === 401) { location.href = "/login"; return; } M = await r.json(); }
  catch (e) { $("#main").prepend(el("div", { class: "card err", text: "Data file could not be loaded." })); return; }
  DS = M.datasets; sc.floor = M.meta.cash_floor || 450000;
  $("#asof").textContent = "Data as of " + M.meta.cutoff;
  const rp = $("#reconPill"); rp.className = "pill " + (M.meta.recon_pass === M.meta.recon_total ? "ok" : "bad"); rp.lastChild.textContent = `${M.meta.recon_pass}/${M.meta.recon_total} checks pass`; rp.style.cursor = "pointer"; rp.onclick = () => show("quality");
  chartTheme(); intro();
  const h = (location.hash || "").slice(1); show(VIEWS[h] ? h : "overview"); setHdr();
}
boot();
})();
</script>
</body>
</html>
'''
out = "\n".join([head, read("page_body.html"), L(h0, h1), read("page_views.js"), "// ---------------------------------------------------------------- AI analyst",
                 ai1, read("page_ai.js"), ai2, boot])
left = [m.group(0) for m in re.finditer(r"[Rr]estaurant|\bR0[123]\b", out)]
if left: raise SystemExit(f"leftover restaurant references: {left[:5]}")
os.makedirs(os.path.join(ROOT, "private", "auto"), exist_ok=True)
open(os.path.join(ROOT, "private", "auto", "dashboard.html"), "w", encoding="utf-8").write(out)
print("wrote private/auto/dashboard.html", len(out.split("\n")), "lines")
