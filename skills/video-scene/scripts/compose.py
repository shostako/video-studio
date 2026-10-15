"""compose.py — scene.json から HyperFrames の作品を組み立てて MP4 に書き出す。

使い方:
  vs compose scene.json [--out 出力.mp4] [--draft] [--no-render]

  - scene.json の書き方は references/scene-spec.md
  - 作業用の HyperFrames プロジェクトは scene.json の隣の hf/ に毎回作り直す（何度実行しても同じ結果）
  - 動きはすべてコマごとの値を計算して置く（GSAP の set だけ使う）。シークしても崩れない
  - 書き出し前に hyperframes lint を通す。エラーがあれば止まる
終了コード: 0 成功（標準出力に保存先） 2 scene.json の誤り 6 lint/書き出しの失敗
"""
import argparse, html, json, math, os, re, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import probe, out_path, atomic_copy, die

HF = "hyperframes@0.8.146"
FONTS = ("https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700"
         "&family=M+PLUS+Rounded+1c:wght@800&family=Noto+Sans+JP:wght@700;900&display=block")


def spring(f, fps, damping, stiffness, mass=1.0):
    """Remotion の spring と同じ減衰振動（0→1）。"""
    if f <= 0: return 0.0
    t = f / fps; w0 = math.sqrt(stiffness / mass); z = damping / (2 * math.sqrt(stiffness * mass))
    if z >= 1: return 1 - math.exp(-w0 * t) * (1 + w0 * t)
    wd = w0 * math.sqrt(1 - z * z)
    return 1 - math.exp(-z * w0 * t) * (math.cos(wd * t) + (z * w0 / wd) * math.sin(wd * t))


def ease_inout(p):
    p = min(1, max(0, p)); return 0.5 - 0.5 * math.cos(math.pi * p)


class Scene:
    def __init__(self, path, out_dir):
        self.root = os.path.dirname(os.path.abspath(path))
        self.s = json.load(open(path, encoding="utf-8"))
        self.fps = self.s.get("fps", 30); self.dur = float(self.s["duration"]); self.N = int(round(self.dur * self.fps))
        self.W, self.H = self.s.get("size", [1920, 1080])
        self.proj = out_dir; self.assets = os.path.join(out_dir, "assets")
        self.tracks = []     # (selector, [props or None per frame])
        self.html = {"camera": [], "screen": [], "audio": []}
        self.css = []; self.n_asset = 0

    def P(self, p): return p if os.path.isabs(p) else os.path.join(self.root, p)
    def sec(self, f): return round(f / self.fps, 4)
    def fr(self, t): return int(round(t * self.fps))

    def asset(self, src, name=None):
        src = self.P(src)
        if not os.path.exists(src): die(f"素材が無い: {src}", 2)
        self.n_asset += 1; name = name or f"a{self.n_asset}_{os.path.basename(src)}"
        dst = os.path.join(self.assets, name); shutil.copyfile(src, dst); return f"assets/{name}"

    def track(self, sel, fn):
        self.tracks.append((sel, [fn(f) for f in range(self.N)]))

    # ---------- 土台 ----------
    def rect_css(self, rect):
        l, t, w, h = rect; return f"left:{l}px;top:{t}px;width:{w}px;height:{h}px;"

    def fade_mask(self, b):
        stops = []
        if b.get("fade_left"): stops.append(f"transparent 0%, black {b['fade_left']*100:.0f}%")
        else: stops.append("black 0%")
        if b.get("fade_right"): stops.append(f"black {b['fade_right']*100:.0f}%, transparent 100%")
        else: stops.append("black 100%")
        g = f"linear-gradient(to right, {', '.join(stops)})"
        return f"-webkit-mask-image:{g};mask-image:{g};" if (b.get("fade_left") or b.get("fade_right")) else ""

    def default_rect(self, w, h):
        k = min(self.W / w, self.H / h); return [round((self.W - w * k) / 2), round((self.H - h * k) / 2), round(w * k), round(h * k)]

    def base(self):
        b = self.s["base"]; t = b["type"]
        if t == "video":
            info = probe(self.P(b["src"])); rect = b.get("rect") or self.default_rect(info["width"], info["height"])
            src = self.asset(b["src"], "base.mp4"); style = f"position:absolute;{self.rect_css(rect)}object-fit:fill;{self.fade_mask(b)}"
            cut = b.get("cut"); audio = b.get("audio", "video"); vend = cut if cut else self.dur
            muted = bool(cut) or audio != "video"
            self.html["camera"].append(f'<video id="base" class="clip" src="{src}" data-start="0" data-duration="{vend:g}" '
                                       f'{"muted" if muted else "data-has-audio=\"true\""} playsinline style="{style}"></video>')
            if cut:
                idx = max(0, int(round(cut * info["fps"])) - 1)
                freeze = os.path.join(self.assets, "freeze.png")
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", self.P(b["src"]), "-vf", f"select=eq(n\\,{idx})", "-frames:v", "1", freeze], check=True)
                self.html["camera"].append(f'<img id="freeze" class="clip" src="assets/freeze.png" data-start="{cut:g}" data-duration="{self.dur - cut:g}" alt="" style="{style}">')
            if audio == "video" and cut and info["has_audio"]:
                wav = os.path.join(self.assets, "base_audio.wav")
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", self.P(b["src"]), "-vn", "-ac", "2", "-ar", "48000", wav], check=True)
                self.add_audio("assets/base_audio.wav", 0, 1.0, copy=False)
            elif audio not in ("video", "none"):
                self.add_audio(audio, 0, b.get("volume", 1.0))
        elif t == "sequence":   # 何本かの動画を順につなぐ（カットごとに cut・hold・audio を指定できる）
            t0 = 0.0
            for k, c in enumerate(b["clips"]):
                p = self.P(c["src"]); info = probe(p); rect = c.get("rect") or b.get("rect") or self.default_rect(info["width"], info["height"])
                length = float(c.get("cut") or info["duration"]); hold = float(c.get("hold", 0))
                src = self.asset(c["src"], f"clip{k}.mp4"); style = f"position:absolute;{self.rect_css(rect)}object-fit:fill;{self.fade_mask(b)}"
                self.html["camera"].append(f'<video id="clip{k}" class="clip" src="{src}" data-start="{t0:g}" data-duration="{length:g}" muted playsinline style="{style}"></video>')
                if hold > 0:   # 最後のまともなコマで止めて hold 秒見せる
                    idx = max(0, int(round(length * info["fps"])) - 1); fz = f"freeze{k}.png"
                    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", p, "-vf", f"select=eq(n\\,{idx})", "-frames:v", "1", os.path.join(self.assets, fz)], check=True)
                    self.html["camera"].append(f'<img id="frz{k}" class="clip" src="assets/{fz}" data-start="{t0 + length:g}" data-duration="{hold:g}" alt="" style="{style}">')
                audio = c.get("audio", b.get("audio", "video"))
                if audio == "video" and info["has_audio"]:
                    wav = f"clip{k}.wav"
                    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", p, "-vn", "-ac", "2", "-ar", "48000", "-t", f"{length:.3f}", os.path.join(self.assets, wav)], check=True)
                    self.add_audio(f"assets/{wav}", t0, c.get("volume", 1.0), copy=False)
                elif audio not in ("video", "none"):   # 差し替えの声もカットの長さで切る（次のカットに食い込ませない）
                    wav = f"clip{k}_audio.wav"
                    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", self.P(audio), "-ac", "2", "-ar", "48000", "-t", f"{length:.3f}",
                                    "-af", f"afade=t=out:st={max(0, length - 0.05):.3f}:d=0.05", os.path.join(self.assets, wav)], check=True)
                    self.add_audio(f"assets/{wav}", t0, c.get("volume", 1.0), copy=False)
                t0 += length + hold
            if t0 < self.dur - 0.05: print(f"WARN: つないだ長さ {t0:.2f} 秒が duration {self.dur} より短い（残りは背景色）", file=sys.stderr)
        elif t == "image":
            import cv2
            im = cv2.imread(self.P(b["src"])); rect = b.get("rect") or self.default_rect(im.shape[1], im.shape[0])
            src = self.asset(b["src"]); self.html["camera"].append(f'<img id="base" src="{src}" alt="" style="position:absolute;{self.rect_css(rect)}{self.fade_mask(b)}">')
        elif t == "flipbook":
            sd = self.P(b["states_dir"]); names = self.flip_timeline(b)
            used = sorted(set(n for n in names if n))
            import cv2
            first = cv2.imread(os.path.join(sd, used[0] + ".png")); rect = b.get("rect") or self.default_rect(first.shape[1], first.shape[0])
            style = f"position:absolute;{self.rect_css(rect)}opacity:0;{self.fade_mask(b)}"
            for n in used:
                src = self.asset(os.path.join(sd, n + ".png"), f"st_{n}.png"); sid = "st_" + re.sub(r"[^A-Za-z0-9_-]", "_", n)
                self.html["camera"].append(f'<img id="{sid}" src="{src}" alt="" style="{style}">')
                self.track(f"#{sid}", lambda f, n=n: {"opacity": 1 if names[f] == n else 0})
        else:
            die(f"base.type が不明: {t}", 2)

    def flip_timeline(self, b):
        """[時刻, 状態] / cycle / overrides から、コマごとの状態名を作る。"""
        names = [None] * self.N
        for e in b["timeline"]:
            if isinstance(e, list):
                f0 = self.fr(e[0])
                for f in range(f0, self.N): names[f] = e[1]
            else:   # {"from","to","step","cycle":[...],"template":"hand-{}_head-B"}
                f0, f1 = self.fr(e["from"]), self.fr(e["to"]); step = e["step"]; tpl = e.get("template", "{}")
                for f in range(f0, min(f1, self.N)):
                    k = int((f - f0) / (step * self.fps)); names[f] = tpl.format(e["cycle"][k % len(e["cycle"])])
        for o in b.get("overrides", []):   # {"from","to","set":{"head":"K"}}
            for f in range(self.fr(o["from"]), min(self.fr(o["to"]), self.N)):
                if names[f] and "-" in names[f]:
                    parts = dict(p.split("-", 1) for p in names[f].split("_"))
                    parts.update(o["set"]); names[f] = "_".join(f"{k}-{v}" for k, v in parts.items())
        if any(n is None for n in names): die("flipbook の timeline が 0 秒から始まっていない", 2)
        return names

    def add_audio(self, src, start, vol, copy=True):
        s = self.asset(src) if copy else src; k = len(self.html["audio"])
        self.html["audio"].append(f'<audio id="au{k}" class="clip" src="{s}" data-start="{start:g}" data-duration="{self.dur - start:g}" data-volume="{vol:g}"></audio>')

    # ---------- カメラ ----------
    def camera(self):
        c = self.s.get("camera", {}); fps = self.fps
        push, punch, shake, pan = c.get("push", []), c.get("punch", []), c.get("shake", []), c.get("pan", [])
        o = (push[0]["origin"] if push else [self.W / 2, self.H / 2]); self.css.append(f"#push{{transform-origin:{o[0]}px {o[1]}px;}}")
        o = (punch[0]["origin"] if punch else [self.W / 2, self.H / 2]); self.css.append(f"#punch{{transform-origin:{o[0]}px {o[1]}px;}}")

        def push_s(f):
            s = 1.0
            for p in push:
                f0, f1 = self.fr(p["from"]), self.fr(p["to"]); s *= 1 + (p["scale"] - 1) * ease_inout((f - f0) / max(1, f1 - f0))
            return {"scale": round(s, 5)}
        def punch_s(f):
            s = 1.0
            for p in punch:
                s *= 1 + (p["scale"] - 1) * spring(f - self.fr(p["t"]), fps, p.get("damping", 9), p.get("stiffness", 180))
            return {"scale": round(s, 5)}
        def shake_xy(f):
            x = y = 0.0
            for sh in shake:
                f0, f1 = self.fr(sh["from"]), self.fr(sh["to"])
                if f0 <= f < f1:
                    a = sh["amp"] * ((1 - 0.7 * (f - f0) / (f1 - f0)) if sh.get("decay", True) else 1)
                    x += a * (math.sin(f * 1.9) + 0.6 * math.sin(f * 4.3)); y += a * 0.6 * (math.cos(f * 2.3) + 0.5 * math.sin(f * 5.1))
            return {"x": round(x, 2), "y": round(y, 2)}
        def pan_xy(f):
            x = y = 0.0
            for p in pan:
                q = ease_inout((f - self.fr(p["from"])) / max(1, self.fr(p["to"]) - self.fr(p["from"])))
                x += p.get("dx", 0) * q; y += p.get("dy", 0) * q
            return {"x": round(x, 2), "y": round(y, 2)}
        if shake: self.track("#shake", shake_xy)
        if punch: self.track("#punch", punch_s)
        if push: self.track("#push", push_s)
        if pan: self.track("#pan", pan_xy)

    # ---------- 重ね表示 ----------
    def overlays(self):
        for i, o in enumerate(self.s.get("overlays", [])):
            getattr(self, "ov_" + o["type"], lambda *_: die(f"overlay.type が不明: {o['type']}", 2))(i, o)

    def place(self, o, html_):
        self.html["camera" if o.get("attach") else "screen"].append(html_)

    def ov_terminal(self, i, o):
        fps = self.fps; l, t, w, h = o.get("rect", [1105, 150, 770, 700]); fs = o.get("font_size", 27); lh = o.get("line_height", 40)
        cap = max(1, int((h - 46 - 42) / lh)); pre = o.get("prefill", ""); typing = o.get("typing", []); lines = o.get("lines", [])
        kw = r"\b(export|import|from|const|let|var|async|await|function|return|if|else|for|while|class|new|def|print)\b"
        def colorize(text, base="#d6deeb"):
            col = [base] * len(text)
            def paint(rx, c):
                for m in re.finditer(rx, text):
                    for k in range(m.start(), m.end()): col[k] = c
            paint(kw, "#c792ea"); paint(r"\b[A-Za-z_]\w*(?=\()", "#82aaff"); paint(r'"[^"\n]*"|\'[^\'\n]*\'', "#c3e88d")
            paint(r"(//|#)[^\n]*", "#637777"); paint(r"(^|\n)\$ [^\n]*", "#7fdbca")
            return col
        # 書き済みの部分（色ごとにまとめて1つの文字列にする＝合字も効く）
        pc = colorize(pre); parts = []; run = ""; rc = None
        for ch, c in zip(pre, pc):
            if c != rc and run: parts.append(f'<span style="color:{rc}">{html.escape(run)}</span>'); run = ""
            run += ch; rc = c
        if run: parts.append(f'<span style="color:{rc}">{html.escape(run)}</span>')
        # 打つ部分（1文字ずつ。直後にカーソル）
        typed_text = "".join(x["text"] for x in typing); tc = colorize(pre + typed_text)[len(pre):]
        reveal = []   # 各文字が出るコマ
        for x in typing:
            f0, f1 = self.fr(x["from"]), self.fr(x["to"]); n = len(x["text"])
            reveal += [f0 + round((f1 - f0) * (k + 1) / n) for k in range(n)]
        p = f"t{i}"
        parts.append(f'<span class="cur" id="{p}cur0"></span>')
        for k, ch in enumerate(typed_text):
            parts.append(f'<span class="ch" id="{p}c{k}" style="color:{tc[k]}">{html.escape(ch)}</span><span class="cur" id="{p}cur{k+1}"></span>')
        kinds = {"dim": "#8b949e", "ok": "#3fb950", "err": "#ff6b6b", "info": "#82aaff", "plain": "#d6deeb"}
        for k, ln in enumerate(lines):
            col = kinds.get(ln.get("kind", "plain"), "#d6deeb"); bold = ln.get("bold", ln.get("kind") == "err")
            body = html.escape(ln.get("text", ""))
            if ln.get("mark"):   # 行の中の語に印（黄色の帯）。mark_t で点滅してから残る
                segs = ln.get("text", "").split(ln["mark"])
                body = "".join(html.escape(sg) + (f'<span class="hl" id="{p}h{k}_{j}">{html.escape(ln["mark"])}</span>' if j < len(segs) - 1 else "")
                               for j, sg in enumerate(segs))
            if "progress" in ln:   # 進み具合のバー: 文言 [■■■□□] 99%
                pg = ln["progress"]; bw = pg.get("width", 16)
                body += (f'<span class="pbar" style="width:{bw * 0.6:.2f}em"><span class="pfill" id="{p}pf{k}"></span></span>'
                         f'<span class="pnum" style="height:{lh}px"><span class="pnin" id="{p}pn{k}">{"<br>".join(f"{n:>3d}%" for n in range(101))}</span></span>')
            parts.append(f'<div class="out" id="{p}o{k}" style="color:{col};font-weight:{700 if bold else 400}">{body}</div>')
        title = html.escape(o.get("title", ""))
        self.place(o, f'''<div class="term" id="{p}" style="left:{l}px;top:{t}px;width:{w}px;height:{h}px;opacity:0">
<div class="thead"><div class="dot" style="background:#ff5f57"></div><div class="dot" style="background:#febc2e"></div><div class="dot" style="background:#28c840"></div><div class="ttitle">{title}</div></div>
<div class="tbody"><div class="tcontent" id="{p}content" style="font-size:{fs}px;line-height:{lh}px">{"".join(parts)}</div></div><div class="tglow" id="{p}glow"></div></div>''')
        appear = o.get("appear", 0.0); fa = self.fr(appear)
        self.track(f"#{p}", lambda f: {"opacity": round(min(1, max(0, (f - fa) / 8)), 3), "y": round(20 * (1 - min(1, max(0, (f - fa) / 8))), 2)})
        for k, rf in enumerate(reveal):
            self.track(f"#{p}c{k}", lambda f, rf=rf: {"opacity": 1 if f >= rf else 0})
        tend = max(reveal) if reveal else -1; tstart = self.fr(typing[0]["from"]) if typing else 0
        def typed_at(f): return sum(1 for rf in reveal if f >= rf)
        enter = self.fr(o["cursor_until"]) if "cursor_until" in o else (tend + 2 if reveal else -1)
        def cur_state(f, k):
            if f >= enter or f < 0: return 0
            n = typed_at(f); typing_now = tstart <= f <= tend
            return 1 if (n == k and (typing_now or (f // 12) % 2 == 0)) else 0
        for k in range(len(typed_text) + 1):
            self.track(f"#{p}cur{k}", lambda f, k=k: {"width": "0.6em" if cur_state(f, k) else 0})
        for k, ln in enumerate(lines):
            self.track(f"#{p}o{k}", lambda f, at=self.fr(ln["t"]): {"opacity": 1 if f >= at else 0})
            if ln.get("mark"):
                mt = self.fr(ln.get("mark_t", ln["t"])); col = kinds.get(ln.get("kind", "plain"), "#d6deeb")
                def hl(f, mt=mt, col=col):
                    on = f >= mt and not (f - mt < 0.5 * self.fps and ((f - mt) // 3) % 2 == 1)
                    return {"backgroundColor": "rgba(255,214,0,1)" if on else "rgba(255,214,0,0)", "color": "#111" if on else col}
                for j in range(ln.get("text", "").count(ln["mark"])):
                    self.track(f"#{p}h{k}_{j}", hl)
            if "progress" in ln:
                keys = [(self.fr(t_), v_) for t_, v_ in ln["progress"]["keys"]]
                def pct(f, keys=keys):
                    if f <= keys[0][0]: return keys[0][1]
                    for (f0, v0), (f1, v1) in zip(keys, keys[1:]):
                        if f < f1: return v0 + (v1 - v0) * (f - f0) / max(1, f1 - f0)
                    return keys[-1][1]
                self.track(f"#{p}pf{k}", lambda f, pct=pct: {"width": f"{pct(f):.1f}%"})
                self.track(f"#{p}pn{k}", lambda f, pct=pct: {"y": -int(pct(f)) * lh})
        pre_lines = pre.count("\n")
        def scroll(f):
            n = pre_lines + 1 + typed_text[:typed_at(f)].count("\n") + sum(1 for ln in lines if f >= self.fr(ln["t"]))
            return {"y": -max(0, n - cap) * lh}
        self.track(f"#{p}content", scroll)
        glows = o.get("glow", []); colored = any("color" in g for g in glows)
        def glow(f):
            v = 0.0; col = [255, 60, 60]; latest = -1
            for g in glows:
                w = 0.0
                if g.get("type", "flash") == "flash":
                    f0 = self.fr(g["t"]); d = f - f0
                    if d >= 0: w = 1.0 if d < 4 else max(0.55, 1 - 0.45 * (d - 4) / 10)
                else:
                    f0 = self.fr(g["from"])
                    if f0 <= f < self.fr(g["to"]): w = 0.575 + 0.175 * math.sin(2 * math.pi * (f - f0) / (0.4 * self.fps))
                if w > 0:
                    v = max(v, w) if g.get("type", "flash") == "flash" else w   # 脈打ちは残光を上書きして暗くもなる
                    if f0 >= latest: latest = f0; col = g.get("color", [255, 60, 60])   # 最後に始まった光の色
            if not colored: return {"opacity": round(v, 3)}
            r, gg, b = col
            return {"opacity": round(v, 3), "borderColor": f"rgb({r},{gg},{b})", "boxShadow": f"0 0 50px rgba({r},{gg},{b},0.9)"}
        if glows: self.track(f"#{p}glow", glow)

    def ov_bubble(self, i, o):
        styles = {"normal": ("#1b1b1b", "#1b1b1b", 0), "panic": ("#1b1b1b", "#1b1b1b", 3), "angry": ("#d61f26", "#c4161c", 2),
                  "soft": ("#7a7f8a", "#4a4e57", 0)}   # soft = 点線の吹き出し（寝言・つぶやき・独り言）
        st = o.get("style", "normal"); border, color, jit = styles.get(st, styles["normal"]); jit = o.get("jitter", jit)
        size = o.get("size", (36 if st == "soft" else 40) if max(len(t) for t in o["text"].split(chr(10))) > 9 or st == "soft" else 46)
        x, y = o.get("pos", [600, 40]); tail = o.get("tail", "dots" if st == "soft" else "left")
        tails = ("" if tail == "none" else
                 f'<div class="td1" style="border-color:{border}"></div><div class="td2" style="border-color:{border}"></div>' if tail == "dots" else
                 f'<div class="t1" style="border-right-color:{border}"></div><div class="t2"></div>' if tail == "left" else
                 f'<div class="t1 r" style="border-left-color:{border}"></div><div class="t2 r"></div>')
        bstyle = "border-style:dashed;border-width:4px;font-weight:700;" if st == "soft" else ""
        self.place(o, f'<div class="bub" id="b{i}" style="left:{x}px;top:{y}px;transform-origin:{"0%" if tail != "right" else "100%"} 100%"><div class="bin" style="border-color:{border};color:{color};font-size:{size}px;{bstyle}">{html.escape(o["text"]).replace(chr(10), "<br>")}{tails}</div></div>')
        a, b = self.fr(o["from"]), self.fr(o.get("to", self.dur))
        def fn(f):
            if f < a or f >= b: return {"opacity": 0, "scale": 0.6, "x": 0}
            pop = spring(f - a, self.fps, 11, 220); out = 1 if b >= self.N else min(1, (b - f) / 4)
            return {"opacity": round(min(pop * 1.4, 1) * out, 3), "scale": round(0.6 + 0.4 * pop, 4), "x": round(jit * math.sin(f * 2.9), 2)}
        self.track(f"#b{i}", fn)

    def ov_caption(self, i, o):
        size = o.get("size", 44)
        self.place(o, f'<div class="cap" id="c{i}" style="font-size:{size}px;bottom:{o.get("bottom", 70)}px">{html.escape(o["text"])}</div>')
        a, b = self.fr(o["from"]), self.fr(o["to"]); k = max(1, self.fr(0.15))
        self.track(f"#c{i}", lambda f: {"opacity": round(max(0, min(1, (f - a) / k, (b - f) / k)), 3)})

    def ov_text(self, i, o):
        x, y = o.get("pos", [self.W / 2, self.H / 2]); st = o.get("style", {})
        # 外側は置き場所（大きさ0、拡大の中心＝pos）。見た目（色・枠・背景・style）は内側に付けて pos に対して寄せる
        inner = (f"font-size:{o.get('size', 64)}px;color:{o.get('color', '#1b1b1b')};font-weight:{o.get('weight', 900)};"
                 f"background:{o.get('bg', 'transparent')};text-align:{o.get('align', 'center')};" + "".join(f"{k}:{v};" for k, v in st.items()))
        anchor = o.get("anchor", "center")
        tr = {"center": "translate(-50%,-50%)", "left": "translate(0,-50%)", "topleft": "none"}[anchor]
        self.place(o, f'<div class="txt" id="x{i}" style="left:{x}px;top:{y}px;width:0;height:0;transform-origin:0 0">'
                      f'<div style="position:absolute;left:0;top:0;white-space:nowrap;transform:{tr};{inner}">{html.escape(o["text"]).replace(chr(10), "<br>")}</div></div>')
        a, b = self.fr(o["from"]), self.fr(o.get("to", self.dur)); anim = o.get("anim", "fade")
        def fn(f):
            if f < a or f >= b: return {"opacity": 0}
            out = 1 if b >= self.N else min(1, (b - f) / 5)
            if anim == "pop":
                p = spring(f - a, self.fps, 11, 220); return {"opacity": round(min(1, p * 1.4) * out, 3), "scale": round(0.7 + 0.3 * p, 4)}
            return {"opacity": round(min(1, (f - a) / 6) * out, 3)}
        self.track(f"#x{i}", fn)

    def ov_wash(self, i, o):
        r, g, b = o.get("color", [230, 0, 20])
        self.place(o, f'<div class="wash" id="w{i}" style="background:radial-gradient(ellipse at center, rgba({r},{g},{b},0) 45%, rgba({r},{g},{b},1) 100%)"></div>')
        segs = o["segments"]
        def fn(f):
            v = 0.0
            for s in segs:
                ty = s["type"]
                if ty == "flash":
                    d = f - self.fr(s["t"]); until = self.fr(s.get("until", self.dur)); rise = 3; dec = max(1, self.fr(s.get("decay", 0.4)))
                    hold = s.get("hold", s["peak"] * 0.25)
                    if 0 <= d and f < until: v = max(v, s["peak"] * d / rise if d < rise else max(hold, s["peak"] - (s["peak"] - hold) * (d - rise) / dec))
                elif ty == "pulse":
                    if self.fr(s["from"]) <= f < self.fr(s["to"]):
                        ph = (f - self.fr(s["from"])) / (s.get("period", 0.4) * self.fps)
                        v = max(v, s.get("low", 0.0) + (s.get("high", 0.16) - s.get("low", 0.0)) * (0.5 - 0.5 * math.cos(2 * math.pi * ph)))
                elif ty == "fade":
                    d = f - self.fr(s["t"]); until = self.fr(s.get("until", self.dur))
                    if 0 <= d and f < until: v = max(v, s["from"] + (s["to"] - s["from"]) * min(1, d / max(1, self.fr(s.get("dur", 0.6)))))
            return {"opacity": round(v, 3)}
        self.track(f"#w{i}", fn)

    def ov_mark(self, i, o):
        size = o.get("size", 90); x, y = o["pos"]
        if o.get("shape") in ("zzz", "sparkle"): return self.mark_multi(i, o, size, x, y)
        shapes = {"anger": "".join(f'<path d="M58 42 Q 62 22 82 18 M58 42 Q 78 38 82 18" transform="rotate({r} 50 50)" stroke="#e0242b" stroke-width="9" fill="none" stroke-linecap="round"/>' for r in (0, 90, 180, 270)),
                  "exclaim": '<path d="M50 10 L50 62" stroke="#e0242b" stroke-width="14" stroke-linecap="round"/><circle cx="50" cy="84" r="8" fill="#e0242b"/>',
                  "sweat": '<path d="M50 8 C 30 40, 26 60, 50 88 C 74 60, 70 40, 50 8 Z" fill="#7cc4ff" stroke="#3a8ad6" stroke-width="4"/>',
                  "heart": '<path d="M50 86 C 20 64, 6 46, 10 30 C 14 14, 34 8, 50 26 C 66 8, 86 14, 90 30 C 94 46, 80 64, 50 86 Z" fill="#ff5c93" stroke="#d6336c" stroke-width="4"/>'}
        self.place(o, f'<svg class="mark" id="m{i}" viewBox="0 0 100 100" style="left:{x}px;top:{y}px;width:{size}px;height:{size}px;rotate:{o.get("rotate", 12)}deg">{shapes[o.get("shape", "anger")]}</svg>')
        a, b = self.fr(o["t"]), self.fr(o.get("to", self.dur)); pulse = o.get("pulse", True)
        self.track(f"#m{i}", lambda f: {"opacity": 1 if a <= f < b else 0,
                                         "scale": round(1 + (0.12 * math.sin(2 * math.pi * (f - a) / (0.42 * self.fps)) if pulse and f >= a else 0), 4)})

    def mark_multi(self, i, o, size, x, y):
        """動く記号: zzz（Z が3つ順に浮いて消える＝居眠り）/ sparkle（星が3つ瞬く＝成功・嬉しい）。pos は左下。"""
        a, b = self.fr(o["t"]), self.fr(o.get("to", self.dur)); fps = self.fps; shape = o["shape"]
        col = o.get("color", "#5b6b8a" if shape == "zzz" else "#f5b301")
        if shape == "zzz":
            # 3つの Z が同じ道筋（右上へ）を 1/3 周期ずつずれて昇り、昇るほど大きくなって消える
            period = o.get("period", 1.2)
            self.place(o, "".join(f'<div class="mz" id="m{i}z{k}" style="left:{x}px;top:{y}px;font-size:{size}px;color:{col}">Z</div>' for k in range(3)))
            for k in range(3):
                def fn(f, k=k):
                    cyc = (f - a) / (period * fps) - k / 3
                    if not (a <= f < b) or cyc < 0: return {"opacity": 0}
                    ph = cyc % 1.0; op = min(1, ph / 0.15, (1 - ph) / 0.3); out = 1 if b >= self.N else min(1, (b - f) / 6)
                    return {"opacity": round(max(0, op) * out, 3), "x": round(size * 0.9 * ph, 1), "y": round(-size * 1.5 * ph, 1),
                            "scale": round(0.45 + 0.75 * ph, 3), "rotate": -12}
                self.track(f"#m{i}z{k}", fn)
        else:
            star = "M50 0 C 54 38, 62 46, 100 50 C 62 54, 54 62, 50 100 C 46 62, 38 54, 0 50 C 38 46, 46 38, 50 0 Z"
            spots = [(0, 0, 1.0), (size * 0.9, -size * 0.55, 0.6), (size * 0.75, size * 0.55, 0.45)]
            self.place(o, "".join(f'<svg class="mark" id="m{i}s{k}" viewBox="0 0 100 100" style="left:{x + dx:.0f}px;top:{y + dy:.0f}px;width:{size * s:.0f}px;height:{size * s:.0f}px"><path d="{star}" fill="{col}"/></svg>'
                                  for k, (dx, dy, s) in enumerate(spots)))
            for k in range(3):
                def fn(f, k=k):
                    if not (a <= f < b): return {"opacity": 0}
                    d = f - a - k * 3
                    if d < 0: return {"opacity": 0}
                    tw = 0.5 + 0.5 * math.sin(2 * math.pi * d / (0.6 * fps) + k)
                    return {"opacity": round(0.35 + 0.65 * tw, 3), "scale": round(min(1, spring(d, fps, 10, 260)) * (0.75 + 0.25 * tw), 4)}
                self.track(f"#m{i}s{k}", fn)

    def ov_svg(self, i, o):
        """図（SVG）を重ね、中の要素（id）をキーフレームで動かす。解説の図・工程図向け。
        anims: [{"sel": "#id", "prop": "x|y|scale|scaleX|scaleY|rotation|opacity", "keys": [[秒, 値], ...],
                 "ease": "linear|inout|step", "origin": "x y"（SVG座標。拡大・回転の中心）} | {"sel", "attr": "width", "keys"}]"""
        svg = open(self.P(o["src"]), encoding="utf-8").read()
        svg = re.sub(r"<\?xml[^>]*\?>", "", svg).strip()
        svg = re.sub(r"<svg\b", '<svg style="width:100%;height:100%;overflow:visible"', svg, count=1)
        self.place(o, f'<div class="svgov" id="sv{i}" style="{self.rect_css(o["rect"])}opacity:0">{svg}</div>')
        a, b = self.fr(o.get("from", 0)), self.fr(o.get("to", self.dur)); fd = max(1, self.fr(o.get("fade", 0.3)))
        self.track(f"#sv{i}", lambda f: {"opacity": round(max(0, min(1, (f - a) / fd, 1 if b >= self.N else (b - f) / fd)), 3) if a <= f < b else 0})
        for an in o.get("anims", []):
            keys = [(self.fr(t_), v_) for t_, v_ in an["keys"]]; ease = an.get("ease", "inout")
            def val(f, keys=keys, ease=ease):
                if f <= keys[0][0]: return keys[0][1]
                for (f0, v0), (f1, v1) in zip(keys, keys[1:]):
                    if f < f1:
                        if ease == "step" or not isinstance(v0, (int, float)): return v0
                        p = (f - f0) / max(1, f1 - f0); p = ease_inout(p) if ease == "inout" else p
                        return round(v0 + (v1 - v0) * p, 4)
                return keys[-1][1]
            if "attr" in an:
                self.track(an["sel"], lambda f, val=val, nm=an["attr"]: {"attr": {nm: val(f)}})
            else:
                org = an.get("origin")
                self.track(an["sel"], lambda f, val=val, pr=an["prop"], org=org: ({pr: val(f), "svgOrigin": org} if org else {pr: val(f)}))

    def ov_video(self, i, o):
        """動画を枠（rect）に重ねる。音は使わない。from 秒から素材の長さだけ流す（length で短くできる）。
        白い背景の図・3D を白っぽい土台になじませるなら blend: "multiply"（白が透けて、色の付いた所だけ残る）。"""
        p = self.P(o["src"]); info = probe(p); a = float(o.get("from", 0))
        length = min(float(o.get("length") or info["duration"]), self.dur - a)
        src = self.asset(o["src"], f"ov{i}.mp4"); blend = f"mix-blend-mode:{o['blend']};" if o.get("blend") else ""
        self.place(o, f'<video id="ov{i}" class="clip" src="{src}" data-start="{a:g}" data-duration="{length:g}" muted playsinline '
                      f'style="{self.rect_css(o["rect"])}object-fit:fill;{blend}"></video>')

    def ov_image(self, i, o):
        src = self.asset(o["src"]); self.place(o, f'<img class="ovimg" id="im{i}" src="{src}" alt="" style="{self.rect_css(o["rect"])}opacity:0">')
        a, b = self.fr(o.get("from", 0)), self.fr(o.get("to", self.dur))
        self.track(f"#im{i}", lambda f: {"opacity": round(max(0, min(1, (f - a) / 6, 1 if b >= self.N else (b - f) / 6)), 3) if a <= f < b else 0})

    # ---------- 書き出し ----------
    def build(self):
        if os.path.isdir(self.proj): shutil.rmtree(self.proj)
        os.makedirs(self.assets)
        self.base(); self.camera(); self.overlays()
        for a in self.s.get("audio", []): self.add_audio(a["src"], a.get("start", 0), a.get("volume", 1.0))
        js = []
        for sel, vals in self.tracks:
            prev = None
            for f, v in enumerate(vals):
                if v != prev:
                    js.append(f'tl.set("{sel}",{json.dumps(v)},{self.sec(f)});'); prev = v
        js.append(f"tl.set({{}},{{}},{self.dur:g});")
        bg = self.s.get("bg", "#fefdfd"); D = f"{self.dur:g}"
        page = f"""<!doctype html>
<html lang="ja"><head><meta charset="UTF-8" /><meta name="viewport" content="width={self.W}, height={self.H}" />
<link href="{FONTS}" rel="stylesheet" />
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
html,body{{width:{self.W}px;height:{self.H}px;overflow:hidden;background:{bg};}}
#root{{position:relative;width:{self.W}px;height:{self.H}px;background:{bg};overflow:hidden;}}
.clip,.layer{{position:absolute;inset:0;}}
{"".join(self.css)}
.term{{position:absolute;border-radius:18px;overflow:hidden;background:#14171f;box-shadow:0 24px 60px rgba(0,0,0,0.28);}}
.thead{{height:46px;background:#232733;display:flex;align-items:center;padding:0 18px;gap:10px;}}
.dot{{width:15px;height:15px;border-radius:8px;}}
.ttitle{{margin-left:16px;color:#9aa4b5;font-family:'JetBrains Mono',monospace;font-size:19px;}}
.tbody{{position:absolute;top:46px;left:0;right:0;bottom:0;overflow:hidden;}}
.tcontent{{padding:21px 28px;font-family:'JetBrains Mono','M PLUS Rounded 1c',monospace;white-space:pre;}}
.ch,.out{{opacity:0;}}
.cur{{display:inline-block;width:0;height:0;position:relative;}}
.cur::after{{content:"";position:absolute;left:0;bottom:-7px;width:100%;height:1.25em;background:#d6deeb;}}
.tglow{{position:absolute;inset:0;border-radius:18px;border:2px solid rgb(255,70,70);box-shadow:0 0 50px rgba(255,40,40,0.9);opacity:0;pointer-events:none;}}
.wash{{position:absolute;inset:0;opacity:0;pointer-events:none;}}
.bub{{position:absolute;opacity:0;}}
.bin{{position:relative;background:white;border:5px solid;border-radius:40px;padding:18px 34px;font-family:'M PLUS Rounded 1c',sans-serif;font-weight:800;white-space:nowrap;box-shadow:0 8px 0 rgba(0,0,0,0.08);}}
.t1{{position:absolute;left:-18px;bottom:-6px;width:0;height:0;border-top:26px solid transparent;border-right:40px solid;transform:rotate(-28deg);}}
.t2{{position:absolute;left:-8px;bottom:0;width:0;height:0;border-top:18px solid transparent;border-right:30px solid white;transform:rotate(-28deg);}}
.t1.r{{left:auto;right:-18px;border-right:0;border-left:40px solid;transform:rotate(28deg);}}
.t2.r{{left:auto;right:-8px;border-right:0;border-left:30px solid white;transform:rotate(28deg);}}
.cap{{position:absolute;left:50%;transform:translateX(-50%);opacity:0;padding:10px 28px;border-radius:12px;background:rgba(0,0,0,0.6);color:#fff;font-family:'Noto Sans JP',sans-serif;font-weight:700;white-space:nowrap;}}
.txt{{position:absolute;opacity:0;font-family:'Noto Sans JP',sans-serif;white-space:nowrap;}}
.mark{{position:absolute;opacity:0;}}
.ovimg{{position:absolute;}}
.svgov{{position:absolute;}}
.pbar{{display:inline-block;position:relative;height:0.62em;margin:0 0.45em 0 0.35em;border:2px solid currentColor;border-radius:4px;vertical-align:middle;overflow:hidden;}}
.pfill{{position:absolute;left:0;top:0;bottom:0;width:0;background:currentColor;}}
.pnum{{display:inline-block;overflow:hidden;vertical-align:top;}}
.pnin{{display:block;}}
.hl{{border-radius:4px;padding:0 2px;}}
.td1{{position:absolute;left:-16px;bottom:-24px;width:24px;height:24px;border-radius:50%;border:4px dashed;background:white;}}
.td2{{position:absolute;left:-36px;bottom:-44px;width:14px;height:14px;border-radius:50%;border:3px solid;background:white;}}
.mz{{position:absolute;opacity:0;font-family:'M PLUS Rounded 1c',sans-serif;font-weight:800;line-height:1;}}
</style></head><body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{D}" data-width="{self.W}" data-height="{self.H}">
  <div id="stage" class="layer">
    <div id="shake" class="layer"><div id="punch" class="layer"><div id="push" class="layer"><div id="pan" class="layer">
      {chr(10).join(self.html["camera"])}
    </div></div></div></div>
    {chr(10).join(self.html["screen"])}
  </div>
  {chr(10).join(self.html["audio"])}
</div>
<script>
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{ paused: true }});
{chr(10).join(js)}
window.__timelines["main"] = tl;
tl.seek(0);
</script></body></html>
"""
        open(os.path.join(self.proj, "index.html"), "w", encoding="utf-8").write(page)
        json.dump({"$schema": "https://hyperframes.heygen.com/schema/hyperframes.json", "paths": {"assets": "assets"}, "media": {"autoProxy": True}},
                  open(os.path.join(self.proj, "hyperframes.json"), "w"), indent=2)
        json.dump({"id": "scene", "name": self.s.get("name", "scene")}, open(os.path.join(self.proj, "meta.json"), "w"), indent=2)
        return len(js)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("scene"); ap.add_argument("--out"); ap.add_argument("--draft", action="store_true")
    ap.add_argument("--no-render", action="store_true"); a = ap.parse_args()
    proj = os.path.join(os.path.dirname(os.path.abspath(a.scene)), "hf")
    sc = Scene(a.scene, proj); n = sc.build()
    print(f"built {proj}/index.html ({n} sets)", file=sys.stderr)
    env = dict(os.environ, HYPERFRAMES_SKIP_SKILLS="1")
    lint = subprocess.run(["npx", "--yes", HF, "lint"], cwd=proj, capture_output=True, text=True, env=env)
    txt = re.sub(r"\x1b\[[0-9;]*m", "", lint.stdout + lint.stderr); m = re.search(r"(\d+) error\(s\)", txt)
    if m and int(m.group(1)) > 0: print(txt, file=sys.stderr); die("lint でエラー", 6)
    if a.no_render: return
    tmp = os.path.join(proj, "render.mp4")
    r = subprocess.run(["npx", "--yes", HF, "render", "-f", str(sc.fps), "-q", "draft" if a.draft else "high", "-o", tmp],
                       cwd=proj, capture_output=True, text=True, env=env)
    if r.returncode != 0 or not os.path.exists(tmp):
        print(re.sub(r"\x1b\[[0-9;]*m", "", r.stdout + r.stderr)[-3000:], file=sys.stderr); die("書き出しに失敗", 6)
    if a.draft and not a.out:   # 試し書き出しは作業フォルダに置く（保存先を散らかさない。毎回上書き）
        dst = os.path.join(os.path.dirname(os.path.abspath(a.scene)), "draft.mp4"); os.replace(tmp, dst)
    else:
        dst = out_path(sc.s.get("name", "scene"), out=a.out); atomic_copy(tmp, dst)
    print(dst)


if __name__ == "__main__":
    main()
