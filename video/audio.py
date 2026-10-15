"""Synthesize the 30 s soundtrack (120 BPM, A minor), synced to reel.html cue times."""
import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfilt, fftconvolve

SR, BEAT = 48000, 0.5
# same timeline as reel.html: story-time scene starts + per-scene holds (whole bars, so the groove stays aligned)
OS, HOLD = [0, 3, 7, 12, 18, 22.5, 26.5], [2, 2, 2, 2, 2, 2, 1.5]
NS = [s + sum(HOLD[:i]) for i, s in enumerate(OS)]
DUR = 30.0 + sum(HOLD)
CUTS = NS[1:]


def scene_at(t):
    return sum(s <= t for s in NS) - 1


def story(t):
    i = scene_at(t)
    return t - NS[i] + OS[i]


def to_real(s):
    i = sum(o <= s for o in OS) - 1
    return s - OS[i] + NS[i]

N = int(SR * DUR)
rng = np.random.default_rng(42)
mix, verb = np.zeros((2, N)), np.zeros((2, N))


def add(sig, at, gain=1.0, pan=0.0, send=0.0):
    i = int(at * SR)
    if i >= N:
        return
    sig = sig[: N - i] * gain
    l, r = np.sqrt((1 - pan) / 2), np.sqrt((1 + pan) / 2)
    mix[0, i:i + len(sig)] += sig * l
    mix[1, i:i + len(sig)] += sig * r
    if send:
        verb[0, i:i + len(sig)] += sig * l * send
        verb[1, i:i + len(sig)] += sig * r * send


def tl(d):
    return np.arange(int(d * SR)) / SR


def filt(x, f, kind="low", order=2):
    return sosfilt(butter(order, f, kind, fs=SR, output="sos"), x)


def kick(big=False):
    t = tl(1.2 if big else 0.45)
    f = 42 + 110 * np.exp(-t * 28)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * (2.5 if big else 7))
    s += 0.25 * filt(rng.standard_normal(len(t)), 3000) * np.exp(-t * 120)
    return np.tanh(s * 1.6)


def hat(open_=False):
    t = tl(0.25 if open_ else 0.06)
    return filt(rng.standard_normal(len(t)), 7000, "high") * np.exp(-t * (14 if open_ else 70))


def clap():
    t = tl(0.35)
    n = filt(filt(rng.standard_normal(len(t)), 900, "high"), 4500)
    env = np.exp(-t * 16) + sum(np.exp(-np.maximum(t - d, 0) * 80) * (t >= d) for d in (0.0, 0.011, 0.022)) * 0.5
    return n * env + 0.3 * np.sin(2 * np.pi * 190 * t) * np.exp(-t * 25)


def saw(f, d, voices=3, det=0.008):
    t = tl(d)
    return sum(2 * ((t * f * (1 + det * (v - voices // 2)) + rng.random()) % 1) - 1 for v in range(voices)) / voices


def whoosh(d=0.6, up=True):
    t = tl(d)
    n = rng.standard_normal(len(t))
    env = np.sin(np.pi * t / d) ** 2
    lo, hi = filt(n, 600), filt(n, 4000)
    k = t / d if up else 1 - t / d
    return (lo * (1 - k) + hi * k) * env


def riser(d):
    t = tl(d)
    f = 200 * np.exp(t / d * np.log(12))
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR)
    n = filt(rng.standard_normal(len(t)), 2500, "high")
    return (0.4 * tone + 0.6 * n) * (t / d) ** 2


def impact():
    t = tl(2.5)
    sub = np.sin(2 * np.pi * np.cumsum(55 * np.exp(-t * 1.5) + 30) / SR) * np.exp(-t * 1.6)
    noise = filt(rng.standard_normal(len(t)), 5000) * np.exp(-t * 6)
    return np.tanh(1.8 * sub + 0.6 * noise)


def glitch(d=0.4):
    t = tl(d)
    out = np.zeros(len(t))
    step = int(SR * 0.025)
    for i in range(0, len(t), step):
        f = rng.choice([110, 220, 880, 1760, 3520])
        seg = t[: min(step, len(t) - i)]
        out[i:i + len(seg)] = np.sign(np.sin(2 * np.pi * f * seg)) * (rng.random() > 0.3)
    return filt(out, 6000) * (1 - t / d)


# ---- arrangement (loops run on real time; cues map from story time) ----
ROOTS = [55.0, 43.65, 65.41, 49.0]                    # A F C G, one per bar
CHORDS = [[220, 261.6, 329.6], [174.6, 220, 261.6], [261.6, 329.6, 392], [196, 246.9, 293.7]]
DROP = (to_real(22.5), to_real(23.5))                 # stop-time under "Fast is easy."
ROLL = (to_real(20.0), to_real(21.0))                 # snare roll into the rejection
REJECT, OUTRO = to_real(21.0), NS[6]


def quiet(t):
    return DROP[0] <= t < DROP[1] or ROLL[0] <= t < ROLL[1]


# intro: logo hits + pad swell
for h in (0.5, 1.0, 1.5):
    add(kick(True), h, 0.9, send=0.3)
    add(clap(), h, 0.35, send=0.5)
add(riser(0.5), 0.0, 0.25)
add(whoosh(0.5), 1.6, 0.35, send=0.3)

# drums from the first cut
t = CUTS[0]
while t < OUTRO - 1e-9:
    sc, halftime = scene_at(t), REJECT <= t < NS[5]
    b = round(t / BEAT)
    if not quiet(t) and not (halftime and b % 2):
        add(kick(), t, 0.95)
    for off in ((0.25,) if sc < 3 else (0.125, 0.25, 0.375)):
        tt = t + off
        if not quiet(tt) and tt < OUTRO:
            add(hat(off == 0.25), tt, 0.16 if off == 0.25 else 0.07, pan=0.3 if off == 0.25 else -0.3)
    if sc == 3 and b % 2 == 1:
        add(clap(), t, 0.5, send=0.35)
    if sc == 5 and t >= DROP[1] and b % 2 == 1:
        add(clap(), t, 0.45, send=0.35)
    t += BEAT

for i in range(32):
    add(clap(), ROLL[0] + 1.0 * (1 - (1 - i / 32) ** 1.6), 0.12 + 0.3 * i / 32, send=0.2)

# bass: offbeat 8ths
t = CUTS[0]
while t < OUTRO - 1e-9:
    if not quiet(t):
        f = ROOTS[int(t // 2) % 4] * (2 if int(t * 4) % 4 == 3 else 1)
        n = filt(saw(f, 0.24, 2), 900 if scene_at(t) < 3 else 1600) * np.exp(-tl(0.24) * 9)
        add(n, t + 0.25, 0.55)
    t += BEAT

# pad
for bar in range(int(OUTRO // 2)):
    t0, d = bar * 2.0, 2.2
    p = sum(saw(f, d, 3, 0.006) for f in CHORDS[bar % 4]) / 3
    p = filt(p, 1200 if t0 < CUTS[2] else 2200) * np.minimum(1, tl(d) / 0.3) * np.minimum(1, (d - tl(d)) / 0.3)
    add(p, t0, 0.0 if DROP[0] <= t0 < DROP[1] else 0.22, send=0.6)
fin = sum(saw(f, DUR - OUTRO, 4, 0.01) for f in [110, 220, 261.6, 329.6, 440]) / 5
add(filt(fin, 2400) * np.exp(-tl(DUR - OUTRO) * 0.7), OUTRO, 0.32, send=0.8)

# transitions (wipe enters ~0.34 s before each cut)
for c in CUTS:
    add(whoosh(0.7), c - 0.5, 0.5, pan=-0.4, send=0.2)
    add(whoosh(0.7, False), c - 0.35, 0.3, pan=0.4)

# risers + hits
add(riser(1.0), CUTS[3] - 1.0, 0.35)
add(riser(1.0), ROLL[0], 0.45)
add(impact(), REJECT, 1.0, send=0.5)
add(glitch(0.45), REJECT, 0.25, pan=-0.5)
add(glitch(0.35), REJECT + 0.1, 0.2, pan=0.5)
for h in (22.5, 22.75, 23.0):        # "Fast / is / easy."
    add(kick(), to_real(h), 0.9)
    add(clap(), to_real(h), 0.4, send=0.6)
add(impact(), DROP[1], 0.7, send=0.4)  # "Correct is the job."
add(impact(), OUTRO, 0.9, send=0.6)
for h in (0, 0.12, 0.24):
    add(clap(), OUTRO + h, 0.3, send=0.7)

# UI ticks while the agent types
for t in np.arange(to_real(12.5), to_real(16.8), 0.0625):
    if rng.random() < 0.45:
        add(filt(rng.standard_normal(200), 5000, "high") * np.exp(-tl(200 / SR) * 300), t, 0.08, pan=rng.uniform(-0.6, 0.6))

# reverb send
ir_t = tl(2.2)
ir = np.stack([rng.standard_normal(len(ir_t)) * np.exp(-ir_t * 2.6) for _ in range(2)])
ir = filt(ir, 5000) * 0.06
mix += np.stack([fftconvolve(verb[i], ir[i])[:N] for i in range(2)])

# master: gentle low cut, soft clip, fades
mix = filt(mix, 28, "high")
mix = np.tanh(mix * 0.9)
mix *= np.minimum(1, np.arange(N) / (0.01 * SR))
fade = int(0.8 * SR)
mix[:, -fade:] *= np.linspace(1, 0, fade) ** 2
mix /= np.abs(mix).max() / 0.89
wavfile.write("music.wav", SR, (mix.T * 32767).astype(np.int16))
print("music.wav written")
