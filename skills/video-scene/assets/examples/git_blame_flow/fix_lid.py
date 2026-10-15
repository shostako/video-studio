"""fix_lid.py — 実例: Flow(Veo) がノートPCの蓋の裏に画面を描いた／頭の横に文字を浮かべたのを塗り戻す（git_blame_flow 用）。
そのまま使う道具ではなく、写して数字を直す見本。数字（コマ番号・四角の座標）はこの素材専用。
  使い方: python fix_lid.py 元.mp4 直した.mp4
考え方（references/fixes.md「勝手に描かれた物を塗り戻す」）:
  1. 蓋が動かない間（36〜138コマ）は、まともなコマ（30）の蓋を同じ四角に貼る。肌（大きな塊だけ）は残す＝指は前、腕は蓋の後ろ
  2. 蓋が動く間（139〜145コマ）は、コマごとに蓋の四隅を読み、まともな蓋を射影変換で貼る
  3. 蓋の周りの照り返し・溶け残りは、蓋が閉じた後のコマ（175）を背景の板にして、コマごとに明るさを合わせ、縁をなだらかにして貼る
  4. 浮いた文字は、その四角の中で背景と違う所だけ背景の板に戻す
"""
import cv2, numpy as np, subprocess, sys
SRC, DST = sys.argv[1], sys.argv[2]
cap=cv2.VideoCapture(SRC); F=[]
while True:
    ok,fr=cap.read()
    if not ok: break
    F.append(fr)
F=np.stack(F); N,H,W=F.shape[:3]
ref=F[30].copy(); reff=ref.astype(np.float32)
RQ=np.float32([[718.5,925],[924,929],[869,1121],[662.5,1117.5]])
Q={139:[[701,921],[910,924],[893,1117],[660,1117]], 140:[[687,915],[893,919],[870,1119],[663,1119]],
   141:[[667,910],[873,913],[868,1119],[660,1119]], 142:[[645,910],[852,915],[863,1119],[660,1119]],
   143:[[623,912],[833,919],[868,1110],[661,1119]], 144:[[603,921],[813,930],[868,1110],[659,1119]],
   145:[[588,928],[793,933],[869,1112],[659,1119]]}
K=lambda n: np.ones((n,n),np.uint8)
def skin(f, minarea=150):
    hsv=cv2.cvtColor(f,cv2.COLOR_BGR2HSV); h,s,v=hsv[...,0],hsv[...,1],hsv[...,2]
    m=(((h<=22)|(h>=170))&(s>=35)&(s<=170)&(v>=110)).astype(np.uint8)
    n,lab,st,_=cv2.connectedComponentsWithStats(m); keep=np.zeros_like(m)
    for k in range(1,n):
        if st[k,4]>=minarea: keep[lab==k]=1
    return cv2.dilate(keep,K(5))>0
def bglike(f, erode=0):
    hsv=cv2.cvtColor(f,cv2.COLOR_BGR2HSV); m=((hsv[...,1]<40)&(hsv[...,2]>170)).astype(np.uint8)
    return (cv2.erode(m,K(erode)) if erode else m)>0
# 背景の板: 蓋の周りだけ（x 650-990, y 830-1112）、蓋が閉じた後のコマ 175 を使う。コマごとに明るさを合わせ、縁はなだらかに
PX0,PY0,PX1,PY1=650,830,990,1112
late=F[175].astype(np.float32)
roi=np.zeros((H,W),np.uint8); roi[PY0:PY1,PX0:PX1]=1
platebg=(roi>0)&bglike(F[175].copy(),5)
ramp=np.clip(cv2.distanceTransform(roi,cv2.DIST_L2,5)/60.0,0,1)
deck=np.array([[640,1112],[662,1112],[662.5,1117.5],[869,1121],[873,1128],[640,1128]],np.int32)
def fix(i):
    f=F[i].copy(); fs=f.astype(np.float32); sk=skin(f)
    if i in Q:
        M=cv2.getPerspectiveTransform(RQ,np.float32(Q[i])); src=cv2.warpPerspective(reff,M,(W,H),borderMode=cv2.BORDER_REPLICATE); quad=np.int32(np.round(Q[i]))
    else: src=reff; quad=np.int32(np.round(RQ))
    lid=np.zeros((H,W),np.uint8); cv2.fillPoly(lid,[quad],1); cv2.fillPoly(lid,[deck],1)
    dist=cv2.distanceTransform(1-lid,cv2.DIST_L2,5); lid=cv2.dilate(lid,K(7))>0
    mlid=lid&~sk
    hsv=cv2.cvtColor(f,cv2.COLOR_BGR2HSV)
    if i in Q: fg=(hsv[...,2]<55)|sk; fg=cv2.dilate(fg.astype(np.uint8),K(5))>0; cand=~fg
    else: cand=bglike(f,5)
    mbg=platebg&~lid&cand
    ring=mbg&(dist>70)&bglike(f,5)
    off=np.median(fs[ring]-late[ring],axis=0) if ring.sum()>500 else np.zeros(3,np.float32)
    plate=late+off
    abg=cv2.GaussianBlur(mbg.astype(np.float32),(9,9),0)*ramp
    if 37<=i<=84:   # 浮いた文字は傾斜なしで消す
        rect=np.zeros((H,W),bool); rect[840:910,695:905]=True
        d=np.abs(fs-plate).max(2)>14
        mt=(cv2.dilate((rect&d).astype(np.uint8),K(11))>0)&rect&platebg
        abg=np.maximum(abg,cv2.GaussianBlur(mt.astype(np.float32),(5,5),0))
    alid=cv2.GaussianBlur(mlid.astype(np.float32),(5,5),0)
    out=fs*(1-abg[...,None])+plate*abg[...,None]
    out=out*(1-alid[...,None])+src*alid[...,None]
    return np.clip(out,0,255).astype(np.uint8)
lo,hi=36,145
p=subprocess.Popen(['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s',f'{W}x{H}','-r','24','-i','-','-i',SRC,
                    '-map','0:v','-map','1:a','-c:v','libx264','-crf','12','-preset','slow','-pix_fmt','yuv420p','-c:a','copy',DST+'.part.mp4'],stdin=subprocess.PIPE)
for i in range(N):
    p.stdin.write((fix(i) if lo<=i<=hi else F[i]).tobytes())
p.stdin.close(); p.wait()
import os; os.replace(DST+'.part.mp4', DST) if p.returncode==0 else sys.exit('ffmpeg failed')
