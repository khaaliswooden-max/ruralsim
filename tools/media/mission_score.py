"""Original score for site/media/mission.mp4 (60 s, 72 BPM, D major).

Synthesized from scratch with NumPy: no samples or third-party recordings, so it
carries no outside rights. Writes score.wav; the site mix then applies
highpass=30 Hz, lowpass=8.5 kHz and loudnorm to -18 LUFS before muxing as AAC.
"""
import numpy as np, wave
SR=48000; DUR=60.0; N=int(SR*DUR)
BPM=72; BEAT=60/BPM; BAR=4*BEAT          # 3.333 s; 18 bars = 60 s
rng=np.random.default_rng(7)
def hz(m): return 440*2**((m-69)/12)
L=np.zeros(N); R=np.zeros(N)
def add(sig,start,pan=0.0,gain=1.0):
    i=int(start*SR); j=min(N,i+len(sig))
    if j<=i: return
    s=sig[:j-i]*gain
    L[i:j]+=s*np.sqrt(0.5*(1-pan)); R[i:j]+=s*np.sqrt(0.5*(1+pan))
def env_adsr(n,a,d,s,r):
    t=np.arange(n)/SR; T=n/SR
    e=np.where(t<a,t/a, np.where(t<a+d, 1-(1-s)*(t-a)/d, s))
    rel=np.clip((T-t)/r,0,1); return e*rel
# chords (MIDI), two bars each: Dmaj9, Bm9, Gmaj7#11, Asus2 ... ends on Dmaj9
prog=[[50,57,61,64,66],[47,54,57,61,62],[43,50,54,59,61],[45,52,57,59,64]]
chords=[prog[i%4] for i in range(9)]
# --- pad: detuned additive, slow swell
for ci,ch in enumerate(chords):
    st=ci*2*BAR; n=int((2*BAR+2.5)*SR); t=np.arange(n)/SR
    e=env_adsr(n,2.2,1.0,0.85,2.5)
    for k,m in enumerate(ch):
        f=hz(m+12 if k==0 else m)
        for det,pan in ((-0.004,-0.6),(0.004,0.6)):
            ff=f*(1+det); ph=rng.uniform(0,2*np.pi)
            s=sum(np.sin(2*np.pi*ff*h*t+ph*h)/h**1.6 for h in (1,2,3,4))
            vib=1+0.15*np.sin(2*np.pi*0.2*t+ph)
            add(s*e*vib*0.035,st,pan)
# --- sub bass: root, soft, from bar 2
for ci,ch in enumerate(chords):
    if ci==0: continue
    st=ci*2*BAR; n=int(2*BAR*SR); t=np.arange(n)/SR
    e=env_adsr(n,0.4,0.6,0.7,0.8)
    add(np.sin(2*np.pi*hz(ch[0]-12)*t)*e*0.16,st)
# --- plucked arpeggio (Karplus-Strong), enters bar 3, denser after bar 9
def pluck(f,dur=1.6,bright=0.5):
    n=int(dur*SR); p=max(2,int(SR/f)); buf=rng.uniform(-1,1,p)
    out=np.empty(n)
    for i in range(n):
        out[i]=buf[i%p]; buf[i%p]=0.5*(buf[i%p]+buf[(i+1)%p])*(0.996)
    lp=np.copy(out)
    for i in range(1,n): lp[i]=bright*out[i]+(1-bright)*lp[i-1]
    return lp*np.exp(-np.arange(n)/SR*2.2)
cache={}
pattern=[0,2,4,3,1,3,4,2]                 # eighth-note figure over chord tones
for bar in range(2,17):
    ch=chords[bar//2]; dens=8 if bar>=8 else 4
    for step in range(8):
        if dens==4 and step%2: continue
        m=ch[1+pattern[step]%4]+12
        if m not in cache: cache[m]=pluck(hz(m))
        vel=0.10*(0.85+0.3*rng.random())*(1.15 if step==0 else 1)
        add(cache[m],bar*BAR+step*BEAT/2+rng.normal(0,0.004),pan=float(np.sin(step)*0.5),gain=vel)
# --- soft pulse (felt kick + shaker) bars 8-16
for bar in range(8,16):
    for b in range(4):
        st=bar*BAR+b*BEAT
        n=int(0.35*SR); t=np.arange(n)/SR
        if b in (0,2):
            k=np.sin(2*np.pi*(55+40*np.exp(-t*30))*t)*np.exp(-t*9)
            add(k*0.14,st)
        sh=rng.normal(0,1,int(0.08*SR))*np.exp(-np.arange(int(0.08*SR))/SR*60)
        sh=np.diff(np.concatenate([[0],sh]))   # crude highpass
        add(sh*0.012,st+BEAT/2,pan=0.3)
# --- reverb: decorrelated exponential-noise IR
def reverb(x,seed):
    r=np.random.default_rng(seed); n=int(2.8*SR); t=np.arange(n)/SR
    ir=r.normal(0,1,n)*np.exp(-t*2.3); ir[:int(0.02*SR)]=0; ir/=np.sqrt((ir**2).sum())
    m=1<<int(np.ceil(np.log2(len(x)+n)))
    return np.fft.irfft(np.fft.rfft(x,m)*np.fft.rfft(ir,m),m)[:len(x)]
L=0.72*L+0.45*reverb(L,1); R=0.72*R+0.45*reverb(R,2)
# master: fades, soft limit, normalize
t=np.arange(N)/SR
fade=np.clip(t/2.0,0,1)*np.clip((DUR-t)/4.0,0,1)
L*=fade; R*=fade
peak=max(np.abs(L).max(),np.abs(R).max()); L/=peak; R/=peak
L=np.tanh(1.3*L)/np.tanh(1.3); R=np.tanh(1.3*R)/np.tanh(1.3)
L*=0.84; R*=0.84
pcm=(np.stack([L,R],1)*32767).astype('<i2')
with wave.open('score.wav','wb') as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
print('ok')
