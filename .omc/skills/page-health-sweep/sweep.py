import re, sys, json
from playwright.sync_api import sync_playwright
PAGES = sys.argv[1].split(",")
BAD = re.compile(r"\bNaN\b|\bundefined\b|Infinity|Invalid Date|\[object Object\]|\bnull\b")
res = {}
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width":1280,"height":900})
    for path in PAGES:
        errs, fails = [], []
        pg.on("console", lambda m: errs.append(m.text[:200]) if m.type=="error" else None)
        pg.on("response", lambda r: fails.append(f"{r.status} {r.url[:120]}") if r.status>=400 else None)
        try:
            pg.goto("http://localhost:3000"+path, wait_until="networkidle", timeout=60000)
        except Exception as e:
            errs.append("goto: "+str(e)[:100])
        pg.wait_for_timeout(2500)
        txt = pg.inner_text("body")
        bad = sorted({txt[max(0,m.start()-30):m.end()+20].replace("\n"," ") for m in BAD.finditer(txt)})[:8]
        ov = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        res[path] = {"console": errs[:6], "http": sorted(set(fails))[:6], "bad_text": bad, "overflow": ov,
                     "loading": len(re.findall(r"불러오는 중|Loading", txt))}
        pg.remove_listener("console", pg.listeners("console")[0]) if hasattr(pg,"listeners") else None
        pg.close(); pg = b.new_page(viewport={"width":1280,"height":900})
    b.close()
print(json.dumps(res, ensure_ascii=False, indent=1))
