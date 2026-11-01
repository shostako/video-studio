"""一括で読ませた wav を、台本の行の終わりに一番近い無音で切る。Whisper の語の時刻と台本を文字で突き合わせる。
python split_align.py <作業フォルダ/mascot> <whole.wav>"""
import sys,os,json,re,subprocess,difflib
sys.path.insert(0,os.path.expanduser('~/.claude/skills/video-scene/scripts'))
from ear import read_audio; from faster_whisper import WhisperModel
import pykakasi; KK=pykakasi.kakasi()
W,whole=sys.argv[1],sys.argv[2]
lines=json.load(open(f"{W}/config.json",encoding="utf-8"))["voice"]["lines"]
def hira(s): return "".join(ch for ch in "".join(t["hira"] for t in KK.convert(s)) if "ぁ"<=ch<="ゖ")
s,_=WhisperModel('medium',device='cpu',compute_type='int8').transcribe(read_audio(whole),language='ja',word_timestamps=True,condition_on_previous_text=False)
hs=[];ht=[]
for x in s:
    for w in x.words:
        h=hira(w.word)
        for k,ch in enumerate(h): hs.append(ch); ht.append(w.start+(w.end-w.start)*(k+1)/len(h))
ref="";ends=[]
for l in lines: ref+=hira(l["text"]); ends.append(len(ref)-1)
m=difflib.SequenceMatcher(None,ref,"".join(hs),autojunk=False); mp={}
for a,b,n in m.get_matching_blocks():
    for i in range(n): mp[a+i]=b+i
def t_of(i):
    while i>=0 and i not in mp: i-=1
    return ht[mp[i]] if i>=0 else 0.0
e=subprocess.run(["ffmpeg","-i",whole,"-af","silencedetect=noise=-40dB:d=0.1","-f","null","-"],capture_output=True,text=True).stderr
sil=list(zip([float(x) for x in re.findall(r"silence_start: ([\d.]+)",e)],[float(x) for x in re.findall(r"silence_end: ([\d.]+)",e)]))
total=float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",whole],capture_output=True,text=True).stdout)
bounds=[0.0]
for i in ends[:-1]:
    t=t_of(i); c=[x for x in sil if abs((x[0]+x[1])/2-t)<=1.2] or sil; a,b=max(c,key=lambda s:s[1]-s[0]) if c is not sil else min(sil,key=lambda s:abs((s[0]+s[1])/2-t)); bounds.append((a+b)/2); print(f"行末 {t:.2f}s → 無音 {a:.2f}-{b:.2f}")
bounds.append(total)
trim="silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.1,areverse"
for n in range(1,len(lines)+1):
    out=f"{W}/voice/l{n}.wav"
    if os.path.islink(out): os.unlink(out)
    subprocess.run(["ffmpeg","-v","error","-y","-ss",f"{bounds[n-1]}","-to",f"{bounds[n]}","-i",whole,"-af",trim,"-ar","48000","-ac","1",out],check=True)
    d=float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",out],capture_output=True,text=True).stdout)
    print(f"l{n} {d:.2f}s")
