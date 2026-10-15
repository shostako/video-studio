#!/usr/bin/env bash
# 使い方: extract_pose.sh <pose>   口6枚と目2枚を、home から写した範囲で切り抜き、parts_<pose>/ に m1..m6, e1, e2 を作る
cd "$(dirname "$0")"; p=$1; PY=~/.local/share/video-scene/venv/bin/python
mapfile -t R < <($PY roi_from_home.py $p 2>/dev/null)
rm -rf parts_$p
$PY extract_parts.py ../hedra/poses/pose_$p.png parts_$p --roi=${R[0]} parts/${p}_m1.png parts/${p}_m2.png parts/${p}_m3.png parts/${p}_m4.png parts/${p}_m5.png parts/${p}_m6.png > /tmp/ex_${p}_m.log 2>&1
$PY extract_parts.py ../hedra/poses/pose_$p.png parts_$p --roi=${R[1]} parts/${p}_e1.png parts/${p}_e2.png > /tmp/ex_${p}_e.log 2>&1
$PY - <<PYEOF
import json, shutil
d=json.load(open('parts_$p/parts.json'))
for k,v in list(d.items()):
    nk=k.replace('${p}_','')
    if nk!=k: shutil.copy(f'parts_$p/{k}.png', f'parts_$p/{nk}.png'); d[nk]=v; del d[k]
json.dump(d,open('parts_$p/parts.json','w'),indent=1)
PYEOF
echo "$p 口範囲 ${R[0]} / 目範囲 ${R[1]}"; grep -c 部品 /tmp/ex_${p}_m.log /tmp/ex_${p}_e.log; grep -h "差が無い" /tmp/ex_${p}_*.log
