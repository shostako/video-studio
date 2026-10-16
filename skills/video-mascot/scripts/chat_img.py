"""ChatGPT の通常の Chat 画面（chatgpt.com）で画像を1枚作る。Codex の枠は使わない。Windows 側の Python + Playwright で、専用の Chrome プロファイルを動かす。
  python chat_img.py login                        専用プロファイルの Chrome で chatgpt.com を開く（ログインは人が手で。閉じたら終わり）
  python chat_img.py gen -p 文 [-r 参照]... -o 出力 [--headless] [--keep-open]
終了コードは img.sh と同じ: 0 成功（標準出力に保存先を1行） / 2 引数の誤り・道具が無い / 3 ログインしていない / 4 上限 / 5 タイムアウト / 6 画像が出ない。
プロファイルは同時に1つの Chrome しか開けないので、gen はロックを取って1枚ずつ描く（並列に呼んでも順番待ちになる）。"""
import argparse, os, re, subprocess, sys, time

HOME = os.path.expanduser("~")
VS = os.environ.get("VIDEO_SCENE_HOME_WIN") or os.path.join(HOME, ".local", "share", "video-scene")
PROFILE = os.environ.get("CHAT_IMG_PROFILE") or os.path.join(VS, "chatgpt-profile")
CHROME = os.environ.get("CHAT_IMG_CHROME") or r"C:\Program Files\Google\Chrome\Application\chrome.exe"
URL = "https://chatgpt.com/"
TIMEOUT = int(os.environ.get("CHAT_IMG_TIMEOUT", "600"))
# 上限の表示。英語と日本語の両方を見る（文言は変わりうるので、広めに拾う）
LIMIT_RE = re.compile(r"(hit|reached) (the|your) .{0,40}limit|limit (for|on) image|image generation.{0,40}limit|try again (later|after|in)|"
                      r"上限に達|制限に達|上限に到達|しばらくしてから|後でもう一度", re.I)
REFUSE_RE = re.compile(r"can't (help|create|generate)|cannot (help|create|generate)|content polic|作成できません|生成できません|お手伝いできません", re.I)


class Fail(Exception):
    def __init__(self, msg, code): super().__init__(msg); self.code = code


def log(*a): print(*a, file=sys.stderr, flush=True)


def login():
    os.makedirs(PROFILE, exist_ok=True)
    if not os.path.exists(CHROME): log("ERROR: Chrome が無い:", CHROME); return 2
    # ログインは Playwright を通さず素の Chrome で開く（自動操作の印が付いた Chrome だと Google のログインが弾かれることがある）
    log(f"専用プロファイル {PROFILE} で chatgpt.com を開く。ログインが済んだらウィンドウを閉じる")
    subprocess.run([CHROME, f"--user-data-dir={PROFILE}", "--no-first-run", "--no-default-browser-check", URL])
    return 0


class Lock:
    """プロファイルの横に置くロックファイル。O_EXCL で作れた者だけが Chrome を開く。持ち主が落ちて残ったものは古ければ消す。"""
    def __init__(self, path, wait): self.path, self.wait = path, wait
    def __enter__(self):
        t0 = time.time()
        while True:
            try: fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY); os.write(fd, str(os.getpid()).encode()); os.close(fd); return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.path) > TIMEOUT + 120: os.remove(self.path); continue
                except FileNotFoundError: continue
                if time.time() - t0 > self.wait: raise Fail("ERROR(timeout): ほかの gen が終わらない（ロック待ち）", 5)
                time.sleep(2)
    def __exit__(self, *a):
        try: os.remove(self.path)
        except FileNotFoundError: pass


def main_text(page):
    m = page.locator("main")
    return m.inner_text() if m.count() else ""


# 画面の中の大きい画像（512px 以上。アバター・アイコンを除く）。添付した参照画像は alt で除く
BIG_IMGS = """() => Array.from(document.querySelectorAll('main img')).filter(im => im.complete && im.naturalWidth >= 512 && im.naturalHeight >= 512)
  .map(im => ({src: im.currentSrc || im.src, alt: im.alt || ''}))"""
USER_ALT = re.compile(r"添付|attach|upload", re.I)


def gen(a):
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    for r in a.ref:
        if not os.path.isfile(r): raise Fail(f"ERROR: 参照画像が無い: {r}", 2)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with Lock(PROFILE + ".lock", wait=TIMEOUT * 4), sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            PROFILE, channel="chrome", headless=a.headless, no_viewport=True, accept_downloads=True,
            ignore_default_args=["--enable-automation"], args=["--disable-blink-features=AutomationControlled", "--window-size=1280,1000"])
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(URL, wait_until="domcontentloaded")
            box = page.locator('#prompt-textarea, div[contenteditable="true"][role="textbox"]').first
            try: box.wait_for(state="visible", timeout=30000)
            except PWTimeout: raise Fail("ERROR(auth): 入力欄が出ない。ログインしていない（chat_img.py login で入り直す）", 3)
            if page.locator('[data-testid="login-button"]').count():
                raise Fail("ERROR(auth): ログインしていない（chat_img.py login で入り直す）", 3)
            before = {x["src"] for x in page.evaluate(BIG_IMGS)}
            if a.ref:
                page.locator('input[type="file"]:not([accept]), input[type="file"][multiple]:not([capture])').first.set_input_files(a.ref)
                # 添付の縮図が並び、送るボタンが押せるまで待つ（上げている間は押せない）
                page.wait_for_timeout(1500)
            note = ("添付画像は、指示が編集なら編集の元として、そうでなければ構図や画風の参考として使って。" if a.ref else "")
            text = f"画像生成ツールで画像を1枚だけ作って。文章の返事は要らない。{note}\n内容: {a.prompt}"
            box.click(); page.keyboard.insert_text(text)
            # 送るボタンは文字を入れてから出る。testid が無い版もあるので aria-label でも探す
            send = page.locator('[data-testid="send-button"], button[aria-label*="送信"], button[aria-label*="Send"]').first
            send.wait_for(state="visible", timeout=60000)
            t0 = time.time()
            while not send.is_enabled():
                if time.time() - t0 > 120: raise Fail("ERROR(timeout): 添付が上がりきらない", 5)
                page.wait_for_timeout(500)
            send.click()
            src = wait_image(page, before, len(main_text(page)), a.timeout)
            data = fetch(ctx, page, src)
            out = save_as(data, a.out)
            if a.keep_open: input("Enter で閉じる")
            return out
        finally:
            ctx.close()


def save_as(data, want):
    """-o で渡された名前のとおりに保存する。.png を頼まれたら、Chat が webp や jpeg で返しても PNG に直す（呼び出し側はその名前の有無で成否を見る）。"""
    import io
    from PIL import Image
    try: im = Image.open(io.BytesIO(data)); im.load()
    except Exception: raise Fail("ERROR(no-image): 画像ではないものが返ってきた", 6)
    fmt = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}.get(os.path.splitext(want)[1].lower(), "PNG")
    if fmt == "JPEG" and im.mode not in ("RGB", "L"): im = im.convert("RGB")
    tmp = want + f".tmp{os.getpid()}"
    im.save(tmp, fmt); os.replace(tmp, want)
    return os.path.abspath(want)


def evidence(page, tag):
    """上限・失敗のときの画面と本文を残す（文言を LIMIT_RE に固めるための一次資料）。"""
    d = os.path.join(VS, "chat-img-evidence"); os.makedirs(d, exist_ok=True)
    base = os.path.join(d, time.strftime("%Y%m%d-%H%M%S") + "_" + tag)
    try: page.screenshot(path=base + ".png", full_page=False)
    except Exception: pass
    try:
        with open(base + ".txt", "w", encoding="utf-8") as f: f.write(page.locator("main").inner_text())
    except Exception: pass
    return base


def wait_image(page, before, text0, timeout):
    """送った後に、新しく出た大きい画像が描き終わるまで待つ。上限・拒否の文が出たらそこで止める。
    今の UI（2026-10）は発言ごとの印（data-message-author-role）を持たないので、送る前に見えていた画像と本文の長さを基準に差分で見る。"""
    t0 = time.time(); last = None
    while time.time() - t0 < timeout:
        page.wait_for_timeout(2000)
        tail = main_text(page)[-1500:]   # 送った後の返事は本文の末尾に出る（送る前の提案文などは消えるので、長さの差では切らない）
        busy = page.locator('[data-testid="stop-button"], button[aria-label*="停止"], button[aria-label*="Stop"]').count() > 0
        if LIMIT_RE.search(tail):
            raise Fail("ERROR(limit): Chat の画像生成の上限: " + " ".join(tail.split())[-300:] + f"（記録: {evidence(page, 'limit')}）", 4)
        new = [x for x in page.evaluate(BIG_IMGS) if x["src"] not in before and not USER_ALT.search(x["alt"])]
        src = new[-1]["src"] if new else None
        # 描いている間は「停止」ボタンが出ている。消えて、同じ画像が2回続けて見えたら出来上がり（途中の荒い絵を拾わない）
        if src and not busy and src == last: return src
        last = src
        if not busy and not src and time.time() - t0 > 60 and REFUSE_RE.search(tail):
            raise Fail("ERROR(no-image): 断られた: " + " ".join(tail.split())[:300] + f"（記録: {evidence(page, 'refused')}）", 6)
    raise Fail(f"ERROR(timeout): {timeout} 秒で画像が出なかった（記録: {evidence(page, 'timeout')}）", 5)


def fetch(ctx, page, src):
    if src.startswith("data:"):
        import base64; return base64.b64decode(src.split(",", 1)[1])
    if src.startswith("blob:"):
        b = page.evaluate("async u => { const r = await fetch(u); return Array.from(new Uint8Array(await r.arrayBuffer())); }", src)
        return bytes(b)
    r = ctx.request.get(src)
    if not r.ok: raise Fail(f"ERROR(no-image): 画像を取れない（HTTP {r.status}）", 6)
    return r.body()


def probe():
    """今の UI で、gen が頼るセレクタが生きているかを数で出す（UI が変わったときの切り分け用）。"""
    from playwright.sync_api import sync_playwright
    with Lock(PROFILE + ".lock", wait=60), sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(PROFILE, channel="chrome", headless=False, no_viewport=True,
            ignore_default_args=["--enable-automation"], args=["--disable-blink-features=AutomationControlled", "--window-size=1280,1000"])
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page(); page.goto(URL, wait_until="domcontentloaded"); page.wait_for_timeout(8000)
            for s in ("#prompt-textarea", '[data-testid="send-button"]', '[data-testid="stop-button"]', '[data-testid="login-button"]',
                      'input[type="file"]', '[data-message-author-role="assistant"]', "main"):
                print(f"{page.locator(s).count():3d}  {s}")
            html = page.content()
            print("候補 data-testid:", sorted(set(re.findall(r'data-testid="([^"]+)"', html)))[:60])
            print("file input:", re.findall(r'<input[^>]*type="file"[^>]*>', html)[:5])
            print("入力欄:", re.findall(r'<(?:textarea|div)[^>]*(?:contenteditable="true"|<textarea)[^>]*>', html)[:5], re.findall(r'<textarea[^>]*>', html)[:3])
            print("ボタン:", page.evaluate("() => Array.from(document.querySelectorAll('button')).map(b => (b.getAttribute('aria-label')||'') + '|' + (b.id||'') + '|' + b.innerText.slice(0,20)).filter(x => x !== '||')"))
            print("証跡:", evidence(page, "probe"))
        finally: ctx.close()
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("login"); sp.add_parser("probe")
    g = sp.add_parser("gen")
    g.add_argument("-p", "--prompt", required=True); g.add_argument("-o", "--out", required=True)
    g.add_argument("-r", "--ref", action="append", default=[]); g.add_argument("--headless", action="store_true")
    g.add_argument("--keep-open", action="store_true"); g.add_argument("--timeout", type=int, default=TIMEOUT)
    a = ap.parse_args()
    if a.cmd == "login": return login()
    if a.cmd == "probe": return probe()
    try: print(gen(a)); return 0
    except Fail as e: log(str(e)); return e.code
    except ImportError: log("ERROR: playwright が入っていない（専用の venv に pip install playwright）"); return 2


if __name__ == "__main__":
    sys.exit(main())
