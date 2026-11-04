import os, re, time, json, csv, io, struct, ipaddress, socket, urllib.request, urllib.parse, hmac, hashlib, base64, secrets, sqlite3, threading, collections, joblib, numpy as np
from fastapi import FastAPI, Depends, HTTPException, Request, Response, Header
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from typing import Optional
from pydantic import BaseModel, Field
from model import feat, simulate_run
from report import build_pdf
from retrain import train as train_csv, DataError
import segno

# Demo fleet for simulated sites: code -> (name, downtime cost per hour in ZAR). EDIT for real clients.
DEMO = {"HT-01": ("Haul truck 01", 38000), "HT-02": ("Haul truck 02", 38000), "LD-01": ("Front-end loader", 52000),
        "CV-02": ("Conveyor belt 02", 95000), "CR-01": ("Primary crusher", 140000), "PM-03": ("Dewatering pump", 21000)}
DEFAULT_COST, LEAD_HOURS = 50000, 36
ALLOW_SIGNUP = os.getenv("ALLOW_SIGNUP", "1") == "1"
DATA_DIR = os.getenv("DATA_DIR", "."); os.makedirs(DATA_DIR, exist_ok=True)
D = lambda *p: os.path.join(DATA_DIR, *p)

os.chdir(os.path.dirname(os.path.abspath(__file__)))  # works no matter where it is started from
app = FastAPI(title="MineSight")
def load_model():
    try: return joblib.load("model.joblib")
    except Exception:  # missing, or saved by a different scikit-learn version: retrain automatically
        import subprocess, sys
        print("Training the prediction model (about 30 seconds)...")
        subprocess.check_call([sys.executable, "train.py"]); return joblib.load("model.joblib")
M = load_model()
db = sqlite3.connect(D("minesight.db"), check_same_thread=False); db.row_factory = sqlite3.Row
db.executescript("""
create table if not exists orgs(id integer primary key, name text);
create table if not exists users(id integer primary key, org_id int, email text unique, pw text, role text);
create table if not exists sites(id integer primary key, org_id int, name text, api_key text unique, simulated int);
create table if not exists readings(site_id int, asset text, ts real, vib real, temp real, rul real);
create table if not exists alerts(site_id int, ts real, asset text, level text, msg text, gain real default 0);
create index if not exists r_idx on readings(site_id, asset, ts);
create table if not exists workorders(id integer primary key, site_id int, asset text, created real, title text, priority text, status text, assignee text, closed real);
create table if not exists resets(h text primary key, user_id int, expires real, used int default 0);
create table if not exists audit(id integer primary key, org_id int, ts real, actor text, action text, detail text);
create table if not exists models(site_id integer primary key, trained real, rows int, failures int, mae_near real, base_near real, mae_all real);
create table if not exists incidents(id integer primary key, site_id int, ts real, kind text, severity text, location text, description text, reporter text);""")
for _col in ("sites add column webhook text", "users add column totp text", "users add column totp_on int default 0",
             "users add column totp_last int default 0", "users add column token_ver int default 1", "users add column recovery text"):
    try: db.execute("alter table " + _col)
    except sqlite3.OperationalError: pass
lock = threading.RLock()
state, RUNS, FAILS = {}, {}, collections.defaultdict(list)

def q(sql, a=(), one=False):
    with lock:
        c = db.execute(sql, a); db.commit()
        return c.fetchone() if one else c.fetchall()
def ins(sql, a):
    with lock:
        c = db.execute(sql, a); db.commit(); return c.lastrowid

def audit(actor, org_id, action, detail=""):
    ins("insert into audit(org_id,ts,actor,action,detail) values(?,?,?,?,?)", (org_id or 0, time.time(), actor, action, str(detail)[:200]))

# ---------- security ----------
def _secret():
    if os.getenv("MINESIGHT_SECRET"): return os.environ["MINESIGHT_SECRET"].encode()
    if not os.path.exists(D(".secret")): open(D(".secret"), "w").write(secrets.token_hex(32))
    return open(D(".secret")).read().strip().encode()
SECRET = _secret()
def hash_pw(pw, salt=None):
    salt = salt or secrets.token_bytes(16)
    return salt.hex() + "$" + hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1).hex()
def check_pw(pw, stored): return hmac.compare_digest(hash_pw(pw, bytes.fromhex(stored.split("$")[0])), stored)
def make_token(uid, ver=1):
    body = base64.urlsafe_b64encode(json.dumps({"u": uid, "v": ver, "e": int(time.time()) + 7*86400}).encode()).decode()
    return body + "." + hmac.new(SECRET, body.encode(), "sha256").hexdigest()
def read_token(t):
    try:
        body, sig = t.split(".")
        if not hmac.compare_digest(sig, hmac.new(SECRET, body.encode(), "sha256").hexdigest()): return None
        d = json.loads(base64.urlsafe_b64decode(body)); return (d["u"], d.get("v", 1)) if d["e"] > time.time() else None
    except Exception: return None
def throttle(key):
    now = time.time(); FAILS[key] = [t for t in FAILS[key] if now - t < 300]
    if len(FAILS[key]) >= 5: raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
def set_cookie(resp, uid, ver=1):
    resp.set_cookie("ms", make_token(uid, ver), httponly=True, samesite="lax", secure=os.getenv("HTTPS") == "1", max_age=7*86400)
def current_user(request: Request):
    t = read_token(request.cookies.get("ms", ""))
    u = t and q("select * from users where id=?", (t[0],), one=True)
    if not u or u["token_ver"] != t[1]: raise HTTPException(401, "Please sign in.")  # a password change signs out old sessions
    return u
def admin_user(u=Depends(current_user)):
    if u["role"] != "admin": raise HTTPException(403, "Admins only.")
    return u
def own_site(u, sid):  # tenant isolation: a site is only reachable by its own organisation
    s = q("select * from sites where id=? and org_id=?", (sid, u["org_id"]), one=True)
    if not s: raise HTTPException(404, "Site not found.")
    return s

# ---------- prediction ----------
def alert(site, a, level, msg, gain=0):
    ins("insert into alerts values(?,?,?,?,?,?)", (site, time.time(), a, level, msg, gain))
    if level in ("warning", "critical"): notify(site, a, level, msg)

def ensure_wo(site, a, name, level, rul):  # one open work order per asset; escalate priority instead of duplicating
    pr, title = ("urgent" if level == "critical" else "planned"), f"Inspect {name}: failure predicted in about {rul:.0f} h"
    o = q("select id from workorders where site_id=? and asset=? and status!='done'", (site, a), one=True)
    if o: q("update workorders set priority=?, title=? where id=?", (pr, title, o["id"]))
    else: ins("insert into workorders(site_id,asset,created,title,priority,status) values(?,?,?,?,?,'open')", (site, a, time.time(), title, pr, ))

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
OPENER = urllib.request.build_opener(_NoRedirect)
def safe_url(u):  # https only, public addresses only (blocks requests to internal networks)
    p = urllib.parse.urlparse(u)
    if p.scheme != "https" or not p.hostname: return False
    try:
        for _, _, _, _, sa in socket.getaddrinfo(p.hostname, p.port or 443):
            ip = ipaddress.ip_address(sa[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast: return False
        return True
    except Exception: return False
def post_hook(url, payload):
    if not safe_url(url): return
    try: OPENER.open(urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json"}), timeout=5)
    except Exception: pass
def notify(site, a, level, msg):
    r = q("select name, webhook from sites where id=?", (site,), one=True)
    if r and r["webhook"]:
        threading.Thread(target=post_hook, args=(r["webhook"], {"text": f"[{r['name']}] {msg}", "site": r["name"], "asset": a, "level": level}), daemon=True).start()

MODELS, TRAIN_LOCK = {}, threading.Lock()
def get_model(site):  # per-site custom model if one was trained, otherwise the standard model
    if site not in MODELS:
        p = D("models", f"site_{site}.joblib"); MODELS[site] = joblib.load(p) if os.path.exists(p) else M
    return MODELS[site]

def process(site, a, vib, temp, ts=None):
    ts = ts or time.time()
    with lock:
        s = state.setdefault((site, a), {"name": DEMO.get(a, (a,))[0], "level": "ok", "hv": collections.deque(maxlen=12),
                                         "ht": collections.deque(maxlen=12), "trend": collections.deque(maxlen=40)})
        s["hv"].append(vib); s["ht"].append(temp); s["trend"].append(round(vib, 2))
        rul = float(np.clip(get_model(site).predict([feat(s["hv"], s["ht"])])[0], 0, 400))
        raw = "critical" if rul < 48 else "warning" if rul < 120 else "ok"
        rank, prev = {"ok": 0, "warning": 1, "critical": 2}, s["level"]
        level = raw
        if rank[raw] < rank[prev] and rul < {"critical": 60, "warning": 140}[prev]:
            level = prev  # hysteresis: noisy readings must clearly improve before a level steps down
        if rank[level] > rank[prev]:  # alert only when things get worse
            alert(site, a, level, f"{s['name']}: predicted failure in about {rul:.0f} h. Work order raised.")
            ensure_wo(site, a, s["name"], level, rul)
        s.update(vib=vib, temp=temp, rul=rul, level=level)
        ins("insert into readings values(?,?,?,?,?,?)", (site, a, ts, vib, temp, rul))
    return {"asset": a, "rul_hours": round(rul, 1), "level": level}

def maintenance(site, a):
    with lock:
        s = state.get((site, a))
        if s and s["level"] != "ok":
            gain = LEAD_HOURS * DEMO.get(a, (a, DEFAULT_COST))[1]
            alert(site, a, "ok", f"{s['name']}: planned repair done before breakdown. Downtime avoided: R{gain:,.0f}.", gain)
            q("update workorders set status='done', closed=? where site_id=? and asset=? and status!='done'", (time.time(), site, a))
            s["hv"].clear(); s["ht"].clear(); s.update(level="ok", rul=400.0)

def sim_loop():
    rng = np.random.default_rng()
    def new(site, a, start=0.0):
        v, t = simulate_run(rng); RUNS[site][a] = {"v": v, "t": t, "i": int(len(v) * start)}
    while True:
        for row in q("select id from sites where simulated=1"):
            sid = row["id"]
            if sid not in RUNS:
                RUNS[sid] = {}
                for a in DEMO: new(sid, a, rng.uniform(0, .5))
            for a in list(RUNS[sid]):
                r = RUNS[sid][a]
                if len(r["v"]) - r["i"] <= 24: maintenance(sid, a); new(sid, a); continue
                process(sid, a, float(r["v"][r["i"]]), float(r["t"][r["i"]])); r["i"] += 1
        time.sleep(1)

@app.on_event("startup")
def start(): threading.Thread(target=sim_loop, daemon=True).start()

# ---------- accounts ----------
class Signup(BaseModel):
    org: str = Field(min_length=2, max_length=80); email: str = Field(max_length=120); password: str = Field(min_length=10, max_length=200)
class Login(BaseModel):
    email: str; password: str; code: str = Field(default="", max_length=20)
class NewSite(BaseModel):
    name: str = Field(min_length=2, max_length=80); simulated: bool = False
class NewUser(BaseModel):
    email: str = Field(max_length=120); password: str = Field(min_length=10, max_length=200); role: str = "viewer"
class Reading(BaseModel):
    asset: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$"); vib: float = Field(ge=0, le=100); temp: float = Field(ge=-50, le=250); ts: Optional[float] = None

def site_row(s, admin): return {"id": s["id"], "name": s["name"], "simulated": bool(s["simulated"]), **({"api_key": s["api_key"], "webhook": s["webhook"] or ""} if admin else {})}
def valid_email(e): return re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e) is not None

@app.post("/api/signup")
def signup(b: Signup, resp: Response):
    if not ALLOW_SIGNUP and q("select 1 from users limit 1", one=True): raise HTTPException(403, "Sign-up is closed. Ask your administrator for an account.")
    e = b.email.strip().lower()
    if not valid_email(e): raise HTTPException(400, "Enter a valid email address.")
    if q("select 1 from users where email=?", (e,), one=True): raise HTTPException(409, "That email is already registered.")
    org = ins("insert into orgs(name) values(?)", (b.org.strip(),))
    uid = ins("insert into users(org_id,email,pw,role) values(?,?,?,?)", (org, e, hash_pw(b.password), "admin"))
    ins("insert into sites(org_id,name,api_key,simulated) values(?,?,?,1)", (org, "Demo pit (simulated)", "ms_" + secrets.token_urlsafe(24)))
    audit(e, org, "account_created", b.org.strip()); set_cookie(resp, uid); return {"ok": True}

@app.post("/api/login")
def login(b: Login, resp: Response, request: Request):
    e = b.email.strip().lower(); key = e + "|" + (request.client.host if request.client else "")
    throttle(key); u = q("select * from users where email=?", (e,), one=True)
    if not u or not check_pw(b.password, u["pw"]):
        FAILS[key].append(time.time()); audit(e, u["org_id"] if u else 0, "login_failed"); raise HTTPException(401, "Wrong email or password.")
    if u["totp_on"]:
        if not b.code.strip(): raise HTTPException(401, "code_required")
        if not second_ok(u, b.code): FAILS[key].append(time.time()); audit(e, u["org_id"], "login_failed_2fa"); raise HTTPException(401, "That code is not right.")
    audit(e, u["org_id"], "login"); set_cookie(resp, u["id"], u["token_ver"]); return {"ok": True}

@app.post("/api/logout")
def logout(resp: Response): resp.delete_cookie("ms"); return {"ok": True}

@app.get("/api/me")
def me(u=Depends(current_user)):
    org = q("select name from orgs where id=?", (u["org_id"],), one=True)["name"]
    sites = q("select * from sites where org_id=? order by id", (u["org_id"],))
    return {"email": u["email"], "role": u["role"], "org": org, "totp": bool(u["totp_on"]), "sites": [site_row(s, u["role"] == "admin") for s in sites]}

@app.post("/api/sites")
def add_site(b: NewSite, u=Depends(admin_user)):
    key = "ms_" + secrets.token_urlsafe(24)
    sid = ins("insert into sites(org_id,name,api_key,simulated) values(?,?,?,?)", (u["org_id"], b.name.strip(), key, int(b.simulated)))
    audit(u["email"], u["org_id"], "site_added", b.name.strip()); return {"id": sid, "api_key": key}

@app.post("/api/users")
def add_user(b: NewUser, u=Depends(admin_user)):
    e = b.email.strip().lower()
    if not valid_email(e) or b.role not in ("admin", "planner", "viewer"): raise HTTPException(400, "Check the email and role.")
    if q("select 1 from users where email=?", (e,), one=True): raise HTTPException(409, "That email is already registered.")
    ins("insert into users(org_id,email,pw,role) values(?,?,?,?)", (u["org_id"], e, hash_pw(b.password), b.role)); audit(u["email"], u["org_id"], "user_added", f"{e} as {b.role}"); return {"ok": True}

# ---------- data ----------
@app.post("/ingest")  # sensors/gateways authenticate with the site's API key
def ingest(r: Reading, x_api_key: str = Header(default="")):
    s = q("select id from sites where api_key=? and simulated=0", (x_api_key,), one=True)
    if not s: raise HTTPException(401, "Invalid API key.")
    return process(s["id"], r.asset, r.vib, r.temp, r.ts)

@app.get("/api/state")
def get_state(site: int, u=Depends(current_user)):
    s = own_site(u, site)
    with lock:
        assets = [{"id": k[1], "name": v["name"], "vib": v["vib"], "temp": v["temp"], "rul": v["rul"], "level": v["level"],
                   "trend": list(v["trend"])} for k, v in state.items() if k[0] == site and "rul" in v]
    al = q("select ts,asset,level,msg from alerts where site_id=? order by ts desc limit 15", (site,))
    saved = q("select coalesce(sum(gain),0) g from alerts where site_id=?", (site,), one=True)["g"]
    return {"assets": assets, "alerts": [dict(a) for a in al], "saved": saved, "mode": "simulated" if s["simulated"] else "live"}

@app.post("/api/fault/{site}/{asset}")
def fault(site: int, asset: str, u=Depends(current_user)):
    own_site(u, site); r = RUNS.get(site, {}).get(asset)
    if r: r["i"] = max(r["i"], int(len(r["v"]) * .72))
    return {"ok": bool(r)}

def writer(u=Depends(current_user)):
    if u["role"] == "viewer": raise HTTPException(403, "Your role is read-only.")
    return u
class WOUpdate(BaseModel):
    status: str | None = None; assignee: str | None = Field(default=None, max_length=60)
class Incident(BaseModel):
    site: int; kind: str; severity: str; location: str = Field(max_length=80); description: str = Field(min_length=3, max_length=500)
class Hook(BaseModel):
    url: str = Field(max_length=300)
KINDS = ("Near miss", "Injury", "Equipment damage", "Unsafe condition", "Environmental")

@app.get("/api/workorders")
def list_wo(site: int, u=Depends(current_user)):
    own_site(u, site)
    return [dict(r) for r in q("select id,asset,created,title,priority,status,assignee from workorders where site_id=? order by (status='done'), (priority='urgent') desc, created desc limit 30", (site,))]

@app.post("/api/workorders/{wid}")
def update_wo(wid: int, b: WOUpdate, u=Depends(writer)):
    if not q("select w.id from workorders w join sites s on s.id=w.site_id where w.id=? and s.org_id=?", (wid, u["org_id"]), one=True):
        raise HTTPException(404, "Work order not found.")
    if b.status is not None:
        if b.status not in ("open", "in_progress", "done"): raise HTTPException(400, "Unknown status.")
        q("update workorders set status=?, closed=? where id=?", (b.status, time.time() if b.status == "done" else None, wid))
    if b.assignee is not None: q("update workorders set assignee=? where id=?", (b.assignee.strip(), wid))
    audit(u["email"], u["org_id"], "work_order_updated", f"#{wid} {b.status or ''} {b.assignee or ''}".strip()); return {"ok": True}

@app.get("/api/incidents")
def list_incidents(site: int, u=Depends(current_user)):
    own_site(u, site)
    return [dict(r) for r in q("select ts,kind,severity,location,description from incidents where site_id=? order by ts desc limit 15", (site,))]

@app.post("/api/incidents")
def add_incident(b: Incident, u=Depends(writer)):
    own_site(u, b.site)
    if b.kind not in KINDS or b.severity not in ("low", "medium", "high"): raise HTTPException(400, "Check the incident type and severity.")
    ins("insert into incidents(site_id,ts,kind,severity,location,description,reporter) values(?,?,?,?,?,?,?)",
        (b.site, time.time(), b.kind, b.severity, b.location.strip(), b.description.strip(), u["email"]))
    audit(u["email"], u["org_id"], "incident_reported", f"{b.kind}, {b.severity}")
    if b.severity == "high": notify(b.site, "INCIDENT", "incident", f"HIGH severity incident: {b.kind} at {b.location}. {b.description}")
    return {"ok": True}

@app.post("/api/sites/{sid}/webhook")
def set_hook(sid: int, b: Hook, u=Depends(admin_user)):
    own_site(u, sid); url = b.url.strip()
    if url and not safe_url(url): raise HTTPException(400, "Use a public https address.")
    q("update sites set webhook=? where id=?", (url or None, sid)); audit(u["email"], u["org_id"], "webhook_changed", urllib.parse.urlparse(url).hostname or "removed"); return {"ok": True}

@app.post("/api/sites/{sid}/webhook/test")
def test_hook(sid: int, u=Depends(admin_user)):
    s = own_site(u, sid)
    if not s["webhook"]: raise HTTPException(400, "Save a webhook address first.")
    threading.Thread(target=post_hook, args=(s["webhook"], {"text": f"[{s['name']}] Test message from MineSight.", "site": s["name"], "asset": "TEST", "level": "ok"}), daemon=True).start()
    return {"ok": True}

class TrainReq(BaseModel):
    csv: str = Field(max_length=6_000_000)

@app.post("/api/sites/{sid}/train")
def train_site(sid: int, b: TrainReq, u=Depends(admin_user)):
    s = own_site(u, sid)
    if s["simulated"]: raise HTTPException(400, "Training is for live sites. Add a live site first.")
    if not TRAIN_LOCK.acquire(blocking=False): raise HTTPException(429, "Another training run is in progress. Try again in a minute.")
    try:
        try: m, res = train_csv(b.csv)
        except DataError as e: raise HTTPException(400, str(e))
        os.makedirs(D("models"), exist_ok=True); joblib.dump(m, D("models", f"site_{sid}.joblib")); MODELS[sid] = m
        ins("insert or replace into models values(?,?,?,?,?,?,?)", (sid, time.time(), res["rows"], res["failures"], res["mae_near"], res["base_near"], res["mae_all"]))
        audit(u["email"], u["org_id"], "model_trained", f"{res['failures']} failures, {res['rows']} rows")
        with lock:
            for k, v in state.items():
                if k[0] == sid: v["hv"].clear(); v["ht"].clear()  # restart each asset's window under the new model
        return res
    finally: TRAIN_LOCK.release()

@app.get("/api/sites/{sid}/model")
def model_info(sid: int, u=Depends(current_user)):
    own_site(u, sid); r = q("select * from models where site_id=?", (sid,), one=True)
    return dict(r) if r else {"source": "default"}

@app.post("/api/sites/{sid}/model/reset")
def reset_model(sid: int, u=Depends(admin_user)):
    own_site(u, sid)
    if os.path.exists(D("models", f"site_{sid}.joblib")): os.remove(D("models", f"site_{sid}.joblib"))
    MODELS.pop(sid, None); q("delete from models where site_id=?", (sid,)); audit(u["email"], u["org_id"], "model_reset"); return {"ok": True}

# ---------- password change, reset links, two-step sign-in ----------
sha = lambda x: hashlib.sha256(x.encode()).hexdigest()
def totp_at(secret, counter):
    h = hmac.new(base64.b32decode(secret), struct.pack(">Q", counter), "sha1").digest(); o = h[-1] & 15
    return f"{(struct.unpack('>I', h[o:o+4])[0] & 0x7fffffff) % 10**6:06d}"
def totp_check(u, code):  # accepts the current and adjacent 30 s windows; a code can never be used twice
    now = int(time.time() // 30)
    for c in (now, now - 1, now + 1):
        if c > (u["totp_last"] or 0) and hmac.compare_digest(totp_at(u["totp"], c), code): return c
    return None
def second_ok(u, code):  # authenticator code, or a one-time recovery code
    c = code.strip().replace(" ", "").lower()
    if re.fullmatch(r"\d{6}", c) and u["totp"]:
        n = totp_check(u, c)
        if n is None: return False
        q("update users set totp_last=? where id=?", (n, u["id"])); return True
    rec = json.loads(u["recovery"] or "[]")
    if sha(c) in rec:
        rec.remove(sha(c)); q("update users set recovery=? where id=?", (json.dumps(rec), u["id"])); return True
    return False

class PwChange(BaseModel):
    current: str = Field(max_length=200); new: str = Field(min_length=10, max_length=200)
class Code(BaseModel):
    code: str = Field(default="", max_length=20); password: str = Field(default="", max_length=200)
class ResetUse(BaseModel):
    token: str = Field(max_length=100); password: str = Field(min_length=10, max_length=200)

@app.post("/api/me/password")
def change_pw(b: PwChange, resp: Response, u=Depends(current_user)):
    key = f"pw|{u['id']}"; throttle(key)
    if not check_pw(b.current, u["pw"]): FAILS[key].append(time.time()); raise HTTPException(403, "Current password is wrong.")
    v = u["token_ver"] + 1; q("update users set pw=?, token_ver=? where id=?", (hash_pw(b.new), v, u["id"]))
    audit(u["email"], u["org_id"], "password_changed"); set_cookie(resp, u["id"], v); return {"ok": True}

@app.post("/api/me/2fa/start")
def tfa_start(u=Depends(current_user)):
    if u["totp_on"]: raise HTTPException(400, "Two-step sign-in is already on.")
    sec = base64.b32encode(secrets.token_bytes(20)).decode()
    q("update users set totp=?, totp_last=0 where id=?", (sec, u["id"]))
    uri = f"otpauth://totp/MineSight:{urllib.parse.quote(u['email'])}?secret={sec}&issuer=MineSight"
    buf = io.BytesIO(); segno.make(uri).save(buf, kind="svg", scale=4, border=2, dark="#000000", light="#ffffff", xmldecl=False)
    return {"secret": sec, "qr": buf.getvalue().decode()}

@app.post("/api/me/2fa/enable")
def tfa_enable(b: Code, u=Depends(current_user)):
    if u["totp_on"] or not u["totp"]: raise HTTPException(400, "Start the set-up first.")
    key = f"2fa|{u['id']}"; throttle(key); c = totp_check(u, b.code.strip().replace(" ", ""))
    if c is None: FAILS[key].append(time.time()); raise HTTPException(400, "That code is not right. Check the clock on your phone and try again.")
    codes = [f"{secrets.token_hex(3)[:5]}-{secrets.token_hex(3)[:5]}" for _ in range(8)]
    q("update users set totp_on=1, totp_last=?, recovery=? where id=?", (c, json.dumps([sha(x) for x in codes]), u["id"]))
    audit(u["email"], u["org_id"], "two_step_enabled"); return {"recovery": codes}

@app.post("/api/me/2fa/disable")
def tfa_disable(b: Code, u=Depends(current_user)):
    key = f"2fa|{u['id']}"; throttle(key)
    if not u["totp_on"]: raise HTTPException(400, "Two-step sign-in is not on.")
    if not check_pw(b.password, u["pw"]) or not second_ok(u, b.code): FAILS[key].append(time.time()); raise HTTPException(403, "Password or code is wrong.")
    q("update users set totp_on=0, totp=null, recovery=null where id=?", (u["id"],)); audit(u["email"], u["org_id"], "two_step_disabled"); return {"ok": True}

def member(u, uid):
    m = q("select * from users where id=? and org_id=?", (uid, u["org_id"]), one=True)
    if not m: raise HTTPException(404, "Person not found.")
    return m
@app.get("/api/users")
def team(u=Depends(admin_user)):
    return [{"id": r["id"], "email": r["email"], "role": r["role"], "totp": bool(r["totp_on"])} for r in q("select id,email,role,totp_on from users where org_id=? order by id", (u["org_id"],))]
@app.post("/api/users/{uid}/reset-link")
def reset_link(uid: int, u=Depends(admin_user)):
    m = member(u, uid); tok = secrets.token_urlsafe(32)
    q("insert into resets values(?,?,?,0)", (sha(tok), uid, time.time() + 3600)); audit(u["email"], u["org_id"], "reset_link_created", m["email"])
    return {"path": "/#reset=" + tok}  # the token sits after the #, so it never reaches server logs
@app.post("/api/users/{uid}/2fa-reset")
def tfa_reset(uid: int, u=Depends(admin_user)):
    m = member(u, uid)
    q("update users set totp_on=0, totp=null, recovery=null, token_ver=token_ver+1 where id=?", (uid,))
    audit(u["email"], u["org_id"], "two_step_reset", m["email"]); return {"ok": True}
@app.post("/api/reset")
def use_reset(b: ResetUse, request: Request):
    key = "reset|" + (request.client.host if request.client else ""); throttle(key)
    r = q("select * from resets where h=?", (sha(b.token),), one=True)
    if not r or r["used"] or r["expires"] < time.time():
        FAILS[key].append(time.time()); raise HTTPException(400, "This reset link is invalid or has expired. Ask your administrator for a new one.")
    m = q("select * from users where id=?", (r["user_id"],), one=True)
    q("update users set pw=?, token_ver=token_ver+1 where id=?", (hash_pw(b.password), m["id"])); q("update resets set used=1 where user_id=?", (m["id"],))
    audit(m["email"], m["org_id"], "password_reset"); return {"ok": True}

@app.get("/api/audit")
def get_audit(u=Depends(admin_user)):
    return [dict(r) for r in q("select ts,actor,action,detail from audit where org_id=? order by ts desc limit 40", (u["org_id"],))]

EXPORTS = {
 "workorders": "select id,asset,datetime(created,'unixepoch') created_utc,title,priority,status,assignee,datetime(closed,'unixepoch') closed_utc from workorders where site_id=? order by created desc",
 "incidents": "select datetime(ts,'unixepoch') time_utc,kind,severity,location,description,reporter from incidents where site_id=? order by ts desc",
 "alerts": "select datetime(ts,'unixepoch') time_utc,asset,level,msg message,gain downtime_avoided_rand from alerts where site_id=? order by ts desc limit 20000",
 "readings": "select datetime(ts,'unixepoch') time_utc,asset,vib,temp,round(rul,1) hours_to_failure from readings where site_id=? and ts>? order by ts desc limit 50000"}
def csv_safe(v):  # stop spreadsheet formula injection from user-entered text
    return "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") else v

@app.get("/api/export/{kind}")
def export(kind: str, site: int, u=Depends(current_user)):
    own_site(u, site)
    if kind not in EXPORTS: raise HTTPException(404, "Unknown export.")
    with lock:
        c = db.execute(EXPORTS[kind], (site, time.time() - 7*86400) if kind == "readings" else (site,))
        cols, rows = [d[0] for d in c.description], c.fetchall()
    out = io.StringIO(); w = csv.writer(out); w.writerow(cols)
    for r in rows: w.writerow([csv_safe(x) for x in r])
    audit(u["email"], u["org_id"], "data_exported", kind)
    return Response(out.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="minesight-{kind}-{site}.csv"'})

@app.get("/healthz")
def healthz(): return {"ok": True}
@app.get("/sw.js")
def sw(): return FileResponse("static/sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})
@app.get("/manifest.webmanifest")
def manifest(): return FileResponse("static/manifest.webmanifest", media_type="application/manifest+json")

@app.get("/api/report")
def report(site: int, hours: int = 24, u=Depends(current_user)):
    s = own_site(u, site); hours = max(1, min(hours, 168)); since = time.time() - hours * 3600
    audit(u["email"], u["org_id"], "report_downloaded", s["name"])
    org = q("select name from orgs where id=?", (u["org_id"],), one=True)["name"]
    with lock:
        A = sorted([(v["name"], k[1], v["vib"], v["temp"], v["rul"], v["level"]) for k, v in state.items()
                    if k[0] == site and "rul" in v], key=lambda x: x[4])
    al = [tuple(r) for r in q("select ts,asset,level,msg from alerts where site_id=? and ts>? order by ts desc limit 25", (site, since))]
    saved = q("select coalesce(sum(gain),0) g from alerts where site_id=? and ts>?", (site, since), one=True)["g"]
    n = q("select count(*) c from readings where site_id=? and ts>?", (site, since), one=True)["c"]
    orders = [tuple(r) for r in q("select asset,title,priority,status,assignee from workorders where site_id=? and status!='done' order by (priority='urgent') desc, created desc limit 15", (site,))]
    incs = [tuple(r) for r in q("select ts,kind,severity,location,description from incidents where site_id=? and ts>? order by ts desc limit 10", (site, since))]
    pdf = build_pdf(org, s["name"], hours, A, al, saved, n, int(os.getenv("TZ_OFFSET_HOURS", "2")), orders, incs)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="minesight-shift-report-{site}.pdf"'})

@app.get("/")
def home(): return FileResponse("static/index.html")

app.mount("/static", StaticFiles(directory="static"), name="static")
