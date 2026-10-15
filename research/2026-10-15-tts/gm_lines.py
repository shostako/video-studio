"""Gemini TTS で config.voice.lines を1行ずつ作り、voice/l<N>.wav に置く（前後の無音は削る）。
python3 gm_lines.py <作業フォルダ/mascot> <voice名> [行番号...]"""
import json,urllib.request,base64,subprocess,os,sys,time
k=json.load(open("/mnt/c/Users/shost/.claude.json"))["mcpServers"]["youtube-gemini"]["env"]["GEMINI_API_KEY"]
W=sys.argv[1]; V=sys.argv[2]; only=[int(x) for x in sys.argv[3:]]
cfg=json.load(open(f"{W}/config.json",encoding="utf-8")); lines=cfg["voice"]["lines"]
NL=chr(10)
style=("Read aloud ONLY the Japanese text under TRANSCRIPT. Do not read these notes."+NL+
       "### DIRECTOR'S NOTES"+NL+"Speaker: a composed, mature woman with a smooth, slightly low, alluring voice. "
       "She explains injection molding playfully, as if teasing the listener. "
       "Pace: brisk and quick, noticeably faster than a normal narration, with only short pauses at commas. "
       "Use clear, lively Japanese intonation: emphasize key terms, rise and fall naturally, never monotone."+NL+
       "### TRANSCRIPT"+NL)
M="gemini-3.8-flash-tts"
def dur(p): return float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",p],capture_output=True,text=True).stdout)
os.makedirs(f"{W}/voice/raw",exist_ok=True)
for n in (only or range(1,len(lines)+1)):
    t=lines[n-1].get("say",lines[n-1]["text"])
    body={"contents":[{"parts":[{"text":style+t}]}],
          "generationConfig":{"responseModalities":["AUDIO"],"speechConfig":{"voiceConfig":{"prebuiltVoiceConfig":{"voiceName":V}}}}}
    for tr in range(3):
        try:
            req=urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{M}:generateContent?key={k}",
                data=json.dumps(body).encode(),headers={"Content-Type":"application/json"})
            r=json.load(urllib.request.urlopen(req,timeout=300)); break
        except Exception as e: print("retry",n,e); time.sleep(5)
    raw=base64.b64decode(r["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
    rp=f"{W}/voice/raw/l{n}.wav"
    cmd=["ffmpeg","-v","error","-y","-i","-"] if raw[:4]==b"RIFF" else ["ffmpeg","-v","error","-y","-f","s16le","-ar","24000","-ac","1","-i","-"]
    subprocess.run(cmd+[rp],input=raw,check=True)
    out=f"{W}/voice/l{n}.wav"
    if os.path.islink(out): os.unlink(out)      # 元の Irodori を指すリンクに書き込まない
    trim="silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.1,areverse"
    subprocess.run(["ffmpeg","-v","error","-y","-i",rp,"-af",trim,"-ar","48000","-ac","1",out],check=True)
    print(f"l{n} {dur(out):.2f}s  {t}",flush=True)
