"""Original synthwave bed for the GRAM City ad (generated, no samples)."""
import numpy as np, wave
SR = 44100; BPM = 120; BEAT = 60 / BPM; DUR = 33.5
N = int(SR * DUR); t = np.arange(N) / SR
L = np.zeros(N); R = np.zeros(N)

def note(m): return 440.0 * 2 ** ((m - 69) / 12)
def env(n, a, d, s, r, sus_len):
    a, d, r = int(a * SR), int(d * SR), int(r * SR); sus = max(0, int(sus_len * SR) - a - d)
    e = np.concatenate([np.linspace(0, 1, a, False), np.linspace(1, s, d, False), np.full(sus, s), np.linspace(s, 0, r)])
    return e[:n] if len(e) >= n else np.pad(e, (0, n - len(e)))
def saw(f, n, detune=0.0):
    x = np.arange(n) / SR
    return sum(2 * ((x * f * (1 + d)) % 1) - 1 for d in (-detune, 0, detune)) / 3
def lowpass(x, cutoff):
    a = np.exp(-2 * np.pi * cutoff / SR); y = np.zeros_like(x); acc = 0.0
    for i in range(len(x)):
        acc = (1 - a) * x[i] + a * acc; y[i] = acc
    return y
def add(sig, start, gain=1.0, pan=0.0):
    i = int(start * SR); j = min(N, i + len(sig))
    if i >= N: return
    s = sig[:j - i] * gain
    L[i:j] += s * (1 - max(0, pan)); R[i:j] += s * (1 + min(0, pan))

# chords: Am F C G (2 beats each bar of 4 -> one chord per bar)
prog = [(57, [57, 60, 64]), (53, [53, 57, 60]), (48, [48, 52, 55]), (55, [55, 59, 62])]
bar = 4 * BEAT
start_beat = 3.0                    # music body starts after the intro riser
bars = int((DUR - start_beat - 2.0) / bar) + 1

# intro riser (noise sweep) + soft pad
n = int(3.0 * SR); noise = np.random.default_rng(1).normal(0, 1, n)
riser = lowpass(noise, 1200) * np.linspace(0, 1, n) ** 2 * 0.35
add(riser, 0.0, 1.0)
pad0 = sum(saw(note(m + 12), n, 0.006) for m in prog[0][1]) / 3 * env(n, 1.2, 0.5, 0.8, 0.8, 3.0)
add(lowpass(pad0, 900), 0.0, 0.18)

for b in range(bars):
    root, ch = prog[b % 4]; t0 = start_beat + b * bar
    # pad
    n = int(bar * SR)
    pad = sum(saw(note(m + 12), n, 0.007) for m in ch) / 3 * env(n, 0.15, 0.3, 0.75, 0.4, bar)
    add(lowpass(pad, 1400), t0, 0.16, -0.2); add(lowpass(pad, 1400), t0 + 0.012, 0.16, 0.2)
    for k in range(8):                                   # 8th-note bass
        nn = int(BEAT / 2 * SR)
        bs = saw(note(root - 12 + (12 if k % 4 == 3 else 0)), nn, 0.002) * env(nn, 0.005, 0.12, 0.45, 0.05, BEAT / 2)
        add(lowpass(bs, 700), t0 + k * BEAT / 2, 0.42)
    for k in range(4):                                   # kick on every beat
        nn = int(0.35 * SR); x = np.arange(nn) / SR
        f = 45 + 110 * np.exp(-x * 30); ph = 2 * np.pi * np.cumsum(f) / SR
        add(np.sin(ph) * np.exp(-x * 9), t0 + k * BEAT, 0.9)
    for k in (1, 3):                                     # snare on 2 & 4
        nn = int(0.22 * SR); x = np.arange(nn) / SR
        sn = (np.random.default_rng(b * 10 + k).normal(0, 1, nn) * 0.6 + np.sin(2 * np.pi * 190 * x) * 0.5) * np.exp(-x * 18)
        add(sn, t0 + k * BEAT, 0.32)
    for k in range(8):                                   # hi-hats
        nn = int(0.05 * SR); hh = np.random.default_rng(b * 100 + k).normal(0, 1, nn)
        hh = hh - lowpass(hh, 6000); add(hh * np.exp(-np.arange(nn) / SR * 70), t0 + k * BEAT / 2, 0.10, 0.3 if k % 2 else -0.3)
    if b >= 2:                                           # pluck arpeggio from bar 3
        arp = [ch[0] + 24, ch[1] + 24, ch[2] + 24, ch[1] + 24]
        for k in range(16):
            nn = int(BEAT / 4 * SR * 1.6); x = np.arange(nn) / SR
            m = arp[k % 4]
            pl = (np.sign(np.sin(2 * np.pi * note(m) * x)) * 0.3 + np.sin(2 * np.pi * note(m) * x)) * np.exp(-x * 14)
            add(lowpass(pl, 3500), t0 + k * BEAT / 4, 0.07, 0.35 if k % 2 else -0.35)

# whooshes on scene changes, impact at the outro
for ts in (3.0, 7.0, 10.5, 13.5, 17.5, 21.0, 25.0, 29.5):
    nn = int(0.45 * SR); w = np.random.default_rng(int(ts * 10)).normal(0, 1, nn)
    w = lowpass(w, 2500) * np.sin(np.linspace(0, np.pi, nn)) ** 2
    add(w, ts - 0.25, 0.22)
nn = int(2.5 * SR); x = np.arange(nn) / SR
impact = np.sin(2 * np.pi * (40 + 60 * np.exp(-x * 6)) * x) * np.exp(-x * 2.2)
add(impact, 29.5, 0.9)
outro_pad = sum(saw(note(m + 12), nn, 0.006) for m in prog[0][1]) / 3 * env(nn, 0.05, 0.6, 0.6, 1.5, 2.5)
add(lowpass(outro_pad, 1600), 29.5, 0.22)

mix = np.stack([L, R], 1)
mix *= np.minimum(1, np.minimum(t / 0.3, (DUR - t) / 2.0))[:, None]   # fade in/out
mix = np.tanh(mix * 1.15) * 0.92                                       # soft limiter
mix /= max(1e-6, np.abs(mix).max()) / 0.95
with wave.open("music.wav", "wb") as f:
    f.setnchannels(2); f.setsampwidth(2); f.setframerate(SR)
    f.writeframes((mix * 32767).astype(np.int16).tobytes())
print("music.wav", DUR, "s")
