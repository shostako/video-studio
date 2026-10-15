import sys,os,glob,json
sys.path.insert(0,os.path.expanduser('~/.claude/skills/video-scene/scripts'))
from ear import read_audio; from faster_whisper import WhisperModel
m=WhisperModel('medium',device='cpu',compute_type='int8'); D=sys.argv[1]; out={}
for f in sorted(glob.glob(D+"/*.wav")):
    s,_=m.transcribe(read_audio(f),language='ja',word_timestamps=True,condition_on_previous_text=False)
    ws=[[w.word,w.start,w.end] for x in s for w in x.words]; out[os.path.basename(f)]=ws
    print(os.path.basename(f),"".join(w[0] for w in ws)[:30])
json.dump(out,open(D+"/words.json","w"),ensure_ascii=False)
