"""Writes sample_history.csv in the upload format. SYNTHETIC data: use it to try the pipeline, not for decisions."""
import numpy as np, pandas as pd
from model import simulate_run
rng = np.random.default_rng(3); rows = []; t0 = pd.Timestamp("2025-01-01", tz="UTC")
for asset in ("CV-01", "CV-02", "CR-01", "HT-01", "HT-02", "LD-01"):
    t = 0
    for _ in range(4):
        v, tp = simulate_run(rng); n = len(v)
        rows += [(asset, (t0 + pd.Timedelta(hours=t + i)).isoformat(), round(v[i], 2), round(tp[i], 1), int(i == n - 1)) for i in range(n)]
        t += n + 12
pd.DataFrame(rows, columns=["asset", "ts", "vib", "temp", "failed"]).to_csv("sample_history.csv", index=False)
print(len(rows), "rows written to sample_history.csv")
