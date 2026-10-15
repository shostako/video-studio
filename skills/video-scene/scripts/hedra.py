"""hedra.py — Hedra API v3（https://api.hedra.com/v3）を呼ぶ。絵＋声 → 話す動画（Character 3、Kling AI Avatar v2 など）。
課金はプリペイドの API の財布（米ドル、Studio のクレジットとは別）。アップロードと見積もりは無料。

使い方:
  vs hedra balance                                  残高
  vs hedra models [語]                              モデル一覧（語で絞る。値段の説明つき）
  vs hedra schema MODEL                             モデルの入力項目
  vs hedra estimate MODEL input.json                見積もり（無料）
  vs hedra run MODEL input.json --out out.mp4 [--max-usd 2.0]
                                                    見積もり → 上限以下なら作る → 完了を待つ → 取り込む
  input.json は API の input そのもの。画像・音声の所に {"file": "ローカルのパス"} と書けば、アップロードして URL に置き換える。

鍵: ~/.config/hedra/api_key（"キーID:秘密"。chmod 600）か環境変数 HEDRA_KEY。鍵は表示しない。
終了コード: 0 成功（run は標準出力に保存先） 2 引数 3 鍵・認証 4 生成の失敗（審査で止められた等） 5 時間切れ
           6 その他 7 残高不足（402）か見積もりが --max-usd を超えた
"""
import argparse, json, mimetypes, os, sys, time, urllib.error, urllib.request, uuid
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import die

BASE = "https://api.hedra.com/v3"


def key():
    k = os.environ.get("HEDRA_KEY")
    p = os.path.expanduser("~/.config/hedra/api_key")
    if not k and os.path.exists(p): k = open(p).read().strip()
    if not k: die("鍵が無い: ~/.config/hedra/api_key か HEDRA_KEY", 3)
    return k


def call(method, path, body=None, raw=None, ctype=None, timeout=120):
    h = {"Authorization": f"Key {key()}", "Accept": "application/json"}
    data = None
    if body is not None: data = json.dumps(body).encode(); h["Content-Type"] = "application/json"
    if raw is not None: data = raw; h["Content-Type"] = ctype
    if method == "POST" and body is not None: h["Idempotency-Key"] = str(uuid.uuid4())
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            t = r.read(); return json.loads(t) if t else {}
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")[:500]
        if e.code in (401, 403): die(f"鍵・認証の問題 ({e.code}): {msg}", 3)
        if e.code == 402: die(f"残高不足 (402): {msg}", 7)
        die(f"HTTP {e.code} {method} {path}: {msg}", 6)


def upload(path):
    if not os.path.exists(path): die(f"ファイルが無い: {path}", 2)
    b = uuid.uuid4().hex; ct = mimetypes.guess_type(path)[0] or "application/octet-stream"
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{os.path.basename(path)}\"\r\n"
            f"Content-Type: {ct}\r\n\r\n").encode() + open(path, "rb").read() + f"\r\n--{b}--\r\n".encode()
    r = call("POST", "/files", raw=body, ctype=f"multipart/form-data; boundary={b}", timeout=600)
    return r["url"]


def resolve(x, base_dir):
    """{"file": パス} をアップロードして {"source": "url", "url": ...} にする（入れ子・配列も）。"""
    if isinstance(x, dict):
        if set(x) == {"file"}:
            p = x["file"] if os.path.isabs(x["file"]) else os.path.join(base_dir, x["file"])
            u = upload(p); print(f"uploaded {os.path.basename(p)}", file=sys.stderr); return {"source": "url", "url": u}
        return {k: resolve(v, base_dir) for k, v in x.items()}
    if isinstance(x, list): return [resolve(v, base_dir) for v in x]
    return x


def local_estimate(model, inp, base_dir):
    """声で動かすモデル（audio がローカルのファイル）は、声の長さ × 公開されている1秒あたりの値段で見積もる。
    値段の説明は「Standard: 720p 5.62¢/second; Pro: ...」「540p 2.5¢/second, 720p 5¢/second」の形を読む。"""
    import re, subprocess
    aud = inp.get("audio")
    files = [x["file"] for x in (aud if isinstance(aud, list) else [aud]) if isinstance(x, dict) and "file" in x]
    if not files: return None
    secs = 0.0
    for f in files:
        p = f if os.path.isabs(f) else os.path.join(base_dir, f)
        secs = max(secs, float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p],
                                              capture_output=True, text=True).stdout.strip() or 0))
    if inp.get("duration_ms"): secs = inp["duration_ms"] / 1000
    with urllib.request.urlopen(urllib.request.Request(BASE + "/models?limit=200"), timeout=60) as f:
        price = next((x.get("price_description", "") for x in json.loads(f.read())["data"] if x["id"] == model), "")
    q = (inp.get("quality") or "").lower()
    seg = price
    if q and re.search(rf"{q}\s*:", price, re.I):
        seg = re.split(r";\s*(?=[A-Za-z]+\s*:)", price[re.search(rf"{q}\s*:", price, re.I).start():])[0]
    res = inp.get("resolution", "")
    m = re.search(rf"(?:^|[\s/]){re.escape(res)}[^,;]*?([\d.]+)¢/second", seg) if res else None
    m = m or re.search(r"([\d.]+)¢/second", seg)
    if not m: return None
    return {"model": model, "cost": round(secs * float(m.group(1)) / 100, 3), "currency": "USD", "local": True}


def main():
    ap = argparse.ArgumentParser(description="Hedra API v3"); sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("balance"); m = sp.add_parser("models"); m.add_argument("word", nargs="?")
    s = sp.add_parser("schema"); s.add_argument("model")
    e = sp.add_parser("estimate"); e.add_argument("model"); e.add_argument("input")
    r = sp.add_parser("run"); r.add_argument("model"); r.add_argument("input"); r.add_argument("--out", required=True)
    r.add_argument("--max-usd", type=float, default=2.0, help="見積もりがこれを超えたら作らない（既定 $2）"); r.add_argument("--timeout", type=int, default=1800)
    a = ap.parse_args()
    if a.cmd == "balance":
        b = call("GET", "/balance"); print(f"{b['balance']:.2f} {b.get('currency', 'USD')}")
    elif a.cmd == "models":
        req = urllib.request.Request(BASE + "/models?limit=200")
        with urllib.request.urlopen(req, timeout=60) as f: d = json.loads(f.read())
        for x in d["data"]:
            if a.word and a.word.lower() not in json.dumps(x, ensure_ascii=False).lower(): continue
            print(f"{x['id']:32} {x.get('price_description', '')}  — {x.get('description', '')[:90]}")
    elif a.cmd == "schema":   # 入力項目の要約（必須か・型か選択肢・説明）
        d = call("GET", f"/models/{a.model}/openapi.json")
        for name, sch in d.get("components", {}).get("schemas", {}).items():
            if not (name.endswith("Input") or name.lower().endswith("input")): continue
            print(name); req = set(sch.get("required", []))
            for k, v in sch.get("properties", {}).items():
                kind = v.get("enum") or v.get("type") or [x.get("type") or x.get("$ref", "").split("/")[-1] for x in v.get("anyOf", [])]
                rng = {x: v[x] for x in ("minimum", "maximum", "default") if x in v}
                print(f"  {k:24} {'必須' if k in req else '任意'}  {kind} {rng if rng else ''}  {(v.get('description') or '')[:160]}")
    else:
        raw_inp = json.load(open(a.input, encoding="utf-8"))
        est = local_estimate(a.model, raw_inp, os.path.dirname(os.path.abspath(a.input)))   # 声で動かすモデルは API が見積もれない
        inp = resolve(raw_inp, os.path.dirname(os.path.abspath(a.input)))
        if est is None: est = call("POST", f"/models/{a.model}/estimate", body={"input": inp})
        print(f"estimate ${est['cost']:.3f} ({est['model']}{', 声の長さ×1秒の値段で手元計算' if est.get('local') else ''})", file=sys.stderr)
        if a.cmd == "estimate": print(f"{est['cost']:.3f}"); return
        if est["cost"] > a.max_usd: die(f"見積もり ${est['cost']:.3f} が上限 ${a.max_usd} を超えたので作らない", 7)
        sub = call("POST", f"/models/{a.model}", body={"input": inp}); jid = sub["job_id"]
        print(f"job {jid} submitted", file=sys.stderr); t0 = time.time(); last = None
        while True:
            st = call("GET", f"/jobs/{jid}/status")
            s_ = st.get("status")
            if s_ != last: print(f"  {s_} {st.get('progress', '')}", file=sys.stderr); last = s_
            if s_ in ("COMPLETED", "FAILED"): break
            if time.time() - t0 > a.timeout: die(f"{a.timeout} 秒で終わらなかった（job {jid}）", 5)
            time.sleep(8)
        res = call("GET", f"/jobs/{jid}")
        if s_ == "FAILED": die(f"生成に失敗: {json.dumps(res.get('error') or res, ensure_ascii=False)[:600]}", 4)
        outs = [o for o in res.get("outputs", []) if o.get("url")]
        if not outs: die(f"出力が無い: {json.dumps(res, ensure_ascii=False)[:600]}", 4)
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with urllib.request.urlopen(outs[0]["url"], timeout=600) as f, open(a.out + ".part", "wb") as w: w.write(f.read())
        os.replace(a.out + ".part", a.out)
        json.dump(res, open(a.out + ".job.json", "w"), ensure_ascii=False, indent=1)
        print(f"elapsed {round(time.time() - t0)}s, cost ~${est['cost']:.3f}", file=sys.stderr); print(a.out)


if __name__ == "__main__":
    main()
