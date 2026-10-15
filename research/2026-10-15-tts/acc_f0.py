"""各 wav の冒頭「うすいいたは」の F0 を描く。Whisper の語の時刻で「は」の手前までを切り出す。"""
import sys,os,glob,json
import parselmouth, numpy as np, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
D=sys.argv[1]; fs=sorted(glob.glob(D+"/*.wav")); words=json.load(open(D+"/words.json"))
fig,axs=plt.subplots(len(fs),1,figsize=(9,2.1*len(fs)))
for ax,f in zip(np.atleast_1d(axs),fs):
    n=os.path.basename(f); s=parselmouth.Sound(f).extract_part(0,1.6)
    p=s.to_pitch_ac(time_step=0.005,pitch_floor=100,pitch_ceiling=450); t=p.xs(); f0=p.selected_array["frequency"]; f0[f0==0]=np.nan
    st=12*np.log2(f0/np.nanmedian(f0))
    ax.plot(t,st,".",ms=2); ax.set_xlim(0,1.6); ax.set_ylim(-8,8); ax.grid(alpha=.3)
    w=words.get(n,[]); txt=" ".join(f"{x[0]}@{x[1]:.2f}-{x[2]:.2f}" for x in w[:4])
    for x in w[:4]: ax.axvline(x[2],color="r",lw=.8)
    ax.set_title(n.replace(".wav","")+"   "+txt,fontsize=8,loc="left")
plt.tight_layout(); plt.savefig(D+"/f0.png",dpi=90)
