"""声の確認の止まり所（opt-in）。config.voice.review が "suspects" か "all" のとき、ユーザーが声を聞いて OK を出す
（vm voice <作業フォルダ> approve）まで、書き出し（vm render・vm explain・compose.py）を止める。

理由（2026-11-15、ユーザーの提案）: 口パク・身振り・画面の切り替えは声の時刻で決まる。書き出したあとで 1 行でも声を替えると、
その行から後ろがずれてマスコットから作り直しになる。声を聞く手間を取れるかは状況によるので、既定は止めない（今までどおり）。
承認は master.wav の中身（md5）で控える。承認のあとで声が変われば、もう一度止まる。"""
import hashlib, json, os, sys, time

LEVELS = ("suspects", "all")


def level(cfg):
    """config の voice.review。None（止めない）・"suspects"（疑い所だけ聞く）・"all"（全部聞く）。それ以外は ValueError。"""
    v = (cfg.get("voice") or {}).get("review")
    if v in (None, False, "", "off"): return None
    if v not in LEVELS: raise ValueError(f"voice.review は suspects・all のどちらか（止めないなら書かない）: {v!r}")
    return v


def _md5(path):
    with open(path, "rb") as f: return hashlib.md5(f.read()).hexdigest()


def approve(root):
    """今の master.wav を承認したと控える。返り値は控えたパス。"""
    m = os.path.join(root, "voice", "master.wav")
    if not os.path.exists(m): raise FileNotFoundError(f"声が無い: {m}（vm voice <作業フォルダ> master）")
    out = os.path.join(root, "voice", "approved.json")
    json.dump({"master_md5": _md5(m), "at": time.strftime("%Y-%m-%d %H:%M:%S")}, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


def problem(root, cfg):
    """書き出しを止める理由。止めないなら None。"""
    try: lv = level(cfg)
    except ValueError as x: return str(x)
    if lv is None: return None
    m = os.path.join(root, "voice", "master.wav"); a = os.path.join(root, "voice", "approved.json")
    how = (f"vm voice {root} review で聞き取りを作ってユーザーに渡し、OK が出たら vm voice {root} approve。"
           "止めずに進めるなら config の voice.review を消す")
    if not os.path.exists(m): return None    # 声が無いことは、それぞれのコマンドが先に止める
    if not os.path.exists(a): return f"声の確認待ち（voice.review: {lv}）。{how}"
    try: ok = json.load(open(a, encoding="utf-8")).get("master_md5") == _md5(m)
    except (ValueError, OSError): ok = False
    if not ok: return f"承認のあとで声（master.wav）が変わった（voice.review: {lv}）。{how}"
    return None


def check(root, cfg=None):
    """止める理由があれば終わる（終了コード 7）。"""
    if cfg is None:
        p = os.path.join(root, "config.json")
        cfg = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    why = problem(root, cfg)
    if why:
        print(f"ERROR: {why}", file=sys.stderr, flush=True); sys.exit(7)
