"""主となる動画の上にマスコットを重ねて、声を足して1本にする。
  vm overlay <主動画.mp4> <作業フォルダ> --out 出力.mp4 [--side left|right|center] [--height 0.9] [--x PX] [--bottom PX] [--start 秒]
             [--mode alpha|multiply] [--duck 0.25] [--main-volume 1.0]
  alpha    : out/mascot.webm（背景透明）を重ねる。どんな主動画にも使える
  multiply : out/mascot_white.mp4（背景が白）を乗算で重ねる。主動画の背景が白っぽいときだけ
  --height 主動画の高さに対するマスコットの高さの割合（既定 0.9）  --start マスコットの声が始まる主動画の時刻（既定 0）
  --duck   マスコットが喋っている間、主動画の音をこの倍率まで下げる（既定 0.25。1 で下げない）
主動画の音は残す。マスコットの声は work/voice/master.wav。

置き方のプリセットと登場・退場（どれも opt-in。付けなければ上のとおり）:
  --preset left|right|center|corner-left|corner-right  主動画の画面比で置く（placement.PRESETS）。--height / --bottom / --x を一緒に書くとそちらが優先
  --safe 0.05   プリセットの安全領域（上下左右の余白の割合）。横の位置はこの内側で決める
  --enter fade|slide|none  --exit fade|slide|none  登場・退場の動き（既定 none）。slide は寄っている側の画面の外から（中央は下から）
  --move-dur 0.5  登場・退場にかける秒数   --ease out-cubic|linear|in-out-sine|out-back  slide の動き方（out-back は少し行き過ぎて戻る）"""
import json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import Proj, die
import placement as pl


def probe(p, entries="stream=codec_type,width,height,duration"):
    return subprocess.run(["ffprobe", "-v", "error", "-show_entries", f"{entries}:format=duration", "-of", "json", p], capture_output=True, text=True).stdout


a = [x for x in sys.argv[1:] if not x.startswith("--")]
def opt(name, default=None, cast=str): return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
if len(a) < 2 or "--out" not in sys.argv: die("使い方: vm overlay <主動画> <作業フォルダ> --out 出力.mp4 [--side left|right|center] [--height 0.9]")
main_p = os.path.abspath(a[0]); P = Proj(a[1]); OUT = os.path.abspath(opt("--out")); MODE = opt("--mode", "alpha")
j = json.loads(probe(main_p)); vs = [s for s in j["streams"] if s["codec_type"] == "video"][0]; has_a = any(s["codec_type"] == "audio" for s in j["streams"])
MW, MH = int(vs["width"]), int(vs["height"]); MDUR = float(j["format"]["duration"])
mp = P.p("out", "mascot.webm" if MODE == "alpha" else "mascot_white.mp4")
if not os.path.exists(mp): die(f"マスコットの動画が無い: {mp}（先に vm render --mode {MODE}）")
mj = json.loads(probe(mp)); mvs = [s for s in mj["streams"] if s["codec_type"] == "video"][0]; OW, OH = int(mvs["width"]), int(mvs["height"])
PRESET = opt("--preset")
if PRESET is None:
    H = int(round(MH * opt("--height", 0.9, float) / 2) * 2); W = int(round(OW * H / OH / 2) * 2)
    side = opt("--side", "left"); bottom = opt("--bottom", 0, int)
    X = opt("--x", None, int)
    if X is None: X = {"left": 0, "right": MW - W, "center": (MW - W) // 2}[side]
    Y = MH - H - bottom; AX = pl.anchor_of(X, W, MW)
else:
    if "--side" in sys.argv: die("--preset と --side は一緒に使えない（横の位置はプリセットが決める。細かく動かすなら --x）")
    if PRESET not in pl.PRESETS: die(f"知らないプリセット: {PRESET}（{', '.join(pl.PRESETS)}）")
    W, H, X, Y, notes = pl.preset_geometry(PRESET, MW, MH, OW, OH, opt("--safe", pl.SAFE_DEFAULT, float), opt("--height", None, float), opt("--bottom", None, int))
    if opt("--x", None, int) is not None: X = opt("--x", None, int)
    AX = pl.PRESETS[PRESET]["ax"] if "--x" not in sys.argv else pl.anchor_of(X, W, MW)
    for n in notes: print("注意:", n, file=sys.stderr)
    print(f"プリセット {PRESET}: 大きさ {W}x{H}、位置 ({X}, {Y})", file=sys.stderr)
ENTER, EXIT = opt("--enter", "none"), opt("--exit", "none"); EASE = opt("--ease", "out-cubic")
for nm, v, ok in (("--enter", ENTER, pl.MOVES), ("--exit", EXIT, pl.MOVES), ("--ease", EASE, pl.EASES)):
    if v not in ok: die(f"{nm} は {' / '.join(ok)} のどれか（{v} は知らない）")
start = opt("--start", 0.0, float); duck = opt("--duck", 0.25, float); mvol = opt("--main-volume", 1.0, float)
voice = P.p("voice", "master.wav")
args = ["ffmpeg", "-v", "error", "-y", "-i", main_p]
args += (["-c:v", "libvpx-vp9", "-i", mp] if MODE == "alpha" else ["-i", mp]) + ["-i", voice]
# 主動画の外にはみ出す分（--x が負、--bottom が負など）は先に切り落とす。pad は負の位置を「中央寄せ」と解釈するため（2026-10-14 実測）
cl, ct = max(0, -X), max(0, -Y); cw, ch = min(W, MW - X) - cl, min(H, MH - Y) - ct
if cw <= 0 or ch <= 0: die("マスコットが主動画の外に出ている（--x / --bottom を見直す）")
crop = f",crop={cw}:{ch}:{cl}:{ct}" if (cl or ct or cw < W or ch < H) else ""
X, Y = max(0, X), max(0, Y)
moves, fades, slides = "", [], (ENTER == "slide", EXIT == "slide")
if ENTER != "none" or EXIT != "none":
    # 出ている間 = 主動画の start からマスコットの動画の終わりまで（主動画の終わりで切れる）
    end_local = min(float(mj["format"]["duration"]), MDUR - start)
    d_in, d_out = pl.fit_durations(end_local, opt("--move-dur", 0.5, float) if ENTER != "none" else 0.0, opt("--move-dur", 0.5, float) if EXIT != "none" else 0.0)
    fades = pl.fade_filters(MODE, d_in, end_local, d_out, ENTER == "fade", EXIT == "fade")
    if any(slides):
        X0, Y0 = pl.slide_from(AX, X, Y, cw, ch, MW, MH)
        ex = pl.slide_expr(X, X0, start, d_in, start + end_local - d_out, d_out, EASE, *slides)
        ey = pl.slide_expr(Y, Y0, start, d_in, start + end_local - d_out, d_out, EASE, *slides)
        moves = f"x='{ex}':y='{ey}':eval=frame"
fades = "".join("," + x for x in fades)
f = [f"[1:v]scale={W}:{H}{crop}{fades},setpts=PTS+{start}/TB[m]"]
if MODE == "alpha": f.append(f"[0:v][m]overlay={moves or f'{X}:{Y}'}:eof_action=pass:format=auto[v]")
elif moves:   # 動く位置は pad では指定できないので、主動画と同じ大きさの白い板に重ねてから乗算する
    f += ["[0:v]split=2[mv0][bg0]", "[bg0]drawbox=x=0:y=0:w=iw:h=ih:color=0xfdfdfd:t=fill[bg]",
          f"[bg][m]overlay={moves}:eof_action=pass,format=gbrp[mp]", "[mv0]format=gbrp[mv]", "[mv][mp]blend=all_mode=multiply,format=yuv420p[v]"]
else:   # 乗算は両方を同じ形式（gbrp）にそろえてから。形式が違うと色が緑にずれる（2026-10-12 実測）
    f += [f"[m]pad={MW}:{MH}:{X}:{Y}:color=0xfdfdfd,format=gbrp[mp]", "[0:v]format=gbrp[mv]", "[mv][mp]blend=all_mode=multiply,format=yuv420p[v]"]
if has_a:
    f.append(f"[0:a]aresample=48000,volume={mvol}[ma]")
    if duck < 1.0:
        f += [f"[2:a]aresample=48000,adelay={int(start * 1000)}:all=1,asplit=2[vsc][vmix]",
              f"[ma][vsc]sidechaincompress=threshold=0.02:ratio={max(2, round(1 / duck * 2))}:attack=20:release=400[dk]", "[dk][vmix]amix=inputs=2:normalize=0:duration=first[a]"]
    else:
        f += [f"[2:a]aresample=48000,adelay={int(start * 1000)}:all=1[vmix]", "[ma][vmix]amix=inputs=2:normalize=0:duration=first[a]"]
else:
    f.append(f"[2:a]aresample=48000,adelay={int(start * 1000)}:all=1[a]")
r = subprocess.run(args + ["-filter_complex", ";".join(f), "-map", "[v]", "-map", "[a]", "-t", f"{MDUR}", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", OUT])
if r.returncode: die("重ねの書き出しに失敗", 6)
print(OUT)
