import json,urllib.request,base64,subprocess,os,sys
k=json.load(open("/mnt/c/Users/shost/.claude.json"))["mcpServers"]["youtube-gemini"]["env"]["GEMINI_API_KEY"]
O=os.path.dirname(os.path.abspath(__file__))+"/gemini"; os.makedirs(O,exist_ok=True)
script=open(os.path.dirname(os.path.abspath(__file__))+"/edge/script.txt").read()
NL=chr(10)
style=("Read aloud ONLY the Japanese text under TRANSCRIPT. Do not read these notes."+NL+
       "### DIRECTOR'S NOTES"+NL+"Speaker: a composed, mature woman with a smooth, slightly low, alluring voice. "
       "She explains injection molding playfully, as if teasing the listener, briskly and a bit fast. "
       "Use clear, lively Japanese intonation: emphasize key terms, rise and fall naturally, never monotone."+NL+
       "### TRANSCRIPT"+NL)
M="gemini-3.8-flash-tts"
for v in sys.argv[1:]:
    body={"contents":[{"parts":[{"text":style+script}]}],
          "generationConfig":{"responseModalities":["AUDIO"],"speechConfig":{"voiceConfig":{"prebuiltVoiceConfig":{"voiceName":v}}}}}
    req=urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{M}:generateContent?key={k}",
        data=json.dumps(body).encode(),headers={"Content-Type":"application/json"})
    try: r=json.load(urllib.request.urlopen(req,timeout=300))
    except urllib.error.HTTPError as e: print(v,"ERR",e.read()[:400]); continue
    p=r["candidates"][0]["content"]["parts"][0]["inlineData"]; raw=base64.b64decode(p["data"])
    out=f"{O}/Gemini_{v}.mp3"
    if raw[:4]==b"RIFF": cmd=["ffmpeg","-v","error","-y","-i","-"]
    else: cmd=["ffmpeg","-v","error","-y","-f","s16le","-ar","24000","-ac","1","-i","-"]
    subprocess.run(cmd+["-c:a","libmp3lame","-b:a","192k",out],input=raw,check=True)
    print(v,p["mimeType"],raw[:4],out)
