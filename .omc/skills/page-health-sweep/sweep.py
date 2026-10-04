import re, sys, json
from playwright.sync_api import sync_playwright
PAGES = sys.argv[1].split(",")
BAD = re.compile(r"\bNaN\b|\bundefined\b|Infinity|Invalid Date|\[object Object\]|\bnull\b")
res = {}
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    ctx = b.new_context(viewport={"width":1280,"height":900})
    # ⚠️자동 갱신을 끈다 — 켜 두면 페이지를 새로 열 때마다 화면이 증권사 이력 동기화를 부른다
    #   (2026-10-04 실측: 스윕 한 번에 키움 동기화 32회).
    ctx.add_init_script("try{localStorage.setItem('pi:auto-refresh','0')}catch(e){}")
    pg = ctx.new_page()
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
        pg.close()
        pg = ctx.new_page()
    b.close()
print(json.dumps(res, ensure_ascii=False, indent=1))
