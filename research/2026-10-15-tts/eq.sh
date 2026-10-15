set -e
M=~/.local/share/video-scene/work/mascot-icm/voice/master.wav
O=/mnt/c/Users/shost/AppData/Local/Temp/claude/C--Users-shost-ClaudeCode/7e7065aa-bfa7-5782-bfee-3a8676dc7de8/scratchpad/eq; mkdir -p $O; cd $O
LN="loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000"
declare -A F
F[A_元]="anull"
F[B_弱]="equalizer=f=250:t=o:w=1:g=-2,highshelf=f=3000:g=6"
F[C_強]="equalizer=f=250:t=o:w=1:g=-3,equalizer=f=4500:t=o:w=1.5:g=6,highshelf=f=6000:g=8"
for k in A_元 B_弱 C_強; do
  ffmpeg -v error -y -i $M -af "${F[$k]},$LN" -ar 48000 -ac 1 full_$k.wav
  ffmpeg -v error -y -i full_$k.wav -t 14.4 -ar 48000 -ac 1 cut_$k.wav
  ffmpeg -v error -y -i full_$k.wav -c:a aac -b:a 192k "全編_$k.m4a"
done
ffmpeg -v error -y -f lavfi -i "sine=frequency=1200:sample_rate=48000:duration=0.12" -af volume=0.25 -ac 1 beep.wav
ffmpeg -v error -y -f lavfi -i anullsrc=r=48000:cl=mono -t 0.8 sil.wav
: > l.txt
for n in 1 2 3; do k=$(echo A_元 B_弱 C_強 | cut -d" " -f$n); for i in $(seq $n); do echo "file beep.wav" >> l.txt; echo "file sil.wav">>l.txt; done; echo "file cut_$k.wav" >> l.txt; echo "file sil.wav" >> l.txt; done
ffmpeg -v error -y -f concat -safe 0 -i l.txt -c:a aac -b:a 192k "聞き比べ_元→弱→強.m4a"
S=$(wslpath "C:\Users\shost\AppData\Local\Temp\claude\C--Users-shost-ClaudeCode\7e7065aa-bfa7-5782-bfee-3a8676dc7de8\scratchpad\spec.py")
~/.local/share/video-scene/venv/bin/python $S full_A_元.wav full_B_弱.wav full_C_強.wav
ls -la *.m4a
