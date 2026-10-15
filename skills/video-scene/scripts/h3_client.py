"""h3_client.py — Windows 側の ComfyUI に話しかける係（h3.py が Windows の同梱 Python で動かす）。

WSL から Windows の 127.0.0.1:8188 には届かないので、HTTP は Windows 側のこの小さな係が受け持つ。
標準ライブラリだけで書く（ComfyUI portable の同梱 Python で動く）。

  python h3_client.py status                 サーバーが応答するか（終了コード 0/1）
  python h3_client.py ensure ROOT ARGS...    応答しなければ ROOT\\ComfyUI\\main.py を窓なしで起動して待つ
  python h3_client.py run JOB.json RES.json  JOB の API グラフを投げ、終わるまで待って結果を RES に書く
  python h3_client.py free                   モデルをメモリから降ろす（VRAM を空ける。サーバーは残す）
  python h3_client.py stop ROOT              ensure で起動したサーバーを止める
"""
import json, os, subprocess, sys, time, urllib.request, urllib.error

HOST = os.environ.get("VS_COMFY_HOST", "http://127.0.0.1:8188")
for _s in (sys.stdout, sys.stderr):   # 既定は cp932 で、WSL の端末で化ける
    try: _s.reconfigure(encoding="utf-8")
    except Exception: pass


def call(path, data=None, timeout=30):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(HOST + path, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def alive():
    try:
        call("/system_stats", timeout=3); return True
    except Exception:
        return False


def ensure(root, extra):
    if alive():
        return 0
    py = os.path.join(root, "python_embeded", "python.exe")
    main = os.path.join(root, "ComfyUI", "main.py")
    if not os.path.exists(py) or not os.path.exists(main):
        print(f"ComfyUI が無い: {root}", file=sys.stderr); return 3
    log = open(os.path.join(root, "vs_server.log"), "ab")
    flags = 0x00000008 | 0x00000200 | 0x08000000 | 0x01000000   # DETACHED | NEW_GROUP | NO_WINDOW | BREAKAWAY_FROM_JOB
    args = [py, "-s", main, "--windows-standalone-build", "--disable-auto-launch"] + extra
    try:
        p = subprocess.Popen(args, cwd=root, stdout=log, stderr=log, stdin=subprocess.DEVNULL, creationflags=flags)
    except OSError:   # 親のジョブが抜け出しを許さないとき
        p = subprocess.Popen(args, cwd=root, stdout=log, stderr=log, stdin=subprocess.DEVNULL, creationflags=flags & ~0x01000000)
    open(os.path.join(root, "vs_server.pid"), "w").write(str(p.pid))
    print(f"ComfyUI を起動した (pid {p.pid})。応答を待つ", file=sys.stderr, flush=True)
    t0 = time.time()
    while time.time() - t0 < 300:
        if p.poll() is not None:
            print(f"ComfyUI が起動中に終わった (code {p.returncode})。{root}\\vs_server.log を見る", file=sys.stderr); return 3
        if alive():
            print(f"ComfyUI 応答あり ({round(time.time() - t0)}s)", file=sys.stderr); return 0
        time.sleep(2)
    print("ComfyUI が 300 秒で応答しなかった", file=sys.stderr); return 3


def run(job_path, res_path):
    job = json.load(open(job_path, encoding="utf-8"))
    smi_log = os.path.splitext(res_path)[0] + "_gpu.csv"
    smi = None
    try:
        smi = subprocess.Popen(["nvidia-smi", "--query-gpu=memory.used,temperature.gpu,power.draw", "--format=csv,noheader,nounits", "-l", "2"],
                               stdout=open(smi_log, "w"), stderr=subprocess.DEVNULL, creationflags=0x08000000)
    except OSError:
        pass
    t0 = time.time(); res = {}
    try:
        try:
            r = call("/prompt", {"prompt": job["graph"]}, timeout=60)
        except urllib.error.HTTPError as e:
            res = {"status": "rejected", "detail": e.read().decode("utf-8", "replace")[:4000]}
            return
        pid = r["prompt_id"]; last = 0
        while True:
            time.sleep(3)
            if time.time() - t0 > job.get("timeout", 3600):
                try: call("/interrupt", {})
                except Exception: pass
                res = {"status": "timeout", "prompt_id": pid}; return
            try:
                h = call("/history/" + pid)
            except Exception:
                if not alive():
                    res = {"status": "server_died", "prompt_id": pid}; return
                continue
            if pid in h:
                break
            if time.time() - last >= 30:
                last = time.time(); print(f"  生成中 {round(last - t0)}s", file=sys.stderr, flush=True)
        st = h[pid].get("status", {}); outs = []
        for o in h[pid].get("outputs", {}).values():
            for v in o.values():
                if isinstance(v, list):
                    outs += [{"filename": it["filename"], "subfolder": it.get("subfolder", ""), "type": it.get("type", "output")}
                             for it in v if isinstance(it, dict) and "filename" in it]
        res = {"status": st.get("status_str"), "prompt_id": pid, "outputs": outs}
        if st.get("status_str") != "success":
            res["messages"] = st.get("messages")
    finally:
        if smi: smi.kill()
        res["seconds"] = round(time.time() - t0, 1)
        peak = 0
        try:
            for line in open(smi_log):
                peak = max(peak, int(line.split(",")[0].strip()))
        except Exception:
            pass
        res["vram_peak_mib"] = peak
        tmp = res_path + ".part"
        json.dump(res, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1); os.replace(tmp, res_path)


def stop(root):
    pf = os.path.join(root, "vs_server.pid")
    if not os.path.exists(pf):
        print("vs が起動したサーバーの記録が無い（手で起動したものは止めない）", file=sys.stderr); return 1
    pid = open(pf).read().strip()
    r = subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True, text=True)
    os.remove(pf); print(r.stdout.strip() or r.stderr.strip(), file=sys.stderr)
    return 0 if r.returncode == 0 else 1


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "status": sys.exit(0 if alive() else 1)
    if cmd == "ensure": sys.exit(ensure(sys.argv[2], sys.argv[3:]))
    if cmd == "run": run(sys.argv[2], sys.argv[3]); sys.exit(0)
    if cmd == "free":
        try: call("/free", {"unload_models": True, "free_memory": True}); sys.exit(0)
        except Exception as e: print(e, file=sys.stderr); sys.exit(1)
    if cmd == "stop": sys.exit(stop(sys.argv[2]))
    print(__doc__, file=sys.stderr); sys.exit(2)
