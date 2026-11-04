"""Train a per-site remaining-useful-life model from a client's own history.
CSV columns: asset, ts, vib, temp, failed   (failed = 1 on the row where a breakdown happened)
ts may be ISO dates or epoch seconds/milliseconds."""
import io, numpy as np, pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
from sklearn.ensemble import GradientBoostingRegressor
from model import W
CLIP = 400
class DataError(ValueError): pass

def feats_matrix(v, t):  # vectorised twin of model.feat(): same six features, same order
    def one(x):
        w = sliding_window_view(np.concatenate([np.full(W - 1, x[0]), x]), W)
        return w[:, -1], w.mean(1), (w[:, -1] - w[:, 0]) / (W - 1)
    v1, vm, vs = one(v); t1, tm, tsl = one(t)
    return np.column_stack([v1, t1, vm, tm, vs, tsl])

def load(text):
    try: df = pd.read_csv(io.StringIO(text))
    except Exception: raise DataError("That file could not be read as a CSV.")
    df.columns = [str(c).strip().lower() for c in df.columns]
    miss = {"asset", "ts", "vib", "temp", "failed"} - set(df.columns)
    if miss: raise DataError("Missing column(s): " + ", ".join(sorted(miss)) + ". Expected: asset, ts, vib, temp, failed.")
    for c in ("vib", "temp"): df[c] = pd.to_numeric(df[c], errors="coerce")
    df["failed"] = pd.to_numeric(df["failed"], errors="coerce").fillna(0)
    n = pd.to_numeric(df["ts"], errors="coerce")
    if n.notna().mean() > .9: df["h"] = (n / 1000 if n.median() > 1e11 else n) / 3600
    else: df["h"] = (pd.to_datetime(df["ts"], errors="coerce", utc=True) - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds() / 3600
    df = df.dropna(subset=["h", "vib", "temp"]); df["asset"] = df["asset"].astype(str).str.strip()
    if len(df) < 300: raise DataError(f"Only {len(df)} usable rows. At least 300 are needed.")
    return df.sort_values(["asset", "h"])

def build(df):
    X, y, g, runs = [], [], [], 0
    for _, d in df.groupby("asset"):
        h, v, t, f = d["h"].values, d["vib"].values, d["temp"].values, d["failed"].values > 0
        start = 0
        for k in np.flatnonzero(f):
            if k - start >= W * 2:
                s = slice(start, k + 1); X.append(feats_matrix(v[s], t[s])); y.append(np.minimum(h[k] - h[s], CLIP))
                g.append(np.full(k + 1 - start, runs)); runs += 1
            start = k + 1  # readings after the last failure have no known outcome and are ignored
    if not X: raise DataError("No usable run-to-failure stretches found. Mark failures with failed=1 and send readings leading up to them.")
    return np.vstack(X), np.concatenate(y), np.concatenate(g), runs

def train(text):
    X, y, g, runs = build(load(text))
    if np.percentile(y, 95) < 24: raise DataError("The time stamps look wrong: almost every reading is less than 24 hours before a failure. Use ISO dates (2025-03-01 14:00) or epoch seconds, not row numbers.")
    if runs < 5: raise DataError(f"Found {runs} usable failure(s). At least 5 recorded failures are needed to train and check a model reliably.")
    test = np.isin(g, np.arange(runs)[::5]); near = test & (y < 150)  # whole runs held out for checking
    if near.sum() < 20: raise DataError("Not enough readings just before failures to check accuracy.")
    rng = np.random.default_rng(1)
    def fit(mask):
        idx = np.flatnonzero(mask)
        if len(idx) > 40000: idx = rng.choice(idx, 40000, replace=False)
        return GradientBoostingRegressor(n_estimators=200, max_depth=3, learning_rate=.08, subsample=.8, random_state=1).fit(X[idx], y[idx])
    m = fit(~test); base = np.median(y[~test])
    res = {"rows": int(len(y)), "failures": int(runs), "mae_near": float(np.mean(np.abs(m.predict(X[near]) - y[near]))),
           "base_near": float(np.mean(np.abs(base - y[near]))), "mae_all": float(np.mean(np.abs(m.predict(X[test]) - y[test])))}
    if res["mae_near"] > .8 * res["base_near"]:
        raise DataError(f"The model was not clearly better than a constant guess (error {res['mae_near']:.0f} h vs {res['base_near']:.0f} h), so it was not activated. Check that vibration and temperature really change before failures, or send more history.")
    return fit(np.ones(len(y), bool)), res
