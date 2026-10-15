set -e
O=/mnt/c/Users/shost/AppData/Local/Temp/claude/C--Users-shost-ClaudeCode/7e7065aa-bfa7-5782-bfee-3a8676dc7de8/scratchpad/edge; mkdir -p $O; cd $O
python3 - <<'PY'
import json,os
c=json.load(open(os.path.expanduser("~/.local/share/video-scene/work/mascot-icm/config.json")))
t="\n".join(l.get("say",l["text"]) for l in c["voice"]["lines"])
t=t.replace("型締力","かたじめ力").replace("PL面","ピーエル面")
open("script.txt","w").write(t)
PY
for v in "ja-JP-NanamiNeural:+0%:Nanami_標準" "ja-JP-NanamiNeural:+15%:Nanami_早め"; do
  IFS=: read voice rate name <<< "$v"
  uvx edge-tts --voice $voice --rate=$rate -f script.txt --write-media $name.mp3
  ffprobe -v error -show_entries stream=sample_rate:format=duration -of csv=p=0 $name.mp3
done
S=$(wslpath "C:\Users\shost\AppData\Local\Temp\claude\C--Users-shost-ClaudeCode\7e7065aa-bfa7-5782-bfee-3a8676dc7de8\scratchpad\spec.py")
~/.local/share/video-scene/venv/bin/python $S Nanami_標準.mp3
