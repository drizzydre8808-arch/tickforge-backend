"""
TickForge standalone server — Windows VPS
Serves HTML UI + all API endpoints
Requires: fastapi, uvicorn  (already installed)
"""

from fastapi import FastAPI, HTTPException, Request, Response, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import sqlite3, os, json, uuid, hashlib, secrets, csv, io, math, threading, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from datetime import datetime, timedelta

DATA_DIR   = Path(r"C:\tickforge-data")
DB_PATH    = DATA_DIR / "sim.db"
HTML_PATH  = DATA_DIR / "index.html"
TICKS_DIR  = DATA_DIR / "ticks"
BRIDGE_TOKEN  = os.environ.get("TICKFORGE_BRIDGE_TOKEN", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GMAIL_USER    = os.environ.get("GMAIL_USER", "")
GMAIL_PASS    = os.environ.get("GMAIL_APP_PASSWORD", "")
SITE_URL      = os.environ.get("SITE_URL", "http://s6beast.com")

DATA_DIR.mkdir(exist_ok=True)
TICKS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="TickForge")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── DB ────────────────────────────────────────────────────────────────────────
_db_lock = threading.Lock()

def get_db():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with _db_lock:
        conn = get_db()
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL,
            pw_hash TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY, user_id TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tests (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, params TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued', result TEXT, error TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, runner TEXT DEFAULT 'python');
        CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL,
            kind TEXT NOT NULL, data_b64 TEXT NOT NULL, size INTEGER NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS native_tests (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, params TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued', result TEXT, error TEXT,
            runner TEXT DEFAULT 'bridge', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS journal_trades (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, source TEXT NOT NULL,
            symbol TEXT NOT NULL, side TEXT NOT NULL, volume REAL,
            open_price REAL, close_price REAL, open_time TEXT, close_time TEXT,
            profit REAL NOT NULL DEFAULT 0, commission REAL NOT NULL DEFAULT 0,
            swap REAL NOT NULL DEFAULT 0, comment TEXT, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tick_jobs (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, symbol TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued', ticks INTEGER NOT NULL DEFAULT 0,
            error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS heartbeats (
            runner TEXT PRIMARY KEY, last_seen TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS email_tokens (
            token TEXT PRIMARY KEY, user_id TEXT NOT NULL,
            type TEXT NOT NULL, expires_at TEXT NOT NULL, created_at TEXT NOT NULL);
        """)
        conn.commit()
        # Add verified column if missing (safe on re-runs)
        try:
            conn.execute("ALTER TABLE users ADD COLUMN verified INTEGER DEFAULT 0")
            conn.execute("UPDATE users SET verified=1 WHERE verified IS NULL")
            conn.commit()
        except Exception:
            pass
        conn.close()

init_db()

# ── Helpers ───────────────────────────────────────────────────────────────────
def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()
def make_token(): return secrets.token_urlsafe(32)
def now(): return datetime.utcnow().isoformat()

def get_user(request: Request):
    token = None
    auth = request.headers.get("Authorization","")
    if auth.startswith("Bearer "): token = auth[7:]
    if not token: token = request.cookies.get("tf_session")
    if not token: raise HTTPException(401, "not authenticated")
    with _db_lock:
        conn = get_db()
        row = conn.execute("SELECT user_id FROM sessions WHERE token=?", (token,)).fetchone()
        conn.close()
    if not row: raise HTTPException(401, "session expired")
    return row["user_id"]

def get_user_opt(request: Request):
    try: return get_user(request)
    except: return None

def check_bridge(request: Request):
    if not BRIDGE_TOKEN: raise HTTPException(500, "bridge token not configured")
    if request.headers.get("X-Bridge-Token") != BRIDGE_TOKEN:
        raise HTTPException(401, "invalid bridge token")

def send_email(to: str, subject: str, html: str):
    if not GMAIL_USER or not GMAIL_PASS:
        print(f"[email] {subject} → {to}  (set GMAIL_USER + GMAIL_APP_PASSWORD to send real emails)")
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"TickForge <{GMAIL_USER}>"
    msg["To"]      = to
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.starttls()
            s.login(GMAIL_USER, GMAIL_PASS)
            s.sendmail(GMAIL_USER, to, msg.as_string())
    except Exception as e:
        print(f"[email] send failed: {e}")

def make_email_token(user_id: str, kind: str, hours: int = 24) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.utcnow() + timedelta(hours=hours)).isoformat()
    with _db_lock:
        conn = get_db()
        conn.execute("DELETE FROM email_tokens WHERE user_id=? AND type=?", (user_id, kind))
        conn.execute("INSERT INTO email_tokens VALUES (?,?,?,?,?)", (token, user_id, kind, expires, now()))
        conn.commit(); conn.close()
    return token

# ── HTML ──────────────────────────────────────────────────────────────────────
@app.get("/")
async def index():
    if HTML_PATH.exists():
        return HTMLResponse(HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse(
        "<h1>TickForge</h1>"
        "<p>UI not deployed yet. Place <code>index.html</code> at "
        "<code>C:\\tickforge-data\\index.html</code> and restart.</p>"
    )

# ── Auth ──────────────────────────────────────────────────────────────────────
@app.post("/auth/signup")
async def signup(request: Request, response: Response):
    body = await request.json()
    email = body.get("email","").strip().lower()
    pw    = body.get("password","")
    if not email or not pw: raise HTTPException(400, "email and password required")
    uid = str(uuid.uuid4())
    with _db_lock:
        conn = get_db()
        try:
            conn.execute("INSERT INTO users (id,email,pw_hash,created_at,verified) VALUES (?,?,?,?,0)",
                         (uid, email, hash_pw(pw), now()))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close(); raise HTTPException(400, "email already registered")
        conn.close()
    token = make_email_token(uid, "verify", hours=48)
    link  = f"{SITE_URL}/auth/verify/{token}"
    send_email(email, "Verify your TickForge account", f"""
    <div style="font-family:sans-serif;max-width:480px;margin:40px auto;padding:32px;background:#1e222d;color:#d1d4dc;border-radius:8px;">
      <h2 style="color:#f0b90b;margin:0 0 16px">Welcome to TickForge</h2>
      <p style="margin:0 0 24px;color:#787b86;">Click the button below to verify your email and activate your account.</p>
      <a href="{link}" style="display:inline-block;padding:12px 28px;background:#f0b90b;color:#131722;font-weight:700;border-radius:4px;text-decoration:none;">Verify my email</a>
      <p style="margin:24px 0 0;font-size:12px;color:#4a4e5b;">Link expires in 48 hours. If you didn't sign up, ignore this.</p>
    </div>""")
    return {"email": email, "pending_verification": True,
            "message": "Check your email to verify your account before signing in."}

@app.post("/auth/login")
async def login(request: Request, response: Response):
    body = await request.json()
    email = body.get("email","").strip().lower()
    pw    = body.get("password","")
    with _db_lock:
        conn = get_db()
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        conn.close()
    if not row or row["pw_hash"] != hash_pw(pw):
        raise HTTPException(401, "invalid email or password")
    if not row["verified"]:
        raise HTTPException(403, "please verify your email first — check your inbox")
    token = make_token()
    with _db_lock:
        conn = get_db()
        conn.execute("INSERT INTO sessions VALUES (?,?,?)", (token, row["id"], now()))
        conn.commit(); conn.close()
    response.set_cookie("tf_session", token, httponly=True, samesite="lax")
    return {"email": email, "token": token}

@app.post("/auth/logout")
async def logout(request: Request, response: Response):
    auth = request.headers.get("Authorization","")
    token = auth[7:] if auth.startswith("Bearer ") else ""
    if token:
        with _db_lock:
            conn = get_db(); conn.execute("DELETE FROM sessions WHERE token=?", (token,)); conn.commit(); conn.close()
    response.delete_cookie("tf_session")
    return {"ok": True}

@app.get("/auth/me")
async def me(request: Request):
    uid = get_user(request)
    with _db_lock:
        conn = get_db()
        row = conn.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone()
        conn.close()
    if not row: raise HTTPException(404, "user not found")
    return {"email": row["email"]}

@app.get("/auth/verify/{token}")
async def verify_email(token: str):
    with _db_lock:
        conn = get_db()
        row = conn.execute("SELECT * FROM email_tokens WHERE token=? AND type='verify'", (token,)).fetchone()
        if not row or row["expires_at"] < now():
            conn.close()
            return HTMLResponse(_page("Link expired", "<p>This verification link has expired. <a href='/'>Sign up again</a>.</p>"))
        conn.execute("UPDATE users SET verified=1 WHERE id=?", (row["user_id"],))
        conn.execute("DELETE FROM email_tokens WHERE token=?", (token,))
        conn.commit(); conn.close()
    return HTMLResponse(_page("Email verified", """
        <p style="color:#26a69a;font-size:18px;margin-bottom:16px">✓ Your email has been verified!</p>
        <p>You can now <a href="/" style="color:#f0b90b">sign in to TickForge</a>.</p>"""))

@app.post("/auth/forgot-password")
async def forgot_password(request: Request):
    body = await request.json()
    email = body.get("email","").strip().lower()
    with _db_lock:
        conn = get_db()
        row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        conn.close()
    if row:
        token = make_email_token(row["id"], "reset", hours=2)
        link  = f"{SITE_URL}/auth/reset/{token}"
        send_email(email, "Reset your TickForge password", f"""
        <div style="font-family:sans-serif;max-width:480px;margin:40px auto;padding:32px;background:#1e222d;color:#d1d4dc;border-radius:8px;">
          <h2 style="color:#f0b90b;margin:0 0 16px">Password reset</h2>
          <p style="margin:0 0 24px;color:#787b86;">Click the button below to choose a new password. Link expires in 2 hours.</p>
          <a href="{link}" style="display:inline-block;padding:12px 28px;background:#f0b90b;color:#131722;font-weight:700;border-radius:4px;text-decoration:none;">Reset password</a>
        </div>""")
    return {"message": "If that email is registered you'll receive a reset link shortly."}

@app.get("/auth/reset/{token}")
async def reset_form(token: str):
    with _db_lock:
        conn = get_db()
        row = conn.execute("SELECT * FROM email_tokens WHERE token=? AND type='reset'", (token,)).fetchone()
        conn.close()
    if not row or row["expires_at"] < now():
        return HTMLResponse(_page("Link expired", "<p>This reset link has expired. <a href='/'>Try again</a>.</p>"))
    return HTMLResponse(_page("Reset password", f"""
        <form method="POST" style="display:flex;flex-direction:column;gap:12px;max-width:320px;margin:0 auto;">
          <input type="hidden" name="token" value="{token}">
          <input name="password" type="password" placeholder="New password" required
            style="padding:10px 14px;background:#2a2e39;border:1px solid #363c4e;color:#d1d4dc;border-radius:4px;font-size:14px;">
          <input name="confirm" type="password" placeholder="Confirm password" required
            style="padding:10px 14px;background:#2a2e39;border:1px solid #363c4e;color:#d1d4dc;border-radius:4px;font-size:14px;">
          <button type="submit"
            style="padding:11px;background:#f0b90b;color:#131722;font-weight:700;border:none;border-radius:4px;cursor:pointer;font-size:14px;">
            Set new password
          </button>
        </form>"""))

@app.post("/auth/reset/{token}")
async def reset_password(token: str, request: Request):
    form = await request.form()
    pw = form.get("password",""); confirm = form.get("confirm","")
    if pw != confirm:
        return HTMLResponse(_page("Error", "<p style='color:#ef5350'>Passwords don't match. <a href='javascript:history.back()'>Go back</a>.</p>"))
    if len(pw) < 6:
        return HTMLResponse(_page("Error", "<p style='color:#ef5350'>Password must be at least 6 characters. <a href='javascript:history.back()'>Go back</a>.</p>"))
    with _db_lock:
        conn = get_db()
        row = conn.execute("SELECT * FROM email_tokens WHERE token=? AND type='reset'", (token,)).fetchone()
        if not row or row["expires_at"] < now():
            conn.close()
            return HTMLResponse(_page("Link expired", "<p>This reset link has expired. <a href='/'>Try again</a>.</p>"))
        conn.execute("UPDATE users SET pw_hash=? WHERE id=?", (hash_pw(pw), row["user_id"]))
        conn.execute("DELETE FROM email_tokens WHERE token=?", (token,))
        conn.commit(); conn.close()
    return HTMLResponse(_page("Password updated", """
        <p style="color:#26a69a;font-size:18px;margin-bottom:16px">✓ Password updated!</p>
        <p><a href="/" style="color:#f0b90b">Sign in to TickForge</a></p>"""))

@app.post("/auth/resend-verification")
async def resend_verification(request: Request):
    body = await request.json()
    email = body.get("email","").strip().lower()
    with _db_lock:
        conn = get_db()
        row = conn.execute("SELECT * FROM users WHERE email=? AND verified=0", (email,)).fetchone()
        conn.close()
    if row:
        token = make_email_token(row["id"], "verify", hours=48)
        link  = f"{SITE_URL}/auth/verify/{token}"
        send_email(email, "Verify your TickForge account", f"""
        <div style="font-family:sans-serif;max-width:480px;margin:40px auto;padding:32px;background:#1e222d;color:#d1d4dc;border-radius:8px;">
          <h2 style="color:#f0b90b;margin:0 0 16px">Verify your email</h2>
          <a href="{link}" style="display:inline-block;padding:12px 28px;background:#f0b90b;color:#131722;font-weight:700;border-radius:4px;text-decoration:none;">Verify my email</a>
        </div>""")
    return {"message": "If your email is pending verification, a new link has been sent."}

def _page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>{title} — TickForge</title>
    <style>*{{box-sizing:border-box;margin:0;padding:0}}body{{background:#131722;color:#d1d4dc;font-family:-apple-system,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;padding:24px}}
    .card{{background:#1e222d;border:1px solid #363c4e;border-radius:8px;padding:40px;max-width:480px;width:100%;text-align:center}}
    h1{{color:#f0b90b;font-size:22px;margin-bottom:24px}}a{{color:#f0b90b}}p{{line-height:1.6;color:#787b86}}</style></head>
    <body><div class="card"><h1>TickForge</h1>{body}</div></body></html>"""

# ── Grid Strategy ─────────────────────────────────────────────────────────────
LOT_UNITS = {"XAUUSD":100,"EURUSD":100000,"GBPUSD":100000,"USDJPY":100000,"BTCUSD":1}
PIP_SIZE  = {"XAUUSD":0.10,"USDJPY":0.01}

def run_grid(ticks_iter, p):
    symbol    = p.get("symbol","XAUUSD")
    unit      = LOT_UNITS.get(symbol, 100000)
    pip       = PIP_SIZE.get(symbol, 0.0001)
    grid_step = p.get("grid_step_pips",25) * pip
    slippage  = p.get("slippage_pips",0) * pip
    deposit   = p.get("deposit",10000)
    direction = p.get("direction","buy")
    init_lot  = p.get("initial_lot",0.01)
    lot_mult  = p.get("lot_multiplier",1.6)
    tp_usd    = p.get("take_profit_usd",25)
    max_layers= p.get("max_layers",8)
    commission= p.get("commission_per_lot",7.0)
    tick_limit= p.get("tick_limit",500000)

    positions=[]; trades=[]; equity=deposit; peak=deposit; max_dd=0.0
    last_px=None; open_ts=None; n=0; eq_samples=[]

    def fpnl(bid,ask):
        t=0.0
        for s,l,e in positions:
            px=bid if s=="buy" else ask; sign=1 if s=="buy" else -1
            t+=sign*(px-e)*l*unit
        return t

    for row in ticks_iter:
        n+=1
        if n>tick_limit: break
        bid,ask=float(row[2]),float(row[3])
        px=ask if direction=="buy" else bid
        ts=row[1] if len(row)>1 else str(n)

        if not positions:
            entry=px+(slippage if direction=="buy" else -slippage)
            positions.append((direction,init_lot,entry))
            last_px=entry; open_ts=ts
        else:
            adv=(last_px-px) if direction=="buy" else (px-last_px)
            if adv>=grid_step and len(positions)<max_layers:
                nl=round(positions[-1][1]*lot_mult,2)
                entry=px+(slippage if direction=="buy" else -slippage)
                positions.append((direction,nl,entry)); last_px=entry

        fp=fpnl(bid,ask)
        if positions and fp>=tp_usd:
            total_lots=sum(x[1] for x in positions)
            comm=total_lots*commission; realized=fp-comm; equity+=realized
            avg_e=sum(x[2]*x[1] for x in positions)/total_lots
            exit_px=bid if direction=="buy" else ask
            trades.append({"side":direction,"lots":round(total_lots,2),
                "entry":round(avg_e,5),"exit":round(exit_px,5),"pnl":round(realized,2),
                "entry_ts":open_ts or "","exit_ts":ts})
            positions.clear(); last_px=None; open_ts=None

        if n%500==0:
            mtm=equity+fpnl(bid,ask); eq_samples.append([ts, mtm])
            peak=max(peak,mtm); max_dd=max(max_dd,(peak-mtm)/peak*100 if peak>0 else 0)

    wins=[t for t in trades if t["pnl"]>0]; losses=[t for t in trades if t["pnl"]<=0]
    gp=sum(t["pnl"] for t in wins); gl=-sum(t["pnl"] for t in losses)
    pf=round(gp/gl,2) if gl>0 else (999.99 if gp>0 else 0.0)
    net=round(equity-deposit,2)
    sharpe=None
    if len(eq_samples)>2:
        d=[eq_samples[i+1]-eq_samples[i] for i in range(len(eq_samples)-1)]
        mn=sum(d)/len(d); std=math.sqrt(sum((x-mn)**2 for x in d)/len(d))
        if std>0: sharpe=round(mn/std*math.sqrt(len(d)),2)
    return {
        "starting_balance":deposit,"ending_balance":round(equity,2),
        "net_profit":net,"return_pct":round(net/deposit*100,2),
        "total_trades":len(trades),"trades":len(trades),
        "wins":len(wins),"losses":len(losses),
        "win_pct":round(len(wins)/len(trades)*100,1) if trades else 0,
        "profit_factor":pf,"max_drawdown_pct":round(max_dd,2),
        "sharpe":sharpe,"ticks_processed":n,
        "open_layers_at_end":len(positions),
        "equity_curve":eq_samples,
        "trades_list":trades,
    }

def iter_ticks(symbol,dt_from,dt_to,limit=500000):
    f=TICKS_DIR/f"{symbol.upper()}.csv"
    if not f.exists(): return
    with open(str(f),newline="",encoding="utf-8") as fh:
        r=csv.reader(fh); next(r,None)
        n=0
        for row in r:
            if len(row)<3: continue
            ts=row[1] if len(row)>1 else ""
            if dt_from and ts and ts[:10]<dt_from: continue
            if dt_to and ts and ts[:10]>dt_to: break
            yield row; n+=1
            if n>=limit: break

def run_test_bg(test_id,params):
    with _db_lock:
        conn=get_db()
        conn.execute("UPDATE tests SET status='running',updated_at=? WHERE id=?",(now(),test_id))
        conn.commit(); conn.close()
    try:
        result=run_grid(iter_ticks(params.get("symbol","XAUUSD"),params.get("dt_from",""),params.get("dt_to",""),params.get("tick_limit",500000)),params)
        with _db_lock:
            conn=get_db()
            conn.execute("UPDATE tests SET status='complete',result=?,updated_at=? WHERE id=?",(json.dumps(result),now(),test_id))
            conn.commit(); conn.close()
    except Exception as e:
        with _db_lock:
            conn=get_db()
            conn.execute("UPDATE tests SET status='failed',error=?,updated_at=? WHERE id=?",(str(e),now(),test_id))
            conn.commit(); conn.close()

# ── Tests ─────────────────────────────────────────────────────────────────────
@app.post("/tests")
async def create_test(request: Request):
    uid=get_user(request); params=await request.json()
    tid=str(uuid.uuid4())[:8]
    with _db_lock:
        conn=get_db()
        conn.execute("INSERT INTO tests VALUES (?,?,?,?,?,?,?,?,?)",(tid,uid,json.dumps(params),"queued",None,None,now(),now(),"python"))
        conn.commit(); conn.close()
    threading.Thread(target=run_test_bg,args=(tid,params),daemon=True).start()
    return {"id":tid}

@app.get("/tests")
async def list_tests(request: Request):
    uid=get_user(request)
    with _db_lock:
        conn=get_db()
        rows=conn.execute("SELECT * FROM tests WHERE user_id=? ORDER BY created_at DESC LIMIT 50",(uid,)).fetchall()
        conn.close()
    return [{"id":r["id"],"status":r["status"],"params":json.loads(r["params"]),"result":json.loads(r["result"]) if r["result"] else None,"created_at":r["created_at"]} for r in rows]

@app.get("/tests/{test_id}")
async def get_test(test_id: str, request: Request):
    uid=get_user(request)
    with _db_lock:
        conn=get_db()
        row=conn.execute("SELECT * FROM tests WHERE id=? AND user_id=?",(test_id,uid)).fetchone()
        conn.close()
    if not row: raise HTTPException(404,"test not found")
    result=json.loads(row["result"]) if row["result"] else None
    return {"id":row["id"],"status":row["status"],"params":json.loads(row["params"]),"result":result,"equity":result.get("equity_curve",[]) if result else [],"created_at":row["created_at"]}

@app.get("/tests/{test_id}/trades")
async def test_trades(test_id: str, request: Request):
    uid=get_user(request)
    with _db_lock:
        conn=get_db()
        row=conn.execute("SELECT result FROM tests WHERE id=? AND user_id=?",(test_id,uid)).fetchone()
        conn.close()
    if not row or not row["result"]: return []
    return json.loads(row["result"]).get("trades_list",[])

@app.get("/tests/{test_id}/metrics")
async def test_metrics(test_id: str, request: Request):
    uid=get_user(request)
    with _db_lock:
        conn=get_db()
        row=conn.execute("SELECT result FROM tests WHERE id=? AND user_id=?",(test_id,uid)).fetchone()
        conn.close()
    if not row or not row["result"]: raise HTTPException(404,"no result")
    return json.loads(row["result"])

@app.get("/tests/{test_id}/conditions")
async def test_conditions(test_id: str, request: Request):
    return {"conditions":[]}

@app.post("/tests/{test_id}/analyze")
async def analyze_test(test_id: str, request: Request):
    uid=get_user(request)
    with _db_lock:
        conn=get_db()
        row=conn.execute("SELECT * FROM tests WHERE id=? AND user_id=?",(test_id,uid)).fetchone()
        conn.close()
    if not row or row["status"]!="complete": raise HTTPException(404,"test not found or not complete")
    r=json.loads(row["result"]); p=json.loads(row["params"])
    trades=r.get("total_trades",0); dd=r.get("max_drawdown_pct",0)
    sharpe=r.get("sharpe") or 0; win_pct=r.get("win_pct",50)
    risk=50
    if trades<20: risk+=20
    if trades>200: risk-=10
    if sharpe>2: risk-=15
    if sharpe<0: risk+=20
    if dd>30: risk+=15
    if win_pct>80: risk+=10
    risk=max(0,min(100,risk))
    findings=[]
    if trades<10: findings.append({"level":"warn","title":"Insufficient sample","text":f"Only {trades} closed trades — not statistically meaningful."})
    if dd>30: findings.append({"level":"bad","title":"High drawdown","text":f"{dd}% max drawdown — reduce lot size or max layers."})
    if r.get("net_profit",0)>0: findings.append({"level":"ok","title":"Positive expectancy","text":f"Returned +{r.get('return_pct',0)}% in this window."})
    if r.get("open_layers_at_end",0)>0: findings.append({"level":"warn","title":"Open layers at end","text":f"{r.get('open_layers_at_end')} grid layers still open — unrealized risk not reflected in results."})
    net=r.get("net_profit",0)
    verdict=f"{'Returned' if net>=0 else 'Lost'} ${abs(net):.2f} with {dd:.1f}% max drawdown over {trades} trades. {'Worth a second window.' if net>0 and dd<30 else 'Review parameters.'}"
    return {"overfit_risk":risk,"findings":findings,"verdict":verdict}

@app.post("/tests/{test_id}/ask")
async def ask_test(test_id: str, request: Request):
    uid=get_user(request); body=await request.json(); question=body.get("question","")
    with _db_lock:
        conn=get_db()
        row=conn.execute("SELECT * FROM tests WHERE id=? AND user_id=?",(test_id,uid)).fetchone()
        conn.close()
    if not row: raise HTTPException(404,"test not found")
    r=json.loads(row["result"]) if row["result"] else {}; p=json.loads(row["params"])
    if ANTHROPIC_KEY:
        try:
            import urllib.request as ur
            payload=json.dumps({"model":"claude-haiku-4-5-20251001","max_tokens":400,"messages":[{"role":"user","content":f"TickForge backtest result:\n{json.dumps(r)}\nParams: {json.dumps(p)}\nQuestion: {question}"}]}).encode()
            req=ur.Request("https://api.anthropic.com/v1/messages",data=payload,
                headers={"x-api-key":ANTHROPIC_KEY,"anthropic-version":"2023-06-01","content-type":"application/json"},method="POST")
            with ur.urlopen(req) as resp:
                return {"answer":json.loads(resp.read())["content"][0]["text"]}
        except Exception as e:
            return {"answer":f"AI error: {e}"}
    return {"answer":f"Test {test_id}: {p.get('symbol')} net P&L ${r.get('net_profit',0):.2f}, {r.get('total_trades',0)} trades, {r.get('max_drawdown_pct',0):.1f}% max DD. (Add ANTHROPIC_API_KEY for AI answers.)"}

@app.post("/tests/parallel/{path:path}")
async def parallel_stub(path: str, request: Request):
    raise HTTPException(501,"parallel backtests not available in standalone mode")

# ── Ticks ─────────────────────────────────────────────────────────────────────
@app.get("/ticks/coverage")
async def tick_coverage(request: Request):
    get_user(request); result=[]
    for f in TICKS_DIR.glob("*.csv"):
        try:
            with open(str(f),newline="",encoding="utf-8") as fh:
                r=csv.reader(fh); next(r,None); rows=list(r)
                if rows:
                    result.append({"symbol":f.stem.upper(),"ticks":len(rows),
                        "from":rows[0][1][:10] if len(rows[0])>1 else "","to":rows[-1][1][:10] if len(rows[-1])>1 else ""})
        except: pass
    return result

@app.post("/ticks/generate")
async def generate_ticks(request: Request):
    import random
    uid=get_user(request); body=await request.json()
    symbol=body.get("symbol","XAUUSD"); dt_from=body.get("dt_from","2024-01-01"); dt_to=body.get("dt_to","2024-12-31")
    n=10000; price=1900.0 if "XAU" in symbol else 1.1; spread=0.3 if "XAU" in symbol else 0.00015
    csv_path=TICKS_DIR/f"{symbol}.csv"; ts=datetime.fromisoformat(dt_from)
    with open(str(csv_path),"w",newline="") as fh:
        w=csv.writer(fh); w.writerow(["symbol","timestamp","bid","ask"])
        for _ in range(n):
            price+=random.gauss(0,0.1 if "XAU" in symbol else 0.0001)
            w.writerow([symbol,ts.isoformat(),f"{price:.5f}",f"{price+spread:.5f}"]); ts+=timedelta(seconds=60)
    return {"ticks_generated":n,"source":"synthetic","symbol":symbol}

def _run_dukascopy(jid: str, symbol: str, dt_from: str, dt_to: str):
    import subprocess, time
    script  = DATA_DIR / "download_ticks.js"
    out_csv = TICKS_DIR / f"{symbol.upper()}.csv"
    if not script.exists():
        with _db_lock:
            conn=get_db(); conn.execute("UPDATE tick_jobs SET status='failed',error=?,updated_at=? WHERE id=?",("download_ticks.js not found at C:\\tickforge-data\\",now(),jid)); conn.commit(); conn.close()
        return
    try:
        proc = subprocess.Popen(
            ["node", str(script), symbol, dt_from, dt_to, str(out_csv)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        while proc.poll() is None:
            time.sleep(4)
            if out_csv.exists():
                try:
                    count = max(0, sum(1 for _ in open(str(out_csv))) - 1)
                    with _db_lock:
                        conn=get_db(); conn.execute("UPDATE tick_jobs SET ticks=?,updated_at=? WHERE id=?",(count,now(),jid)); conn.commit(); conn.close()
                except: pass
        stdout, _ = proc.communicate()
        if proc.returncode != 0:
            raise Exception((stdout or "").strip() or "node exited with error")
        count = max(0, sum(1 for _ in open(str(out_csv))) - 1) if out_csv.exists() else 0
        with _db_lock:
            conn=get_db(); conn.execute("UPDATE tick_jobs SET status='complete',ticks=?,updated_at=? WHERE id=?",(count,now(),jid)); conn.commit(); conn.close()
    except Exception as e:
        with _db_lock:
            conn=get_db(); conn.execute("UPDATE tick_jobs SET status='failed',error=?,updated_at=? WHERE id=?",(str(e),now(),jid)); conn.commit(); conn.close()

@app.post("/ticks/download")
async def download_ticks(request: Request, background_tasks: BackgroundTasks):
    uid=get_user(request); body=await request.json()
    symbol  = body.get("symbol","XAUUSD").upper()
    dt_from = body.get("dt_from","2020-01-01")
    dt_to   = body.get("dt_to", now()[:10])
    jid=str(uuid.uuid4())[:8]
    with _db_lock:
        conn=get_db()
        conn.execute("INSERT INTO tick_jobs VALUES (?,?,?,?,?,?,?,?)",(jid,uid,symbol,"running",0,None,now(),now()))
        conn.commit(); conn.close()
    background_tasks.add_task(_run_dukascopy, jid, symbol, dt_from, dt_to)
    return {"id":jid,"status":"running","symbol":symbol,"ticks":0}

@app.get("/ticks/download/{job_id}")
async def tick_job(job_id: str, request: Request):
    uid=get_user(request)
    with _db_lock:
        conn=get_db()
        row=conn.execute("SELECT * FROM tick_jobs WHERE id=? AND user_id=?",(job_id,uid)).fetchone()
        conn.close()
    if not row: raise HTTPException(404,"job not found")
    return {"id":row["id"],"status":row["status"],"symbol":row["symbol"],
            "ticks":row["ticks"],"error":row["error"]}

# ── AllTick ───────────────────────────────────────────────────────────────────
_ALLTICK_SYM = {
    "XAUUSD":"XAUUSD.FX","XAGUSD":"XAGUSD.FX","EURUSD":"EURUSD.FX",
    "GBPUSD":"GBPUSD.FX","USDJPY":"USDJPY.FX","USDCHF":"USDCHF.FX",
    "AUDUSD":"AUDUSD.FX","USDCAD":"USDCAD.FX","NZDUSD":"NZDUSD.FX",
    "EURGBP":"EURGBP.FX","EURJPY":"EURJPY.FX","GBPJPY":"GBPJPY.FX",
    "BTCUSD":"BTC.CC","ETHUSD":"ETH.CC","SOLUSD":"SOL.CC",
}
_ALLTICK_SPREAD = {
    "XAUUSD":0.3,"XAGUSD":0.03,"EURUSD":0.00010,"GBPUSD":0.00015,
    "USDJPY":0.02,"BTCUSD":10.0,"ETHUSD":1.0,"DEFAULT":0.0002,
}

def _run_alltick(jid, symbol, dt_from, dt_to, token, kline_type):
    import json as _json, urllib.request as _ur, urllib.parse as _up, datetime as _dt
    at_sym = _ALLTICK_SYM.get(symbol, symbol+".FX")
    spread = _ALLTICK_SPREAD.get(symbol, _ALLTICK_SPREAD["DEFAULT"])
    ts_from = int(_dt.datetime.fromisoformat(dt_from).replace(tzinfo=_dt.timezone.utc).timestamp()*1000)
    ts_to   = int(_dt.datetime.fromisoformat(dt_to).replace(tzinfo=_dt.timezone.utc).timestamp()*1000)
    candles = []
    end_ts  = ts_to
    try:
        while end_ts > ts_from and len(candles) < 50000:
            q = _json.dumps({"symbol":at_sym,"kline_type":kline_type,"kline_timestamp_end":end_ts,"query_kline_num":1000,"adjust_type":0})
            url = f"https://quote.tradeswitcher.com/quote-b-api/kline?token={token}&query={_up.quote(q)}"
            req = _ur.Request(url, headers={"Content-Type":"application/json"})
            with _ur.urlopen(req, timeout=30) as resp:
                data = _json.loads(resp.read())
            if data.get("ret") != 200:
                raise Exception(f"AllTick API error: {data.get('msg','unknown')}")
            items = data.get("data",{}).get("items",[])
            if not items: break
            chunk = [c for c in items if c[0] >= ts_from]
            candles.extend(chunk)
            earliest = min(c[0] for c in items)
            if earliest <= ts_from: break
            end_ts = earliest - 1
        candles.sort(key=lambda c:c[0])
        ticks=[]
        for c in candles:
            ts_ms,o,h,l,cl = c[0],c[1],c[2],c[3],c[4]
            base = _dt.datetime.utcfromtimestamp(ts_ms/1000)
            def t(secs,p): return (base+_dt.timedelta(seconds=secs)).isoformat()
            ticks.append((symbol, t(0,o),  round(o,5),  round(o+spread,5)))
            if o <= cl:
                ticks.append((symbol, t(15,l), round(l,5), round(l+spread,5)))
                ticks.append((symbol, t(30,h), round(h,5), round(h+spread,5)))
            else:
                ticks.append((symbol, t(15,h), round(h,5), round(h+spread,5)))
                ticks.append((symbol, t(30,l), round(l,5), round(l+spread,5)))
            ticks.append((symbol, t(45,cl), round(cl,5), round(cl+spread,5)))
        with _db_lock:
            conn=get_db()
            conn.execute("DELETE FROM ticks WHERE symbol=?",(symbol,))
            conn.executemany("INSERT INTO ticks VALUES (?,?,?,?)", ticks)
            conn.execute("UPDATE tick_jobs SET status='complete',ticks=?,updated_at=? WHERE id=?",(len(ticks),now(),jid))
            conn.commit(); conn.close()
    except Exception as e:
        with _db_lock:
            conn=get_db(); conn.execute("UPDATE tick_jobs SET status='failed',error=?,updated_at=? WHERE id=?",(str(e),now(),jid)); conn.commit(); conn.close()

@app.post("/ticks/alltick")
async def download_alltick(request: Request, background_tasks: BackgroundTasks):
    uid=get_user(request); body=await request.json()
    symbol     = body.get("symbol","XAUUSD").upper()
    dt_from    = body.get("dt_from","2024-01-01")
    dt_to      = body.get("dt_to", now()[:10])
    token      = body.get("token","")
    kline_type = int(body.get("kline_type",5))
    if not token: raise HTTPException(400,"AllTick API token required")
    jid=str(uuid.uuid4())[:8]
    with _db_lock:
        conn=get_db()
        conn.execute("INSERT INTO tick_jobs VALUES (?,?,?,?,?,?,?,?)",(jid,uid,symbol,"running",0,None,now(),now()))
        conn.commit(); conn.close()
    background_tasks.add_task(_run_alltick, jid, symbol, dt_from, dt_to, token, kline_type)
    return {"id":jid,"status":"running","symbol":symbol,"ticks":0}

@app.get("/ticks/csv/{symbol}")
async def ticks_csv(symbol: str, request: Request):
    uid=get_user_opt(request); bt=request.headers.get("X-Bridge-Token","")
    if not uid and (not BRIDGE_TOKEN or bt!=BRIDGE_TOKEN): raise HTTPException(401,"auth required")
    dt_from=request.query_params.get("dt_from",""); dt_to=request.query_params.get("dt_to","")
    limit=int(request.query_params.get("limit","500000"))
    out=io.StringIO(); w=csv.writer(out); w.writerow(["symbol","timestamp","bid","ask"])
    for row in iter_ticks(symbol,dt_from,dt_to,limit): w.writerow(row)
    return Response(out.getvalue(),media_type="text/csv")

# ── Bars ──────────────────────────────────────────────────────────────────────
@app.get("/bars")
async def bars(request: Request): return []

# ── Native / Bridge ───────────────────────────────────────────────────────────
@app.post("/native/files")
async def upload_file(request: Request):
    import base64
    uid=get_user(request); body=await request.json()
    fid=str(uuid.uuid4())[:8]; name=body.get("name","file"); data=body.get("data_b64","")
    kind="set" if name.endswith(".set") else "ea"; size=len(base64.b64decode(data))
    with _db_lock:
        conn=get_db()
        conn.execute("INSERT INTO files VALUES (?,?,?,?,?,?,?)",(fid,uid,name,kind,data,size,now()))
        conn.commit(); conn.close()
    return {"id":fid,"name":name,"kind":kind,"size":size}

@app.get("/native/files")
async def list_files(request: Request):
    uid=get_user(request)
    with _db_lock:
        conn=get_db()
        rows=conn.execute("SELECT id,name,kind,size FROM files WHERE user_id=?",(uid,)).fetchall()
        conn.close()
    return [{"id":r["id"],"name":r["name"],"kind":r["kind"],"size":r["size"]} for r in rows]

@app.post("/native/tests")
async def create_native_test(request: Request):
    uid=get_user(request); params=await request.json(); tid=str(uuid.uuid4())[:8]
    with _db_lock:
        conn=get_db()
        conn.execute("INSERT INTO native_tests VALUES (?,?,?,?,?,?,?,?,?)",(tid,uid,json.dumps(params),"queued",None,None,"bridge",now(),now()))
        conn.commit(); conn.close()
    return {"id":tid}

@app.get("/native/tests")
async def list_native(request: Request):
    uid=get_user(request)
    with _db_lock:
        conn=get_db()
        rows=conn.execute("SELECT * FROM native_tests WHERE user_id=? ORDER BY created_at DESC LIMIT 20",(uid,)).fetchall()
        conn.close()
    return [{"id":r["id"],"status":r["status"],"params":json.loads(r["params"]),"result":json.loads(r["result"]) if r["result"] else None} for r in rows]

@app.get("/native/tests/{job_id}")
async def get_native(job_id: str, request: Request):
    uid=get_user(request)
    with _db_lock:
        conn=get_db()
        row=conn.execute("SELECT * FROM native_tests WHERE id=? AND user_id=?",(job_id,uid)).fetchone()
        conn.close()
    if not row: raise HTTPException(404,"not found")
    return {"id":row["id"],"status":row["status"],"params":json.loads(row["params"]),"result":json.loads(row["result"]) if row["result"] else None,"error":row["error"]}

@app.get("/native/bridge/status")
async def bridge_status(request: Request):
    with _db_lock:
        conn=get_db()
        row=conn.execute("SELECT last_seen FROM heartbeats WHERE runner='csharp'").fetchone()
        conn.close()
    configured=bool(BRIDGE_TOKEN)
    if not row: return {"configured":configured,"online":False}
    online=(datetime.utcnow()-datetime.fromisoformat(row["last_seen"])).total_seconds()<30
    return {"configured":configured,"online":online,"last_seen":row["last_seen"]}

@app.post("/native/agent/claim")
async def agent_claim(request: Request):
    check_bridge(request)
    with _db_lock:
        conn=get_db()
        row=conn.execute("SELECT * FROM native_tests WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if not row: conn.close(); raise HTTPException(204,"no jobs")
        conn.execute("UPDATE native_tests SET status='running',updated_at=? WHERE id=?",(now(),row["id"]))
        conn.commit(); conn.close()
    return {"id":row["id"],"params":json.loads(row["params"])}

@app.get("/native/agent/file/{file_id}")
async def agent_file(file_id: str, request: Request):
    import base64
    check_bridge(request)
    with _db_lock:
        conn=get_db()
        row=conn.execute("SELECT * FROM files WHERE id=?",(file_id,)).fetchone()
        conn.close()
    if not row: raise HTTPException(404,"not found")
    return Response(base64.b64decode(row["data_b64"]),media_type="application/octet-stream")

@app.post("/native/agent/result/{job_id}")
async def agent_result(job_id: str, request: Request):
    check_bridge(request); body=await request.json()
    status=body.get("status","complete"); result=body.get("result"); error=body.get("error")
    with _db_lock:
        conn=get_db()
        conn.execute("UPDATE native_tests SET status=?,result=?,error=?,updated_at=? WHERE id=?",(status,json.dumps(result) if result else None,error,now(),job_id))
        conn.execute("UPDATE tests SET status=?,result=?,error=?,updated_at=? WHERE id=?",(status,json.dumps(result) if result else None,error,now(),job_id))
        conn.commit(); conn.close()
    return {"ok":True}

@app.post("/native/agent/heartbeat")
async def heartbeat(request: Request):
    check_bridge(request)
    with _db_lock:
        conn=get_db(); conn.execute("INSERT OR REPLACE INTO heartbeats VALUES (?,?)",("csharp",now())); conn.commit(); conn.close()
    return {"ok":True}

# ── Simulator bridge (C# side) ────────────────────────────────────────────────
@app.post("/simulator/tests")
async def create_sim(request: Request):
    body=await request.json(); tid=str(uuid.uuid4())[:8]
    with _db_lock:
        conn=get_db()
        conn.execute("INSERT INTO tests VALUES (?,?,?,?,?,?,?,?,?)",(tid,"bridge",json.dumps(body),"queued",None,None,now(),now(),"csharp"))
        conn.commit(); conn.close()
    return {"id":tid}

@app.get("/simulator/tests")
async def list_sim():
    with _db_lock:
        conn=get_db()
        rows=conn.execute("SELECT * FROM tests WHERE runner='csharp' ORDER BY created_at DESC LIMIT 20").fetchall()
        conn.close()
    return [{"id":r["id"],"status":r["status"],"params":json.loads(r["params"]),"result":json.loads(r["result"]) if r["result"] else None} for r in rows]

@app.get("/simulator/tests/{job_id}")
async def get_sim(job_id: str):
    with _db_lock:
        conn=get_db(); row=conn.execute("SELECT * FROM tests WHERE id=?",(job_id,)).fetchone(); conn.close()
    if not row: raise HTTPException(404,"not found")
    return {"id":row["id"],"status":row["status"],"params":json.loads(row["params"]),"result":json.loads(row["result"]) if row["result"] else None}

@app.post("/simulator/agent/claim")
async def sim_claim(request: Request):
    check_bridge(request)
    with _db_lock:
        conn=get_db()
        row=conn.execute("SELECT * FROM tests WHERE status='queued' AND runner='csharp' ORDER BY created_at LIMIT 1").fetchone()
        if not row: conn.close(); raise HTTPException(204,"no jobs")
        conn.execute("UPDATE tests SET status='running',updated_at=? WHERE id=?",(now(),row["id"]))
        conn.commit(); conn.close()
    return {"id":row["id"],"params":json.loads(row["params"])}

# ── Journal ───────────────────────────────────────────────────────────────────
@app.get("/journal/trades")
async def j_trades(request: Request):
    uid=get_user(request)
    with _db_lock:
        conn=get_db()
        rows=conn.execute("SELECT * FROM journal_trades WHERE user_id=? ORDER BY close_time DESC LIMIT 200",(uid,)).fetchall()
        conn.close()
    return [dict(r) for r in rows]

@app.get("/journal/calendar")
async def j_calendar(request: Request):
    uid=get_user(request)
    with _db_lock:
        conn=get_db()
        rows=conn.execute("SELECT date(close_time) as date,SUM(profit+commission+swap) as pnl,COUNT(*) as trades FROM journal_trades WHERE user_id=? GROUP BY date(close_time)",(uid,)).fetchall()
        conn.close()
    return [{"date":r["date"],"pnl":round(r["pnl"] or 0,2),"trades":r["trades"]} for r in rows]

@app.get("/journal/stats")
async def j_stats(request: Request):
    uid=get_user(request)
    with _db_lock:
        conn=get_db()
        rows=conn.execute("SELECT * FROM journal_trades WHERE user_id=?",(uid,)).fetchall()
        conn.close()
    if not rows: return {"net_pnl":0,"win_pct":0,"profit_factor":0,"trades":0,"avg_win":0,"avg_loss":0}
    pnls=[r["profit"]+r["commission"]+r["swap"] for r in rows]
    wins=[p for p in pnls if p>0]; losses=[p for p in pnls if p<=0]
    gp=sum(wins); gl=-sum(losses)
    return {"net_pnl":round(sum(pnls),2),"win_pct":round(len(wins)/len(pnls)*100,1),
        "profit_factor":round(gp/gl,2) if gl>0 else 0,"trades":len(pnls),
        "avg_win":round(sum(wins)/len(wins),2) if wins else 0,"avg_loss":round(abs(sum(losses)/len(losses)),2) if losses else 0}

@app.post("/journal/import/test/{test_id}")
async def j_import_test(test_id: str, request: Request):
    uid=get_user(request)
    with _db_lock:
        conn=get_db()
        row=conn.execute("SELECT * FROM tests WHERE id=? AND user_id=?",(test_id,uid)).fetchone()
        if not row or not row["result"]: conn.close(); raise HTTPException(404,"test not found")
        result=json.loads(row["result"]); params=json.loads(row["params"])
        trades=result.get("trades_list",[]); imported=0
        for t in trades:
            tid2=str(uuid.uuid4())[:8]
            try:
                conn.execute("INSERT INTO journal_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (tid2,uid,f"test:{test_id}",params.get("symbol","?"),t.get("side","buy"),
                     t.get("lots"),t.get("entry"),t.get("exit"),t.get("entry_ts"),t.get("exit_ts"),
                     t.get("pnl",0),0,0,None,now()))
                imported+=1
            except: pass
        conn.commit(); conn.close()
    return {"imported":imported}

@app.post("/journal/import/mt5")
async def j_import_mt5(request: Request):
    return {"imported":0}

@app.post("/journal/import/csv")
async def j_import_csv(request: Request):
    return {"imported":0}

# ── Analysis stubs ────────────────────────────────────────────────────────────
@app.post("/analysis/{path:path}")
async def analysis_stub(path: str, request: Request):
    raise HTTPException(501,"analysis not available in standalone mode")

if __name__ == "__main__":
    import uvicorn
    port=int(os.environ.get("TICKFORGE_PORT","8000"))
    uvicorn.run(app,host="0.0.0.0",port=port)
