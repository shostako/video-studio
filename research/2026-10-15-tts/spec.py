import sys, subprocess, numpy as np
def load(p):
    raw = subprocess.run(["ffmpeg","-v","error","-i",p,"-vn","-ac","1","-ar","48000","-f","f32le","-"],capture_output=True).stdout
    return np.frombuffer(raw,np.float32)
def sr(p):
    return subprocess.run(["ffprobe","-v","error","-select_streams","a:0","-show_entries","stream=sample_rate,codec_name,bit_rate","-of","csv=p=0",p],capture_output=True,text=True).stdout.strip()
bands=[(0,300),(300,1000),(1000,3000),(3000,5000),(5000,8000),(8000,11000),(11000,12000),(12000,16000),(16000,24000)]
for p in sys.argv[1:]:
    x=load(p); n=4096; w=np.hanning(n)
    fr=np.lib.stride_tricks.sliding_window_view(x,n)[::1024]*w
    rms=np.sqrt((fr**2).mean(1)); fr=fr[rms>np.percentile(rms,60)]   # 発話部分だけ
    P=(np.abs(np.fft.rfft(fr,axis=1))**2).mean(0); f=np.fft.rfftfreq(n,1/48000); tot=P.sum()
    print(f"== {p.split('/')[-1]}  [{sr(p)}]")
    print("  "+"  ".join(f"{a//1000 if a>=1000 else a}-{b/1000:g}k:{10*np.log10(P[(f>=a)&(f<b)].sum()/tot+1e-12):6.1f}" for a,b in bands))
    c=np.cumsum(P)/tot; print(f"  99%エネルギー上限 {f[np.searchsorted(c,0.99)]:.0f}Hz  99.9% {f[np.searchsorted(c,0.999)]:.0f}Hz")
