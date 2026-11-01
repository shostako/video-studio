"""マスコットのパック（基準キャラの蘭・凜）を GitHub Releases から取ってくる・公開用に書き出す。
  vm packs                      リポの控え（data/packs.json）のパックが手元にあって版が合うかを一覧する（足りない・古ければ終了コード 1）
  vm packs fetch [名前 ...]     足りない・古いパックを取ってきて展開する（ハッシュを確かめる。古い版は <パック>.old-<時刻> に退避し、
                                そのパックから作った作業フォルダの作り置きのリンクを退避先へ向け直す）。名前を書かなければ全部
  vm packs export <パック> <出力.zip> --version 版
                                パックを公開用の zip にする（手元のパスを外し、版を pack.json の release に書く。中身の一覧も出す）
置き場は <VIDEO_SCENE_HOME>/packs/<名前>（既定 ~/.local/share/video-scene/packs）。控えの url・sha256・size・version は
export の出力から書く。リポを同期して setup.sh（か vm packs fetch）を回せば、どの PC にも同じ版のパックがそろう。"""
import argparse, hashlib, json, os, shutil, sys, tempfile, time, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import die

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "..", "data", "packs.json")


LICENSE = """{name}（video-studio のマスコットのパック、版 {version}）

このパックの絵・部品・姿勢の切り替えの作り置きは CC0 1.0（パブリックドメイン）で配る。
https://creativecommons.org/publicdomain/zero/1.0/deed.ja
作り方: 絵は ChatGPT（Codex）の画像生成、姿勢の切り替えは Wan2.2 I2V（Apache 2.0）と Lightning の LoRA（Apache 2.0）、
コマの補間は RIFE（MIT）。使い方は https://github.com/shostako/video-studio の README。
声（Irodori-TTS）を付けて使うときは、Irodori-TTS の利用条件（実在の人物のなりすまし・誤情報の作成に使わない）を守る。
"""


def packs_dir():
    return os.path.join(os.environ.get("VIDEO_SCENE_HOME") or os.path.expanduser("~/.local/share/video-scene"), "packs")


def manifest(path=None):
    p = path or os.environ.get("VM_PACKS_MANIFEST") or MANIFEST
    try: return json.load(open(p, encoding="utf-8")).get("packs", [])
    except (OSError, ValueError) as e: die(f"パックの控えが読めない: {p}（{e}）")


def installed_version(name, root=None):
    """手元のパックの版（pack.json の release）。パックが無ければ None、版が書いてなければ ""。"""
    pj = os.path.join(root or packs_dir(), name, "pack.json")
    if not os.path.exists(pj): return None
    try: return json.load(open(pj, encoding="utf-8")).get("release", "")
    except (OSError, ValueError): return ""


def status(entries, root=None):
    """[(名前, 控えの版, 手元の版, "ok"|"missing"|"outdated"), ...]"""
    out = []
    for e in entries:
        v = installed_version(e["name"], root)
        out.append((e["name"], e["version"], v, "ok" if v == e["version"] else ("missing" if v is None else "outdated")))
    return out


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def download(url, dst):
    """url（http(s) か file:// か手元のパス）を dst に写す。"""
    if url.startswith("file://") or os.path.exists(url):
        shutil.copyfile(url[7:] if url.startswith("file://") else url, dst); return
    import urllib.request
    with urllib.request.urlopen(url, timeout=60) as r, open(dst, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0); got = 0; last = 0
        while True:
            b = r.read(1 << 20)
            if not b: break
            f.write(b); got += len(b)
            if total and time.time() - last > 5: print(f"  {got / 1e6:.0f}/{total / 1e6:.0f} MB", flush=True); last = time.time()


def install(e, root=None):
    """控えの 1 件を取ってきて展開する。古い版は退避し、作業フォルダのリンクを向け直す。"""
    root = root or packs_dir(); os.makedirs(root, exist_ok=True)
    name = e["name"]; dst = os.path.join(root, name)
    tmpd = tempfile.mkdtemp(prefix=f".{name}-dl-", dir=root)
    try:
        zp = os.path.join(tmpd, f"{name}.zip")
        print(f"{name}: 取ってくる（{e.get('size', 0) / 1e6:.0f} MB）{e['url']}", flush=True)
        download(e["url"], zp)
        if e.get("sha256") and sha256(zp) != e["sha256"]: die(f"{name}: ハッシュが控えと合わない（壊れたか、別の版）。取り直す")
        ex = os.path.join(tmpd, "x")
        with zipfile.ZipFile(zp) as z:
            for m in z.namelist():                 # zip の外へ書く名前は止める
                if m.startswith("/") or ".." in m.split("/"): die(f"{name}: zip に置き場の外を指す名前がある: {m}")
            z.extractall(ex)
        src = os.path.join(ex, name)
        if not os.path.exists(os.path.join(src, "pack.json")): die(f"{name}: zip の中に {name}/pack.json が無い")
        if installed_version(name, ex) != e["version"]: die(f"{name}: zip の版（{installed_version(name, ex)}）が控え（{e['version']}）と違う")
        import pack as P_                          # 展開で更新時刻が展開の時刻になる。中割りの続き（chain）が古く見えないよう、vm pack と同じにそろえる
        try: pairs = [tuple(p_) for p_ in json.load(open(os.path.join(src, "config.json"), encoding="utf-8")).get("pairs", [])]
        except (OSError, ValueError): pairs = []
        P_.settle_mtimes(src, pairs)
        if os.path.exists(dst):
            old = P_.unique(dst + ".old-" + time.strftime("%Y%m%d_%H%M%S")); os.rename(dst, old)
            print(f"{name}: 前の版を {old} に退避した", flush=True); P_.repin(dst, old)
        os.rename(src, dst)
        print(f"{name}: {e['version']} を {dst} に置いた", flush=True)
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


def export(pack, out, version):
    """パックを公開用の zip にする。手元のパス（pack.json の sources・poses・pairs の出どころ、config の from_pack）を外し、
    pack.json に release を書く。作業用の out/・voice/ の中身や reject/ は入れない。"""
    pack = os.path.abspath(pack); name = os.path.basename(pack)
    if not os.path.exists(os.path.join(pack, "pack.json")): die(f"パックではない（pack.json が無い）: {pack}")
    tmpd = tempfile.mkdtemp(prefix=f".{name}-export-")
    try:
        dst = os.path.join(tmpd, name)
        shutil.copytree(pack, dst, ignore=shutil.ignore_patterns("reject", "*.old-*", "*.tmp-*", "__pycache__"))
        for sub in ("out", "voice"):
            d = os.path.join(dst, sub); shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
        man = json.load(open(os.path.join(dst, "pack.json"), encoding="utf-8"))
        base = lambda v: os.path.basename(v.rstrip("/")) if isinstance(v, str) else v
        man["sources"] = [base(s) for s in man.get("sources", [])]
        for k in ("poses", "pairs"):
            if isinstance(man.get(k), dict): man[k] = {a: base(v) for a, v in man[k].items()}
        man.pop("workspaces", None); man["release"] = version
        json.dump(man, open(os.path.join(dst, "pack.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        open(os.path.join(dst, "LICENSE.txt"), "w", encoding="utf-8").write(LICENSE.format(name=name, version=version))
        cf = os.path.join(dst, "config.json"); c = json.load(open(cf, encoding="utf-8")); c.pop("from_pack", None); c["name"] = name
        json.dump(c, open(cf, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        home = os.path.expanduser("~")                 # 手元のパスが残っていないか（json だけ見る）
        for r_, _, fs in os.walk(dst):
            for f in fs:
                if f.endswith(".json") and home in open(os.path.join(r_, f), encoding="utf-8", errors="ignore").read():
                    die(f"手元のパスが残っている: {os.path.relpath(os.path.join(r_, f), tmpd)}")
        out = os.path.abspath(out); os.makedirs(os.path.dirname(out), exist_ok=True)
        kinds = {}
        with zipfile.ZipFile(out + ".part", "w", zipfile.ZIP_STORED) as z:   # 絵は PNG・WebP で圧縮済み
            for r_, ds, fs in os.walk(tmpd):
                ds.sort()
                for f in sorted(fs):
                    p = os.path.join(r_, f); rel = os.path.relpath(p, tmpd); z.write(p, rel)
                    k = os.path.splitext(f)[1] or f; kinds[k] = kinds.get(k, 0) + 1
            for r_, ds, fs in os.walk(tmpd):          # 空の out/・voice/ も入れる
                if not ds and not fs: z.writestr(os.path.relpath(r_, tmpd) + "/", "")
        os.replace(out + ".part", out)
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)
    entry = {"name": name, "version": version, "size": os.path.getsize(out), "sha256": sha256(out)}
    print(f"中身: {', '.join(f'{k} {v}' for k, v in sorted(kinds.items()))}")
    print(json.dumps(entry, ensure_ascii=False))
    return entry


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="status", choices=["status", "fetch", "export"])
    ap.add_argument("args", nargs="*"); ap.add_argument("--version"); ap.add_argument("--manifest")
    a = ap.parse_args()
    if a.cmd == "export":
        if len(a.args) != 2 or not a.version: die("使い方: vm packs export <パック> <出力.zip> --version 版")
        export(a.args[0], a.args[1], a.version); return
    entries = manifest(a.manifest)
    if a.cmd == "fetch":
        want = [e for e in entries if not a.args or e["name"] in a.args]
        if a.args and len(want) != len(a.args): die(f"控えに無いパック: {sorted(set(a.args) - {e['name'] for e in want})}")
        for name, ver, have, st in status(want):
            if st == "ok": print(f"{name}: {ver} はそろっている"); continue
            install(next(e for e in want if e["name"] == name))
        return
    bad = 0
    for name, ver, have, st in status(entries):
        print(f"{'ok  ' if st == 'ok' else 'NG  '} {name}: 控え {ver}、手元 {have if have is not None else '無し'}" + ("" if st == "ok" else "（vm packs fetch）"))
        bad += st != "ok"
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
