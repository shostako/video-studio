"""画面操作の解説動画を、型を選んで 1 本に組む入口（撮影・台本・声は先に用意する）。
  vm explain <作業フォルダ> --shots <撮影フォルダ> --scenes <scenes.py> --style cursor|wipe|full --out 出力.mp4
             [--scale 0.73] [--chapters 章.json] [--clip-bottom 948] [--clip-right 1895] [--keep]

  型（2026-11-01 にユーザーと決めた 3 つ）:
    cursor  カーソルだけ。画面を全面に出し、章が替わった所に左上へ見出しを数秒出す（マスコットなし）
    wipe    画面を --scale に縮めて右に寄せ、余白の左下に丸いワイプの顔（身振りなしで口パク）。見出しは余白の左上
    full    同じ割り付けで、余白に小さな全身のマスコット（台本の身振り＝config.events で動く）。見出しは余白の左上
  作業フォルダ: 声（config.json の voice.lines と voice/master.wav・timing.json。vm voice で作る）。wipe と full はマスコットの
    作業フォルダ（vm pack <パック> --new で作るのが楽。Wan・RIFE の無い PC でも作り置きのある身振りは書き出せる）
  流れ: screen-explainer の compose.py で主動画 → （wipe・full）vm render の下見（--strict。足りない作り置き・口の問題で止まる）
        → vm render → vm layout → （full）vm check。途中の物は毎回新しく作る <出力の名前>_work_<ランダム>/ に置き、--keep が無ければ最後に消す
  使える段は既存のコマンドを順に呼ぶだけ。1 段ずつ確かめたいときは、それぞれのコマンドを直に使う。"""
import json, os, re, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import die

HERE = os.path.dirname(os.path.abspath(__file__))
COMPOSE = os.path.join(HERE, "..", "..", "screen-explainer", "scripts", "compose.py")


def step(title, cmd):
    """1 段を動かす。失敗したらその段の名前で止める。標準出力を返す。"""
    print(f"== {title}", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    tail = [l for l in (r.stdout + r.stderr).splitlines() if l.strip() and not re.match(r"^\s*(\d+/\d+|[\d.]+s / [\d.]+s)\s*$", l)]   # 進み具合の行は出さない
    for l in tail[-8:]: print("   " + l, flush=True)
    if r.returncode != 0:
        print((r.stdout + r.stderr)[-3000:], file=sys.stderr)
        die(f"{title} で止まった（終了コード {r.returncode}）", r.returncode if r.returncode in (2, 3) else 2)
    return r.stdout


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work"); ap.add_argument("--shots", required=True); ap.add_argument("--scenes", required=True)
    ap.add_argument("--style", required=True, choices=["cursor", "wipe", "full"]); ap.add_argument("--out", required=True)
    ap.add_argument("--scale", default="0.73"); ap.add_argument("--chapters"); ap.add_argument("--clip-bottom"); ap.add_argument("--clip-right")
    ap.add_argument("--keep", action="store_true")
    A = ap.parse_args()
    work, shots, scenes, style, out = os.path.abspath(A.work), A.shots, A.scenes, A.style, A.out
    for p in (work, shots, scenes, COMPOSE):
        if not os.path.exists(p): die(f"無い: {p}")
    if not os.path.exists(os.path.join(work, "voice", "master.wav")): die(f"声が無い: {work}/voice/master.wav（vm voice {work} synth → master）")
    out = os.path.abspath(out); os.makedirs(os.path.dirname(out), exist_ok=True)
    import tempfile                                # 途中の置き場は毎回新しく作る（既にあるフォルダを使って消さない）
    tmp = tempfile.mkdtemp(prefix=os.path.splitext(os.path.basename(out))[0] + "_work_", dir=os.path.dirname(out))
    py = sys.executable; vm = lambda *x: [py, "-B", os.path.join(HERE, x[0] + ".py"), *x[1:]]
    comp = [py, COMPOSE, "--shots", shots, "--voice", work, "--scenes", scenes]
    for k, v in (("--clip-bottom", A.clip_bottom), ("--clip-right", A.clip_right), ("--chapters", A.chapters)):
        if v: comp += [k, v]

    if style == "cursor":
        step("画面の組み立て（カーソルだけ）", comp + ["--out", out])
    else:
        main_mp4 = os.path.join(tmp, "main.mp4")
        step(f"画面の組み立て（余白あり・倍率 {A.scale}）", comp + ["--layout", "margin", "--scale", A.scale, "--out", main_mp4])
        face = os.path.join(tmp, "mascot.webm"); extra = ["--no-events", "--crop", "face"] if style == "wipe" else []   # ワイプは顔の周りだけを書き出す（速い）
        step("マスコットの下見", vm("render", work, "--mode", "alpha", "--out", face, "--check-only", "--strict", *extra))
        step("マスコットの書き出し", vm("render", work, "--mode", "alpha", "--out", face, "--strict", *extra))
        lay = step("余白に置く", vm("layout", main_mp4, work, "--mascot", face, "--style", "full" if style == "full" else "wipe", "--out", out, "--full"))
        if style == "full":
            crop = next((l.split()[1] for l in lay.splitlines() if l.startswith("CROP ")), None)
            if not crop: die("vm layout が CROP を出さなかった")
            step("身振りが出たかの測定", vm("check", out, "--switches", os.path.splitext(face)[0] + ".check.json", "--crop", crop))
            mj = os.path.splitext(out)[0] + ".motion.json"
            res = json.load(open(mj)).get("switches", []) if os.path.exists(mj) else []
            bad = [r for r in res if r.get("verdict") == "still"]; soft = [r for r in res if r.get("verdict") in ("weak", "unknown")]
            if soft: print(f"   注意: 弱い・測れない切り替え {len(soft)} 件（短い動画や話していない所が少ないと測れない。{mj} を見て、気になる所は目で確かめる）", flush=True)
            if bad: die(f"身振りが出ていない切り替えが {len(bad)} 件ある: {[(r['at'], r['from'], r['to']) for r in bad]}（{mj}）", 3)
    if not A.keep: shutil.rmtree(tmp, ignore_errors=True)
    else: print(f"途中の物: {tmp}", flush=True)
    print(f"できた: {out}（{style}）", flush=True)


if __name__ == "__main__":
    main()
