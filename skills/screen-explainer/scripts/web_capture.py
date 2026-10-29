"""Web アプリ（ローカルのダッシュボード等）を裏のブラウザ（Playwright・Chromium）で開いて、場面ごとに画面を撮り、
要素の画面座標を rects.json に書く。PC の画面には触らない（撮影中もユーザーは画面を使える）。

usage: python3 web_capture.py <states.json> <出力フォルダ>

states.json:
{ "url": "http://127.0.0.1:8766/",
  "blur_css": "td:not(:first-child) { color: transparent !important; text-shadow: 0 0 9px rgba(40,40,40,.75) !important; }",
  "frame_css": "#term { filter: blur(6px) }",        （任意。URL に frame_match を含む iframe に入れる CSS）
  "frame_match": "8767",                             （任意。iframe の URL の一部）
  "block_websocket": true,                           （任意。WebSocket をつながない＝本物の端末・会話に触らない）
  "init_script": "localStorage.setItem('k','v');",   （任意）
  "states": [ {"name": "c01",
               "do": [ ["scroll", "#s2"], ["click", "nav a[href='#s6']"], ["open", "#s1 details"], ["close", "#s1 details"],
                       ["fill_frame", "#in", ""], ["wait", 800] ],
               "rects": {"キー": "CSS セレクタ", "列": ["CSS セレクタ", true]},     （true は「見えている全部を囲む」）
               "frame_rects": {"キー": "iframe の中の CSS セレクタ"} }, ... ] }

do の種類: scroll（要素の頭を上から 70px の所へ。null で先頭へ）、click、open / close（details の開閉）、fill_frame（iframe の欄に文字を入れる）、wait（ミリ秒）
押してはいけないボタン（取り込み・削除・送信など）は do に書かない。Enter も送らない。
ページが scroll-behavior: smooth でも、ここでは瞬時に動かす（滑らかなスクロールの途中で撮らない）。
"""
import json, os, sys
from playwright.sync_api import sync_playwright

spec = json.load(open(sys.argv[1], encoding="utf-8")); OUT = sys.argv[2]; os.makedirs(OUT, exist_ok=True)
W, H = 1920, 1020
RECT_JS = """([s, all_]) => { const es = [...document.querySelectorAll(s)].filter(e => { const r = e.getBoundingClientRect();
  return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight; });
  if (!es.length) return null; const rs = (all_ ? es : es.slice(0, 1)).map(e => e.getBoundingClientRect());
  return [Math.min(...rs.map(r => r.left)), Math.min(...rs.map(r => r.top)), Math.max(...rs.map(r => r.right)), Math.max(...rs.map(r => r.bottom))]; }"""

def frame_of(page):
    m = spec.get("frame_match")
    return next((f for f in page.frames if m and m in f.url), None)

INJECT_JS = """css => { let s = document.getElementById('se-redact');
  if (!s) { s = document.createElement('style'); s.id = 'se-redact'; (document.head || document.documentElement).appendChild(s); }
  s.textContent = css; return document.getElementById('se-redact').textContent === css; }"""

def style(page):
    """ぼかしの CSS を入れる。撮る直前に毎回呼ぶ。入らなければ撮らずに止める（ぼかしていない画面を残さない）。"""
    for target, css, what in ((lambda: page.main_frame, spec.get("blur_css"), "blur_css"), (lambda: frame_of(page), spec.get("frame_css"), "frame_css")):
        if not css: continue
        err = None
        for _ in range(5):
            try:
                f = target()
                if f is None: err = f"iframe（{spec.get('frame_match')}）が見つからない"
                elif f.evaluate(INJECT_JS, css): err = None; break
                else: err = "CSS が入ったことを確かめられない"
            except Exception as e:
                err = str(e)
            page.wait_for_timeout(500)
        if err: sys.exit(f"ERROR: {what} を入れられないので撮影を止めた: {err}")

def scroll(page, sel):
    page.evaluate("""s => { document.documentElement.style.scrollBehavior = 'auto';
        if (!s) { scrollTo({top: 0, behavior: 'instant'}); return; }
        const e = document.querySelector(s); if (!e) return;
        scrollTo({top: Math.max(0, e.getBoundingClientRect().top + scrollY - 70), behavior: 'instant'}); }""", sel)
    page.wait_for_timeout(300)

rects = {}
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": W, "height": H}, device_scale_factor=1, locale="ja-JP")
    if spec.get("block_websocket"): ctx.route_web_socket("**", lambda ws: None)
    if spec.get("init_script"): ctx.add_init_script(spec["init_script"])
    page = ctx.new_page(); page.goto(spec["url"]); page.wait_for_timeout(2500)
    for st in spec["states"]:
        for act in st.get("do", []):
            kind, arg = act[0], (act[1] if len(act) > 1 else None)
            if kind == "scroll": scroll(page, arg)
            elif kind == "click": page.click(arg); page.wait_for_timeout(800)
            elif kind in ("open", "close"):
                page.evaluate("([s, o]) => { const d = document.querySelector(s); if (d) d.open = o; }", [arg, kind == "open"])
            elif kind == "fill_frame":
                f = frame_of(page)
                if f: f.fill(arg, act[2])
            elif kind == "wait": page.wait_for_timeout(int(arg))
        page.wait_for_timeout(700); style(page)
        page.screenshot(path=os.path.join(OUT, st["name"] + ".png"))
        d = {}
        for k, v in st.get("rects", {}).items():
            sel, all_ = (v, False) if isinstance(v, str) else (v[0], bool(v[1]))
            r = page.evaluate(RECT_JS, [sel, all_])
            if r: d[k] = [round(x) for x in r]
        f = frame_of(page)
        if f:
            fx, fy = page.evaluate("""m => { const i = [...document.querySelectorAll('iframe')].find(e => e.src.includes(m));
                const r = i.getBoundingClientRect(); return [r.left, r.top]; }""", spec["frame_match"])
            for k, sel in st.get("frame_rects", {}).items():
                r = f.evaluate(RECT_JS, [sel, False])
                if r: d[k] = [round(r[0] + fx), round(r[1] + fy), round(r[2] + fx), round(r[3] + fy)]
        missing = sorted((set(st.get("rects", {})) | set(st.get("frame_rects", {}))) - set(d))
        rects[st["name"]] = d; print(st["name"], "ok", ("見つからない: " + ", ".join(missing)) if missing else "", flush=True)
    json.dump(rects, open(os.path.join(OUT, "rects.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    b.close()
print("done", OUT)
