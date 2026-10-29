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
  "browser_args": ["--use-angle=swiftshader"],       （任意。Chromium の起動の引数）
  "hooks": "hooks.py",                               （任意。states.json からの相対。アプリに固有の操作を Python の関数で書く）
  "states": [ {"name": "c01",
               "do": [ ["scroll", "#s2"], ["click", "nav a[href='#s6']"], ["open", "#s1 details"], ["close", "#s1 details"],
                       ["fill_frame", "#in", ""], ["wait", 800] ],
               "rects": {"キー": "CSS セレクタ", "列": ["CSS セレクタ", true],      （true は「見えている全部を囲む」）
                         "点": {"js": "[x0, y0, x1, y1] を返す式"}},
               "frame_rects": {"キー": "iframe の中の CSS セレクタ"} }, ... ] }

do の種類:
  scroll（要素の頭を上から 70px の所へ。null で先頭へ）、click（セレクタ）、open / close（details の開閉）、
  fill_frame（iframe の欄に文字を入れる）、wait（ミリ秒）、
  upload [セレクタ, ファイル]（input[type=file] に渡す）、select [セレクタ, 値か表示名]、fill [セレクタ, 文字]、press [キー]、
  hover [セレクタ]、click_xy [x, y]、drag [[x0, y0], [x1, y1], "left"|"right"|"middle"]、wheel [[x, y], 縦の量]、
  wait_for [JS の式, 打ち切りミリ秒]（式が真になるまで待つ）、js [JS の式]、
  call [関数名, 引数...]（hooks の関数を fn(page, *引数) で呼ぶ。dict を返すと、その場面の rects に足す）
  drag_film [名前, [x0, y0], [x1, y1], 枚数, "left"|"right"]、wheel_film [名前, [x, y], 縦の量の合計, 枚数]
    （動きを細かく刻み、1 刻みごとに <名前>_000.png… を撮る。カーソルの位置は film.json に書く。compose.py の film で流す）
キャンバス（3D の画面など）のように要素で指せない所は、click_xy・drag・wheel か hooks で動かし、カーソルを置く点は
rects の js か hooks の戻り値で残す（compose.py の ctr で使う）。
押してはいけないボタン（取り込み・削除・送信など）は do に書かない。Enter も送らない。
ページが scroll-behavior: smooth でも、ここでは瞬時に動かす（滑らかなスクロールの途中で撮らない）。
"""
import json, os, runpy, sys
from playwright.sync_api import sync_playwright

spec = json.load(open(sys.argv[1], encoding="utf-8")); OUT = sys.argv[2]; os.makedirs(OUT, exist_ok=True)
BASE = os.path.dirname(os.path.abspath(sys.argv[1]))
HOOKS = runpy.run_path(os.path.join(BASE, spec["hooks"])) if spec.get("hooks") else {}
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

def mouse_drag(page, a, b, button="left", steps=24):
    page.mouse.move(*a); page.mouse.down(button=button)
    page.mouse.move(*b, steps=steps); page.mouse.up(button=button)

FILMS = {}

def next_frame(page):
    page.evaluate("new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")

def film_shot(page, name, i, pos):
    next_frame(page); page.wait_for_timeout(40); style(page)
    page.screenshot(path=os.path.join(OUT, f"{name}_{i:03d}.png")); FILMS.setdefault(name, []).append([round(pos[0]), round(pos[1])])

def drag_film(page, name, a, b, n, button="left"):
    FILMS[name] = []; page.mouse.move(*a); page.mouse.down(button=button); film_shot(page, name, 0, a)
    for i in range(1, n + 1):
        x, y = a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n
        page.mouse.move(x, y); film_shot(page, name, i, (x, y))
    page.mouse.up(button=button)

def wheel_film(page, name, at, total, n):
    FILMS[name] = []; page.mouse.move(*at); film_shot(page, name, 0, at)
    for i in range(1, n + 1):
        page.mouse.wheel(0, total / n); film_shot(page, name, i, at)

def act(page, a, got):
    kind, args = a[0], a[1:]
    arg = args[0] if args else None
    if kind == "scroll": scroll(page, arg)
    elif kind == "click": page.click(arg); page.wait_for_timeout(800)
    elif kind in ("open", "close"):
        page.evaluate("([s, o]) => { const d = document.querySelector(s); if (d) d.open = o; }", [arg, kind == "open"])
    elif kind == "fill_frame":
        f = frame_of(page)
        if f: f.fill(arg, args[1])
    elif kind == "wait": page.wait_for_timeout(int(arg))
    elif kind == "upload": page.set_input_files(arg, os.path.join(BASE, args[1]))
    elif kind == "select":
        try: page.select_option(arg, value=args[1], timeout=3000)
        except Exception: page.select_option(arg, label=args[1])
    elif kind == "fill": page.fill(arg, args[1])
    elif kind == "press": page.keyboard.press(arg)
    elif kind == "hover": page.hover(arg)
    elif kind == "click_xy": page.mouse.click(*args[:2])
    elif kind == "drag": mouse_drag(page, args[0], args[1], args[2] if len(args) > 2 else "left")
    elif kind == "wheel": page.mouse.move(*args[0]); page.mouse.wheel(0, args[1])
    elif kind == "drag_film": drag_film(page, arg, args[1], args[2], int(args[3]), args[4] if len(args) > 4 else "left")
    elif kind == "wheel_film": wheel_film(page, arg, args[1], args[2], int(args[3]))
    elif kind == "wait_for": page.wait_for_function(arg, timeout=int(args[1]) if len(args) > 1 else 30000)
    elif kind == "js": page.evaluate(arg)
    elif kind == "call":
        if arg not in HOOKS: sys.exit(f"ERROR: hooks に関数 {arg} が無い")
        r = HOOKS[arg](page, *args[1:])
        if isinstance(r, dict): got.update({k: [round(x) for x in v] for k, v in r.items()})
    else: sys.exit(f"ERROR: 知らない do: {kind}")

rects = {}
with sync_playwright() as p:
    b = p.chromium.launch(args=spec.get("browser_args", []))
    ctx = b.new_context(viewport={"width": W, "height": H}, device_scale_factor=1, locale="ja-JP")
    if spec.get("block_websocket"): ctx.route_web_socket("**", lambda ws: None)
    if spec.get("init_script"): ctx.add_init_script(spec["init_script"])
    page = ctx.new_page(); page.goto(spec["url"]); page.wait_for_timeout(2500)
    for st in spec["states"]:
        d = {}
        for a in st.get("do", []): act(page, a, d)
        page.wait_for_timeout(int(st.get("settle", 700))); style(page)
        page.screenshot(path=os.path.join(OUT, st["name"] + ".png"))
        for k, v in st.get("rects", {}).items():
            if isinstance(v, dict): r = page.evaluate(v["js"])
            else:
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
        tmp = os.path.join(OUT, ".rects.json.tmp")
        rects[st["name"]] = d; print(st["name"], "ok", ("見つからない: " + ", ".join(missing)) if missing else "", flush=True)
        with open(tmp, "w", encoding="utf-8") as fo: json.dump(rects, fo, ensure_ascii=False, indent=1)
        os.replace(tmp, os.path.join(OUT, "rects.json"))         # 場面ごとに書く（途中で止まっても撮れた分の座標は残る）
        if FILMS:
            with open(tmp, "w", encoding="utf-8") as fo: json.dump(FILMS, fo)
            os.replace(tmp, os.path.join(OUT, "film.json"))
    b.close()
print("done", OUT)
