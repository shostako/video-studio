"""中割りのコマ補間（config.interp、opt-in）。描いた絵（端の姿勢と中割り）の間を RIFE で細かくし、作業フォルダにためておく。
vm render が使う。単独では動かさない。
  ためる所: <作業フォルダ>/ib_interp/<前>_<次>_x<倍>_<モデル>/f<j>.png（j=1..div*倍-1。j が倍の倍数の所は描いた中割りそのもの）
  元の絵か設定が変わったら作り直す（stamp.json で比べる）。
RIFE は rife-ncnn-vulkan（Windows 版の exe を WSL から呼ぶ）。入出力は exe が読み書きできる Windows 側の一時フォルダ（interp.tmp）。"""
import json, os, shutil, subprocess

import cv2

from lib import die


def _winpath(p):
    r = subprocess.run(["wslpath", "-w", p], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else p


def _stamp(srcs, cfg):
    return {"src": [[os.path.basename(p), os.path.getmtime(p), os.path.getsize(p)] for p in srcs],
            "mult": cfg["mult"], "model": cfg["model"]}


def dense_paths(proj, pa, pb, div, cfg, log=None):
    """組 pa→pb（pairs の向き）の補間した列のパス（div*mult-1 枚、k=j/mult の順）。無ければ RIFE で作る。"""
    mult = cfg["mult"]
    srcs = [proj.pose_path(pa)] + [proj.ib_path(pa, pb, k) for k in range(1, div)] + [proj.pose_path(pb)]
    miss = [p for p in srcs if not os.path.exists(p)]
    if miss: die(f"補間の元の絵が無い: {miss}")
    out = proj.p("ib_interp", f"{pa}_{pb}_x{mult}_{cfg['model']}")
    want = [os.path.join(out, f"f{j}.png") for j in range(1, div * mult)]
    st = _stamp(srcs, cfg); sf = os.path.join(out, "stamp.json")
    if os.path.exists(sf) and all(os.path.exists(p) for p in want):
        try:
            if json.load(open(sf)) == json.loads(json.dumps(st)): return want
        except (OSError, ValueError): pass
    if not os.path.exists(cfg["exe"]): die(f"RIFE が無い: {cfg['exe']}（config.interp.exe を直すか、interp を外す）")
    imgs = [cv2.imread(p) for p in srcs]; h, w = imgs[0].shape[:2]
    imgs = [im if im.shape[:2] == (h, w) else cv2.resize(im, (w, h), interpolation=cv2.INTER_AREA) for im in imgs]
    tmp = os.path.join(cfg["tmp"], f"{os.path.basename(proj.root)}_{pa}_{pb}")
    shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp + "/in"); os.makedirs(tmp + "/out")
    for i, im in enumerate(imgs): cv2.imwrite(f"{tmp}/in/{i:04d}.png", im)
    n_out = (len(imgs) - 1) * mult + 1           # -n は列の末尾の外まで割り付けるので、多めに頼んで最後の原画までで切る
    r = subprocess.run([cfg["exe"], "-i", _winpath(tmp + "/in"), "-o", _winpath(tmp + "/out"), "-m", cfg["model"], "-n", str(n_out + mult - 1)],
                       cwd=os.path.dirname(cfg["exe"]), capture_output=True, text=True)
    outs = sorted(os.listdir(tmp + "/out"))[:n_out]
    if r.returncode != 0 or len(outs) < n_out: die(f"RIFE が失敗した（{pa}→{pb}、終了コード {r.returncode}）: {(r.stdout + r.stderr)[-800:]}")
    os.makedirs(out, exist_ok=True)
    for j in range(1, div * mult):
        if j % mult == 0: cv2.imwrite(want[j - 1], imgs[j // mult])          # 描いた中割りはそのまま使う
        else: shutil.copyfile(os.path.join(tmp, "out", outs[j]), want[j - 1])
    json.dump(st, open(sf, "w")); shutil.rmtree(tmp, ignore_errors=True)
    if log: log(f"補間: {pa}→{pb} を {div * mult - 1} 枚に（RIFE {cfg['model']}）")
    return want
