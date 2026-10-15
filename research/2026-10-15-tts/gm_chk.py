import sys,os,subprocess
sys.path.insert(0,os.path.expanduser('~/.claude/skills/video-scene/scripts'))
from ear import read_audio; from faster_whisper import WhisperModel
m=WhisperModel('medium',device='cpu',compute_type='int8')
for p in sys.argv[1:]:
    s,_=m.transcribe(read_audio(p),language='ja',vad_filter=False,condition_on_previous_text=False)
    print("==",os.path.basename(p)); print("".join(x.text for x in s))
