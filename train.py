"""Train a remaining-useful-life (RUL) model.
   python train.py                  -> synthetic run-to-failure data
   python train.py history.csv      -> your data, columns: run,vib,temp,rul (rows in time order per run)"""
import sys, numpy as np, pandas as pd, joblib
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error
from model import feat, simulate_run, FEATS

CLIP = 400
def build(df):
    X, y, g = [], [], []
    for run, d in df.groupby("run", sort=False):
        v, t, r = d["vib"].values, d["temp"].values, d["rul"].values
        for i in range(len(d)):
            X.append(feat(v[:i+1], t[:i+1])); y.append(min(r[i], CLIP)); g.append(run)
    return np.array(X), np.array(y), np.array(g)

if len(sys.argv) > 1:
    df = pd.read_csv(sys.argv[1])
else:
    rng = np.random.default_rng(7); rows = []
    for k in range(90):
        v, t = simulate_run(rng); n = len(v)
        rows.append(pd.DataFrame({"run": k, "vib": v, "temp": t, "rul": n - np.arange(n)}))
    df = pd.concat(rows)

X, y, g = build(df)
test = np.isin(g, np.unique(g)[::5])           # hold out whole runs, not random rows
m = GradientBoostingRegressor(n_estimators=250, max_depth=3, learning_rate=.08, subsample=.8, random_state=1)
m.fit(X[~test], y[~test])
near = test & (y < 150)
print(f"Held-out error, all rows: {mean_absolute_error(y[test], m.predict(X[test])):.1f} h")
print(f"Held-out error, last 150 h before failure: {mean_absolute_error(y[near], m.predict(X[near])):.1f} h")
m.fit(X, y); joblib.dump(m, "model.joblib"); print("Saved model.joblib")
