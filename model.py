"""Shared feature code, so training and live scoring use identical inputs."""
import numpy as np
W = 12  # readings per window (1 reading = 1 operating hour)
FEATS = ["vib", "temp", "vib_mean", "temp_mean", "vib_slope", "temp_slope"]

def feat(v, t):
    v, t = list(v)[-W:], list(t)[-W:]
    v = [v[0]] * (W - len(v)) + v
    t = [t[0]] * (W - len(t)) + t
    return [v[-1], t[-1], np.mean(v), np.mean(t), (v[-1]-v[0])/(W-1), (t[-1]-t[0])/(W-1)]

def simulate_run(rng, life=None):
    """One run-to-failure history: wear accelerates, vibration and temperature rise."""
    life = life or int(rng.integers(300, 700))
    wear = (np.arange(life) / life) ** 3
    return 2 + 6*wear + rng.normal(0, .3, life), 62 + 30*wear + rng.normal(0, 1.2, life)
