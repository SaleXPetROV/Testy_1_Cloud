"""GRAM City ad — energetic EDM bed, 128 BPM, original synthesis (no samples).
Structure (bars of 1.875 s): 0-2 build | 2-12 drop | 12-13 fill/build | 13-16 outro."""
import numpy as np, wave
from scipy.signal import lfilter, butter
SR = 44100; BPM = 128; B = 60 / BPM; BAR = 4 * B; DUR = 30.0
N = int(SR * DUR); L = np.zeros(N); R = np.zeros(N)
rng = np.random.default_rng(7)

def hz(m): return 440.0 * 2 ** ((m - 69) / 12)
def lp(x, fc, order=2):
    b, a = butter(order, min(0.99, fc / (SR / 2)), 'low'); return lfilter(b, a, x)
def hp(x, fc, order=2):
    b, a = butter(order, fc / (SR / 2), 'high'); return lfilter(b, a, x)
def env_ad(n, a, d):
    x = np.arange(n) / SR; e = np.minimum(1, x / max(a, 1e-4)) * np.exp(-np.maximum(0, x - a) / d); return e
def supersaw(f, n, voices=7, spread=0.012):
    x = np.arange(n) / SR; out = np.zeros(n)
    for k in range(voices):
        d = (k - (voices - 1) / 2) / ((voices - 1) / 2) * spread
        out += 2 * ((x * f * (1 + d) + rng.random()) % 1) - 1
    return out / voices
def add(sig, t0, g=1.0, pan=0.0):
    i = int(t0 * SR); j = min(N, i + len(sig))
    if i >= N or j <= i: return
    s = sig[:j - i] * g; L[i:j] += s * (1 - max(0, pan)); R[i:j] += s * (1 + min(0, pan))

prog = [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]]   # Am F C G
roots = [45, 41, 48, 43]
DROP = 2 * BAR; FILL = 12 * BAR; OUT = 13 * BAR

# sidechain envelope (duck on every kick of the drop / outro)
side = np.ones(N)
def duck(t0):
    i = int(t0 * SR); n = int(B * SR * 0.9); x = np.arange(n) / (B * SR * 0.9)
    j = min(N, i + n); side[i:j] = np.minimum(side[i:j], (0.25 + 0.75 * x ** 0.6)[:j - i])

# ── BUILD (0 – 2 bars): opening filter on the chords, snare roll, riser
nb = int(DROP * SR)
for c in range(2):
    ch = prog[c]; n = int(BAR * SR)
    pad = sum(supersaw(hz(m + 12), n) for m in ch) / 3
    sweep = np.linspace(400 + c * 1200, 1600 + c * 2600, n)
    seg = np.concatenate([lp(pad[k:k + 4410], sweep[k]) for k in range(0, n, 4410)])[:n]
    add(seg * np.linspace(0.5, 1, n), c * BAR, 0.22, -0.15); add(seg * np.linspace(0.5, 1, n), c * BAR + 0.011, 0.22, 0.15)
t = 0.0; step = B
while t < DROP - B / 2:                                     # accelerating snare roll
    n = int(0.12 * SR); sn = hp(rng.normal(0, 1, n), 1200) * env_ad(n, 0.001, 0.05)
    add(sn, t, 0.18 + 0.4 * t / DROP)
    step = B if t < BAR else B / 2 if t < BAR + 2 * B else B / 4 if t < DROP - B else B / 8
    t += step
n = int(DROP * SR); riser = hp(rng.normal(0, 1, n), 600) * np.linspace(0, 1, n) ** 3
add(riser, 0.0, 0.32)
x = np.arange(n) / SR; add(np.sin(2 * np.pi * np.cumsum(np.linspace(200, 1400, n)) / SR) * np.linspace(0, 1, n) ** 2, 0.0, 0.08)

# ── DROP (2 – 12 bars) + OUTRO beat (13 – 15 bars)
def kick(t0):
    n = int(0.42 * SR); x = np.arange(n) / SR
    f = 48 + 180 * np.exp(-x * 38); body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-x * 7.5)
    click = hp(rng.normal(0, 1, n), 3000) * np.exp(-x * 400) * 0.6
    add(np.tanh((body + click) * 1.8), t0, 0.95)
def clap(t0):
    n = int(0.3 * SR); x = np.arange(n) / SR; c = np.zeros(n)
    for off in (0, 0.011, 0.023):
        k = int(off * SR); c[k:] += hp(rng.normal(0, 1, n - k), 900) * np.exp(-np.arange(n - k) / SR * 22)
    add(lp(c, 7000), t0, 0.33)
def hat(t0, open_=False):
    n = int((0.18 if open_ else 0.05) * SR); h = hp(rng.normal(0, 1, n), 7000) * np.exp(-np.arange(n) / SR * (18 if open_ else 80))
    add(h, t0, 0.16 if open_ else 0.09, 0.25)

lead = [76, 74, 72, 74, 76, 79, 76, 74,   72, 72, 74, 76, 74, 72, 71, 72]      # 2-bar hook, 8ths
def drop_bar(bi, t0, with_lead=True):
    c = bi % 4
    for k in range(4):
        kick(t0 + k * B); duck(t0 + k * B); hat(t0 + k * B + B / 2, open_=True)
        if k in (1, 3): clap(t0 + k * B)
    for k in range(16): hat(t0 + k * B / 4 + (B / 8 if k % 2 else 0) * 0)
    n = int(BAR * SR)
    chords = sum(supersaw(hz(m + 12), n, 7, 0.016) for m in prog[c]) / 3
    add(lp(chords, 5200) * side[int(t0 * SR):int(t0 * SR) + n][:n], t0, 0.2, -0.3)
    add(lp(chords, 5200) * side[int(t0 * SR):int(t0 * SR) + n][:n], t0 + 0.009, 0.2, 0.3)
    for k in range(8):                                               # off-beat pumping bass
        nn = int(B / 2 * SR); f = hz(roots[c] - 12)
        bs = (supersaw(f, nn, 3, 0.004) * 0.7 + np.sin(2 * np.pi * f * np.arange(nn) / SR)) * env_ad(nn, 0.004, 0.18)
        add(np.tanh(lp(bs, 900) * 1.5), t0 + k * B / 2, 0.38)
    if with_lead:
        half = (bi % 2) * 8
        for k in range(8):
            nn = int(B / 2 * SR * 1.1); m = lead[half + k]
            pl = supersaw(hz(m), nn, 5, 0.01) * env_ad(nn, 0.003, 0.16)
            add(lp(pl, 6500), t0 + k * B / 2, 0.16, -0.2 if k % 2 else 0.2)

for bi in range(10):
    drop_bar(bi, DROP + bi * BAR, with_lead=bi >= 2)

# ── FILL (12 – 13): snare roll + riser, no kick
t = FILL; step = B / 2
while t < OUT - B / 8:
    n = int(0.1 * SR); add(hp(rng.normal(0, 1, n), 1500) * env_ad(n, 0.001, 0.04), t, 0.25 + 0.35 * (t - FILL) / BAR)
    step = B / 2 if t < FILL + 2 * B else B / 4 if t < FILL + 3 * B else B / 8; t += step
n = int(BAR * SR); add(hp(rng.normal(0, 1, n), 800) * np.linspace(0, 1, n) ** 2, FILL, 0.3)

# ── OUTRO (13 – 16): big impact, 2 bars of drop, final chord tail
n = int(3 * SR); x = np.arange(n) / SR
add(np.tanh(np.sin(2 * np.pi * (35 + 90 * np.exp(-x * 5)) * x) * np.exp(-x * 1.6) * 2), OUT, 0.9)
add(lp(hp(rng.normal(0, 1, n), 200) * np.exp(-x * 3), 6000), OUT, 0.25)
for bi in range(2):
    drop_bar(bi, OUT + bi * BAR, with_lead=True)
n = int((DUR - OUT - 2 * BAR) * SR)
tail = sum(supersaw(hz(m + 12), n, 7, 0.016) for m in prog[0]) / 3 * np.exp(-np.arange(n) / SR * 1.2)
add(lp(tail, 4000), OUT + 2 * BAR, 0.3)

mix = np.stack([L, R], 1)
mix = hp(mix.T, 25).T                                             # clean sub rumble
t = np.arange(N) / SR
mix *= np.minimum(1, (DUR - t) / 1.2)[:, None]
mix = np.tanh(mix * 1.6) / np.tanh(1.6)                           # loud, punchy limiter
mix /= np.abs(mix).max() / 0.97
with wave.open("music2.wav", "wb") as f:
    f.setnchannels(2); f.setsampwidth(2); f.setframerate(SR)
    f.writeframes((mix * 32767).astype(np.int16).tobytes())
print("music2.wav", DUR, "s | drop at", round(DROP, 3), "s | fill", round(FILL, 3), "| outro", round(OUT, 3))
