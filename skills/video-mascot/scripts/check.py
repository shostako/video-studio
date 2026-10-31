"""書き出した動画で、各切り替えの前後が実際に変わったかを画素で確かめる（vm render が書いた <出力>.check.json の切り替えの一覧を使う）。
  vm check <動画> [--switches <check.json>] [--crop x,y,w,h] [--shift 秒] [--strict]
    動画        vm render の出力（透明の webm は白に重ねて見る）か、それを主動画に重ねた完成の動画
    --switches  切り替えの一覧（既定は <動画の名前>.check.json）。完成の動画を見るときは vm render の出力の .check.json を渡す
    --crop      完成の動画でマスコットのいる範囲（画素、x,y,幅,高さ）。既定は画面全体
    --shift     動画の時刻 = 切り替えの時刻 + shift 秒（完成の動画で頭を足した・切ったとき）
  判定: 切り替えの直前と直後のコマで変わった画素の割合を、顔を除いて測る。顔は、切り替えも頭の動きも無い区間（話しているだけ）で
    変わった画素（口・まばたき・視線）を全部集めた覆いで、動画そのものから作る（視線は体の切り替えに合わせて先に動くので、
    顔を含めると身振りが消えていても「動いた」に見える）。顔の外で FLOOR の 2 倍を超えれば「動いた」、1.2〜2 倍は「弱い」（目で確かめる）、
    それ以下は「動いていない」。話しているだけの区間が MIN_REST 組に足りなければ顔を外せないので「測れない」。
    結果は <動画の名前>.motion.json。--strict は「動いていない」「測れない」、vm render の検査の問題（.check.json の problems）、
    切り替えがあるのに 1 件も測れなかった、のどれかがあれば終了コード 3。vm render --from で書き出した動画は、その時刻を 0 秒として読む。
"""
import json, os, re, subprocess, sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import die, motion_verdict, switch_spans, rest_pairs

DIFF = 24                                          # 変わった画素とみなす明るさの差（0〜255）
SH_MAX = 360                                       # 測るときの高さ（画素。縮めて速くする）
FLOOR = 0.0005                                     # 顔の外で変わった画素の割合の基準（0.05%。2 倍の 0.1% を超えれば動いた）
GROW = 2                                           # 顔の覆いを広げる画素（縮めた後の画素）
MIN_REST = 3                                       # 顔の覆いを作るのに要る、話しているだけの区間のコマの組の数（足りなければ「測れない」）
LABEL = {"moved": "動いた", "weak": "弱い", "still": "動いていない", "unknown": "測れない"}


def opt(name, default=None, cast=str): return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def probe(path):
    """(幅, 高さ, fps, 符号化の名前, 透明か, 秒)。ffprobe の無い環境（CI の imageio-ffmpeg）でも動くように ffmpeg -i の表示から読む。"""
    if not os.path.exists(path): die(f"動画が無い: {path}")
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", path], capture_output=True, text=True)
    s = r.stderr; v = re.search(r"Stream #0:\d+[^\n]*?: Video: (\w+)[^\n]*?, (\d{2,5})x(\d{2,5})[^\n]*", s)
    d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", s)
    if not v or not d: die(f"動画が読めない: {path}")
    fps = re.search(r"([\d.]+) fps", v.group(0)) or re.search(r"([\d.]+) tbr", v.group(0))
    if not fps: die(f"動画のコマの速さが読めない: {path}")
    alpha = re.search(r"alpha_mode\s*:\s*1", s[v.start():]) is not None   # 映像の流れの情報（Metadata）にある時だけ
    return int(v.group(2)), int(v.group(3)), float(fps.group(1)), v.group(1), alpha, int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))


def read_frames(path, want, crop):
    """動画のうち、コマ番号 want（集合）のコマだけを、白に重ねた明るさ（gray、縮めた物）で {番号: 配列}。"""
    w, h, fps, codec, alpha, _ = probe(path)
    x, y, cw, ch = crop if crop else (0, 0, w, h)
    x, y = max(0, x), max(0, y); cw, ch = min(cw, w - x), min(ch, h - y)
    if cw <= 0 or ch <= 0: die(f"--crop が画面の外: {crop}（動画は {w}x{h}）")
    sh = min(SH_MAX, ch); sw = max(2, round(cw * sh / ch / 2) * 2)
    dec = ["-c:v", "libvpx-vp9"] if (alpha and codec == "vp9") else []   # 透明の vp9 は libvpx でないとアルファが読めない
    pf, nc = ("rgba", 4) if alpha else ("gray", 1)
    rd = subprocess.Popen(["ffmpeg", "-v", "error"] + dec + ["-i", path, "-vf", f"crop={cw}:{ch}:{x}:{y},scale={sw}:{sh}:flags=area",
                           "-f", "rawvideo", "-pix_fmt", pf, "-"], stdout=subprocess.PIPE)
    out, i, last = {}, 0, max(want) if want else -1
    size = sw * sh * nc
    while i <= last:
        b = rd.stdout.read(size)
        if len(b) < size: break
        if i in want:
            a = np.frombuffer(b, np.uint8).reshape(sh, sw, nc).astype(np.float32)
            if alpha:                              # 白に重ねる
                al = a[:, :, 3:4] / 255; a = (a[:, :, :3] * al + 255 * (1 - al)).mean(2)
            else: a = a[:, :, 0]
            out[i] = a
        i += 1
    rd.kill(); rd.wait()
    return out


def changed(a, b): return np.abs(a - b) > DIFF


def change(a, b, mask=None):
    """変わった画素の割合（画面全体の画素の数で割る）。mask（True が顔）の中は数えない。"""
    c = changed(a, b)
    if mask is not None: c = c & ~mask
    return float(c.mean())


def face_mask(pairs, grow=GROW):
    """話しているだけの区間のコマの組 [(a, b), ...] で変わった画素を全部集めて、grow 画素広げた覆い（True が顔）。組が無ければ None。"""
    if not pairs: return None
    m = np.zeros(pairs[0][0].shape, bool)
    for a, b in pairs: m |= changed(a, b)
    if grow > 0:
        import cv2
        m = cv2.dilate(m.astype(np.uint8), np.ones((2 * grow + 1, 2 * grow + 1), np.uint8)) > 0
    return m


def main():
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    if not a: die("使い方: vm check <動画> [--switches <check.json>] [--crop x,y,w,h] [--shift 秒] [--strict]")
    video = a[0]; jp = opt("--switches", os.path.splitext(video)[0] + ".check.json")
    if not os.path.exists(jp): die(f"切り替えの一覧が無い: {jp}（vm render の出力の .check.json を --switches で渡す）")
    J = json.load(open(jp)); sws = J["switches"]
    crop = tuple(int(v) for v in opt("--crop").split(",")) if opt("--crop") else None
    if crop is not None and len(crop) != 4: die("--crop は x,y,幅,高さ")
    shift = opt("--shift", 0.0, float)
    _, _, vfps, _, _, vdur = probe(video)
    off = float(J["from"])                             # vm render --from で書き出した動画は、その時刻が動画の 0 秒
    t_lo, t_hi = off, min(float(J["to"]), off + vdur - shift)
    gap = max(2 / vfps, 2 / float(J["fps"]))
    spans = switch_spans(sws, gap, t_lo, t_hi)
    pairs = [s for s in spans if isinstance(s, tuple)]
    widths = sorted(s[1] - s[0] for s in pairs)
    rest = rest_pairs(sws, J.get("head_spans", []), widths[len(widths) // 2] if widths else 0.5, t_lo, t_hi)
    fi = lambda t: int(round((t - off + shift) * vfps))
    want = {fi(t) for s in pairs for t in s} | {fi(t) for p in rest for t in p}
    fr = read_frames(video, want, crop)
    rp = [(fr[fi(p)], fr[fi(q)]) for p, q in rest if fi(p) in fr and fi(q) in fr]
    mask = face_mask(rp) if len(rp) >= MIN_REST else None   # 足りなければ顔を外せない＝測れない（画面全体で測ると目の変化で「動いた」に見える）
    rc = [change(p, q) for p, q in rp]
    noise = float(np.percentile(rc, 90)) if rc else None   # 参考: 話しているだけの変化（顔を含む）
    res = []
    for sw, sp in zip(sws, spans):
        r = {"at": sw["at"], "from": sw["from"], "to": sw["to"], "engine": sw.get("engine"), "render": sw.get("status")}
        if sp == "unclean": r["verdict"] = "unknown"; r["note"] = "前後の切り替えと重なっていて、混ざらない直前・直後のコマが取れない"
        elif sp is None or fi(sp[0]) not in fr or fi(sp[1]) not in fr: r["verdict"] = "skip"
        else:
            A, B = fr[fi(sp[0])], fr[fi(sp[1])]; r["change_face"] = round(change(A, B), 5)
            if mask is None: r["verdict"] = "unknown"
            else: c = change(A, B, mask); r["change"] = round(c, 5); r["verdict"] = motion_verdict(c, FLOOR)
        res.append(r)
    cnt = {}
    for r in res: cnt[r["verdict"]] = cnt.get(r["verdict"], 0) + 1
    meas = sum(v for k, v in cnt.items() if k != "skip")
    print(f"動画の測定: {meas} 件（" + "、".join(f"{LABEL[k]} {cnt[k]}" for k in ("moved", "weak", "still", "unknown") if cnt.get(k)) + "）"
          + (f" 顔の外で {2 * FLOOR * 100:.2f}% を超えれば動いた。顔の覆い {mask.mean() * 100:.1f}%（話しているだけの区間 {len(rp)} 組から）" if mask is not None
             else f" 話しているだけの区間が {len(rp)} 組しか無く（{MIN_REST} 組要る）、顔を外せないので測れない"))
    for r in res:
        if r["verdict"] in ("still", "weak"):
            mark = "✗" if r["verdict"] == "still" else "△"
            print(f"  {mark} {r['at']:.2f} 秒 {r['from']}→{r['to']}（{r['engine']}）: {LABEL[r['verdict']]}  顔の外の変化 {r['change'] * 100:.3f}%（顔を含めると {r['change_face'] * 100:.3f}%）")
        elif r.get("note"): print(f"  ? {r['at']:.2f} 秒 {r['from']}→{r['to']}（{r['engine']}）: {LABEL[r['verdict']]}（{r['note']}）")
    if J.get("problems"): print(f"  vm render の切り替えの検査でも問題が {J['problems']} 件（{jp}）")
    nsw = sum(s.get("status") != "skip" and s["from"] != s["to"] for s in sws)
    if nsw and not meas: print(f"  切り替えが {nsw} 件あるのに 1 件も測れなかった（--from・--shift・動画の長さを見直す）")
    json.dump({"video": os.path.abspath(video), "switches_file": os.path.abspath(jp), "crop": crop, "shift": shift, "floor": FLOOR,
               "face_mask": None if mask is None else round(float(mask.mean()), 5), "noise_with_face": noise, "rest_pairs": len(rp), "switches": res},
              open(os.path.splitext(video)[0] + ".motion.json", "w"), ensure_ascii=False, indent=1)
    bad = cnt.get("still", 0) + cnt.get("unknown", 0) + (J.get("problems") or 0) + (1 if nsw and not meas else 0)
    if bad and "--strict" in sys.argv:
        die(f"動いていない切り替え {cnt.get('still', 0)} 件、測れない {cnt.get('unknown', 0)} 件、書き出しの検査の問題 {J.get('problems') or 0} 件"
            + ("、1 件も測れていない" if nsw and not meas else ""), 3)


if __name__ == "__main__":
    main()
