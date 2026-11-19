# Render check for private/auto/dashboard.html: loads the page in headless Chrome with the local
# datamart, opens every tab, saves screenshots and prints JavaScript errors.
# Usage: python3 pipeline/auto/render_check.py <out_dir>
import asyncio, json, os, sys
from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PAGE = os.path.join(ROOT, "private", "auto", "dashboard.html")
DATA = os.path.join(ROOT, "private", "auto", "datamart.json")
OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/auto_shots"
VIEWS = ["overview", "month", "bva", "shops", "mix", "tech", "parts", "mkt", "wc", "cash", "sources", "quality"]


async def main():
    os.makedirs(OUT, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width": 1500, "height": 1000})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: m.type == "error" and errs.append(m.text))
        html, data = open(PAGE, encoding="utf-8").read(), open(DATA, "rb").read()
        await pg.route("http://demo.local/dashboard.html", lambda r: r.fulfill(body=html, content_type="text/html"))
        await pg.route("http://demo.local/datamart.json", lambda r: r.fulfill(body=data, content_type="application/json"))
        await pg.goto("http://demo.local/dashboard.html")
        await pg.wait_for_timeout(3000)
        for v in VIEWS:
            await pg.evaluate(f"location.hash='{v}'")
            await pg.wait_for_timeout(800)
            await pg.screenshot(path=f"{OUT}/{v}.png", full_page=True)
        await pg.evaluate("location.hash='cash'")
        await pg.wait_for_timeout(600)
        await pg.click("#scScen button[data-n=stress]")
        await pg.wait_for_timeout(500)
        await pg.click("#tCash tbody tr:nth-child(2) td.click")
        await pg.wait_for_timeout(500)
        await pg.screenshot(path=f"{OUT}/cash_stress.png", full_page=True)
        tiles = await pg.evaluate("[...document.querySelectorAll('#cashTiles .tile')].map(t=>t.innerText.replace(/\\n/g,' | '))")
        print(json.dumps(tiles, indent=1))
        print("ERRORS:", errs)
        await b.close()

asyncio.run(main())
