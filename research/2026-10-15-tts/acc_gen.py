"""1行目のアクセント違いを何本か作る。out: scratchpad/acc/<名前>.wav（前後無音を削り 1.1倍速）"""
import json,urllib.request,base64,subprocess,os,time
k=json.load(open("/mnt/c/Users/shost/.claude.json"))["mcpServers"]["youtube-gemini"]["env"]["GEMINI_API_KEY"]
O=os.path.dirname(os.path.abspath(__file__))+"/acc"; os.makedirs(O,exist_ok=True)
NL=chr(10)
BASE=("Read aloud ONLY the Japanese text under TRANSCRIPT. Do not read these notes."+NL+
      "### DIRECTOR'S NOTES"+NL+"Speaker: a composed, mature woman with a smooth, slightly low, alluring voice. "
      "She explains injection molding playfully, as if teasing the listener. "
      "Pace: brisk and quick, noticeably faster than a normal narration, with only short pauses at commas. "
      "Use clear, lively Japanese intonation: emphasize key terms, rise and fall naturally, never monotone.")
ACC=(" Pronounce the opening phrase 薄い板 (うすいいた) as ONE smooth accent phrase in standard Tokyo accent: "
     "う low, す high, い high, い high, た low (LHHHL). Do not split it into two words; no dip between うすい and いた.")
REST="は、普通の射出成形だと、樹脂が奥まで届かない。そこで射出圧縮成形だ。"
V={"A_漢字":("薄い板"+REST,False),"B_漢字+指示":("薄い板"+REST,True),
   "C_ひらがな":("うすいいた"+REST,False),"D_ひらがな+指示":("うすいいた"+REST,True)}
M="gemini-3.8-flash-tts"
for name,(t,acc) in V.items():
    for take in (1,2):
        body={"contents":[{"parts":[{"text":BASE+(ACC if acc else "")+NL+"### TRANSCRIPT"+NL+t}]}],
              "generationConfig":{"responseModalities":["AUDIO"],"speechConfig":{"voiceConfig":{"prebuiltVoiceConfig":{"voiceName":"Kore"}}}}}
        for tr in range(3):
            try:
                req=urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{M}:generateContent?key={k}",
                    data=json.dumps(body).encode(),headers={"Content-Type":"application/json"})
                r=json.load(urllib.request.urlopen(req,timeout=300)); break
            except Exception as e: print("retry",name,e); time.sleep(5)
        raw=base64.b64decode(r["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
        out=f"{O}/{name}_{take}.wav"
        cmd=["ffmpeg","-v","error","-y","-i","-"] if raw[:4]==b"RIFF" else ["ffmpeg","-v","error","-y","-f","s16le","-ar","24000","-ac","1","-i","-"]
        trim="silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.1,areverse,atempo=1.1"
        subprocess.run(cmd+["-af",trim,"-ar","48000","-ac","1",out],input=raw,check=True); print("ok",out,flush=True)
