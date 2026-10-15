"""全行を1回で読ませ、行間の長い無音8か所で切って voice/l<N>.wav に置く。
python3 gm_whole.py <作業フォルダ/mascot> <voice名> [take名]"""
import json,urllib.request,base64,subprocess,os,sys,re,time
k=json.load(open("/mnt/c/Users/shost/.claude.json"))["mcpServers"]["youtube-gemini"]["env"]["GEMINI_API_KEY"]
W=sys.argv[1]; V=sys.argv[2]; TK=sys.argv[3] if len(sys.argv)>3 else "whole"
cfg=json.load(open(f"{W}/config.json",encoding="utf-8")); lines=cfg["voice"]["lines"]
NL=chr(10)
style=("Read aloud ONLY the Japanese text under TRANSCRIPT. Do not read these notes."+NL+
       "### DIRECTOR'S NOTES"+NL+"Speaker: a composed, mature woman with a smooth, slightly low, alluring voice. "
       "She explains injection molding playfully, as if teasing the listener, briskly and fast. "
       "Use clear, lively Japanese intonation: emphasize key terms, rise and fall naturally, never monotone. "
       "Leave a short pause between lines."+NL+"### TRANSCRIPT"+NL)
text=NL.join(l["text"] for l in lines)
body={"contents":[{"parts":[{"text":style+text}]}],
      "generationConfig":{"responseModalities":["AUDIO"],"speechConfig":{"voiceConfig":{"prebuiltVoiceConfig":{"voiceName":V}}}}}
for tr in range(3):
    try:
        req=urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash-tts:generateContent?key={k}",
            data=json.dumps(body).encode(),headers={"Content-Type":"application/json"})
        r=json.load(urllib.request.urlopen(req,timeout=300)); break
    except Exception as e: print("retry",e); time.sleep(5)
raw=base64.b64decode(r["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
os.makedirs(f"{W}/voice/raw",exist_ok=True); whole=f"{W}/voice/raw/{TK}.wav"
cmd=["ffmpeg","-v","error","-y","-i","-"] if raw[:4]==b"RIFF" else ["ffmpeg","-v","error","-y","-f","s16le","-ar","24000","-ac","1","-i","-"]
subprocess.run(cmd+["-ar","48000","-ac","1",whole],input=raw,check=True)
# 無音を拾い、長い順に8か所を行の切れ目にする
e=subprocess.run(["ffmpeg","-i",whole,"-af","silencedetect=noise=-40dB:d=0.12","-f","null","-"],capture_output=True,text=True).stderr
st=[float(x) for x in re.findall(r"silence_start: ([\d.]+)",e)]; en=[float(x) for x in re.findall(r"silence_end: ([\d.]+)",e)]
sil=[(a,b) for a,b in zip(st,en) if a>0.3]
cut=sorted(sorted(sil,key=lambda s:s[1]-s[0],reverse=True)[:len(lines)-1])
print("切れ目:",[(round(a,2),round(b-a,2)) for a,b in cut])
total=float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",whole],capture_output=True,text=True).stdout)
bounds=[0.0]+[(a+b)/2 for a,b in cut]+[total]
trim="silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.1,areverse"
for n in range(1,len(lines)+1):
    out=f"{W}/voice/l{n}.wav"
    if os.path.islink(out): os.unlink(out)
    subprocess.run(["ffmpeg","-v","error","-y","-ss",f"{bounds[n-1]}","-to",f"{bounds[n]}","-i",whole,"-af",trim,"-ar","48000","-ac","1",out],check=True)
    d=float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",out],capture_output=True,text=True).stdout)
    print(f"l{n} {d:.2f}s")
