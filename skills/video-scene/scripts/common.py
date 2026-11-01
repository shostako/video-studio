"""video-scene の共通部品: 鍵の解決、Gemini 呼び出し、動画・音声の読み出し、保存先の決定。"""
import json, os, subprocess, sys, time, datetime, shutil

def _default_out():
    """出力先の既定: Windows のユーザーの Videos/generated（WSL）、Windows が無ければ ~/Videos/generated。"""
    try:
        r = subprocess.run(["cmd.exe", "/C", "echo %USERPROFILE%"], capture_output=True, timeout=15, cwd="/mnt/c" if os.path.isdir("/mnt/c") else None)
        b = r.stdout                               # 日本語のユーザー名は CP932 で出るので、UTF-8 で読めなければ CP932 で読む
        try: txt = b.decode("utf-8")
        except UnicodeDecodeError: txt = b.decode("cp932", errors="replace")
        w = txt.strip().splitlines()
        if w and "%" not in w[-1]:
            u = subprocess.run(["wslpath", "-u", w[-1].strip()], capture_output=True, text=True, timeout=15).stdout.strip()
            if u: return os.path.join(u, "Videos", "generated")
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.expanduser("~/Videos/generated")


OUT_DIR = os.environ.get("VIDEO_SCENE_OUT") or _default_out()
GEMINI_MODELS = [m for m in os.environ.get("VS_GEMINI_MODEL", "gemini-3.8-flash,gemini-2.5-flash").split(",") if m]


def resolve_api_key():
    """GEMINI_API_KEY を探す: 環境変数 → watermark-remover の .env → ~/.claude.json(youtube-gemini)。値は表示しない。"""
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        if os.environ.get(k):
            return os.environ[k]
    env_path = os.path.expanduser("~/ClaudeCode/watermark-remover/.env")
    if os.path.exists(env_path):
        for line in open(env_path, encoding="utf-8"):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                if k.strip() in ("GEMINI_API_KEY", "GOOGLE_API_KEY") and v.strip().strip("\"'"):
                    return v.strip().strip("\"'")
    cj = os.path.expanduser("~/.claude.json")
    if os.path.exists(cj):
        try:
            v = json.load(open(cj, encoding="utf-8")).get("mcpServers", {}).get("youtube-gemini", {}).get("env", {}).get("GEMINI_API_KEY")
            if v:
                return v
        except Exception:
            pass
    return None


def gemini_client():
    from google import genai
    key = resolve_api_key()
    if not key:
        die("Gemini API キーが見つからない", 3)
    return genai.Client(api_key=key)


def gemini_ask(media_path, question, json_out=False):
    """動画・音声ファイルを Gemini に渡して質問する。json_out=True なら JSON を返す。"""
    from google.genai import types
    c = gemini_client()
    f = c.files.upload(file=media_path)
    try:
        while f.state.name == "PROCESSING":
            time.sleep(2); f = c.files.get(name=f.name)
        cfg = types.GenerateContentConfig(response_mime_type="application/json") if json_out else None
        last = None
        for m in GEMINI_MODELS:
            try:
                r = c.models.generate_content(model=m, contents=[f, question], config=cfg)
                return json.loads(r.text) if json_out else r.text
            except Exception as e:  # モデル名の世代交代に備えて次の候補へ
                last = e
        raise last
    finally:
        try: c.files.delete(name=f.name)
        except Exception: pass


def probe(path):
    """幅・高さ・fps・長さ・音の有無。"""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate:format=duration",
                        "-of", "json", path], capture_output=True, text=True, check=True)
    d = json.loads(r.stdout); info = {"duration": float(d["format"]["duration"]), "has_audio": False}
    for s in d["streams"]:
        if s["codec_type"] == "video":
            n, m = s["r_frame_rate"].split("/"); info.update(width=s["width"], height=s["height"], fps=float(n) / float(m))
        elif s["codec_type"] == "audio":
            info["has_audio"] = True
    return info


def read_frames(path, scale=None, select=None):
    """動画のコマを numpy 配列 (N,H,W,3) BGR で返す。scale=(w,h)、select は ffmpeg の select 式。"""
    import numpy as np
    info = probe(path)
    vf = []
    if select: vf.append(f"select='{select}'")
    if scale: vf.append(f"scale={scale[0]}:{scale[1]}")
    w, h = scale if scale else (info["width"], info["height"])
    cmd = ["ffmpeg", "-v", "error", "-i", path] + (["-vf", ",".join(vf), "-vsync", "vfr"] if vf else []) + ["-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)


def read_audio(path, sr=16000, start=None, dur=None):
    import numpy as np
    cmd = ["ffmpeg", "-v", "error"] + (["-ss", str(start)] if start else []) + ["-i", path] + (["-t", str(dur)] if dur else []) + \
          ["-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, np.float32)


def out_path(name, ext="mp4", out=None):
    """保存先を決める。既定は Videos/generated/<日時>_<名前>.mp4。同名があれば -v2, -v3…（上書きしない）。"""
    if out:
        p = out
    else:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        safe = "".join(ch if ch.isalnum() or ch in "-_+." else "_" for ch in name)
        p = os.path.join(OUT_DIR, f"{stamp}_{safe}.{ext}")
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    base, e = os.path.splitext(p); i = 2
    while os.path.exists(p):
        p = f"{base}-v{i}{e}"; i += 1
    return p


def atomic_copy(src, dst):
    tmp = dst + ".part"
    shutil.copyfile(src, tmp); os.replace(tmp, dst)


def die(msg, code=1):
    print(f"ERROR: {msg}", file=sys.stderr); sys.exit(code)


if __name__ == "__main__" and "--check-key" in sys.argv:
    sys.exit(0 if resolve_api_key() else 1)
