"""
TickForge — MT5 Bridge
Polls the backend for native test jobs, runs them through MT5 Strategy Tester,
and posts results back.

Setup:
  1. Install MetaTrader 5 on this machine
  2. Open MT5, log in to any demo account, then close it
  3. In MT5: Tools → Options → Expert Advisors → add http://localhost:8000 to allowed URLs
  4. Set env vars and run: python mt5_bridge.py

Env vars:
  TICKFORGE_URL          default http://localhost:8000
  TICKFORGE_BRIDGE_TOKEN required
  MT5_EXE                default C:\Program Files\MetaTrader 5\terminal64.exe
"""

import os, time, json, glob, subprocess, shutil, requests
import xml.etree.ElementTree as ET
from pathlib import Path

BACKEND     = os.environ.get("TICKFORGE_URL", "http://localhost:8000")
TOKEN       = os.environ.get("TICKFORGE_BRIDGE_TOKEN", "")
MT5_EXE     = os.environ.get("MT5_EXE", r"C:\Program Files\MetaTrader 5\terminal64.exe")
DATA_DIR    = Path(r"C:\tickforge-data")
REPORT_PATH = DATA_DIR / "mt5_report"

HEADERS = {"X-Bridge-Token": TOKEN}

TF_PERIODS = {
    "M1": "1",   "M5": "5",   "M15": "15",  "M30": "30",
    "H1": "60",  "H4": "240", "D1": "1440", "W1": "10080",
}

def find_experts_dir():
    """Find MT5 MQL5/Experts folder."""
    patterns = [
        r"C:\Users\*\AppData\Roaming\MetaQuotes\Terminal\*\MQL5\Experts",
        r"C:\Program Files\MetaTrader 5\MQL5\Experts",
        r"C:\Program Files (x86)\MetaTrader 5\MQL5\Experts",
    ]
    for pat in patterns:
        hits = glob.glob(pat)
        if hits:
            return Path(hits[0])
    return None

def download_ea(file_id: str, name: str, experts_dir: Path) -> Path:
    r = requests.get(f"{BACKEND}/native/agent/file/{file_id}", headers=HEADERS, timeout=30)
    r.raise_for_status()
    dest = experts_dir / name
    dest.write_bytes(r.content)
    print(f"[mt5] EA saved → {dest}")
    return dest

def write_ini(ea_name: str, symbol: str, period: str, dt_from: str, dt_to: str,
              deposit: float, set_path: str = "") -> Path:
    ini = DATA_DIR / "tester.ini"
    lines = [
        "[Tester]",
        f"Expert=Experts\\{ea_name}",
        f"Symbol={symbol}",
        f"Period={period}",
        "Optimization=0",
        f"FromDate={dt_from}",
        f"ToDate={dt_to}",
        "ForwardDate=",
        "ForwardMode=0",
        f"Deposit={deposit}",
        "Currency=USD",
        "ProfitInPips=0",
        "Model=1",
        "ExecutionMode=0",
        f"Report={REPORT_PATH}",
        "UseDate=1",
        "ShutdownTerminal=1",
    ]
    if set_path:
        lines.append(f"Inputs={set_path}")
    ini.write_text("\n".join(lines))
    return ini

def run_mt5(ini_path: Path, timeout: int = 600):
    if not Path(MT5_EXE).exists():
        raise FileNotFoundError(f"MT5 not found at {MT5_EXE} — check MT5_EXE env var")

    # Remove stale report
    for ext in (".xml", ".htm", ".html"):
        p = REPORT_PATH.with_suffix(ext)
        if p.exists():
            p.unlink()

    print(f"[mt5] launching tester…")
    proc = subprocess.Popen([MT5_EXE, f"/config:{ini_path}"])
    start = time.time()
    report = None
    while time.time() - start < timeout:
        time.sleep(3)
        for ext in (".xml", ".htm", ".html"):
            p = REPORT_PATH.with_suffix(ext)
            if p.exists():
                report = p
                break
        if report:
            break
        if proc.poll() is not None:
            break

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

    return report

def parse_report(report_path: Path, deposit: float) -> dict:
    result = {
        "starting_balance": deposit, "ending_balance": deposit,
        "net_profit": 0.0, "return_pct": 0.0,
        "total_trades": 0, "wins": 0, "losses": 0,
        "win_pct": 0.0, "profit_factor": 0.0,
        "max_drawdown_pct": 0.0, "sharpe": None,
        "trades_list": [], "equity": [],
    }

    if report_path.suffix == ".xml":
        _parse_xml(report_path, result)
    else:
        _parse_html(report_path, result)

    result["ending_balance"] = round(deposit + result["net_profit"], 2)
    if deposit:
        result["return_pct"] = round(result["net_profit"] / deposit * 100, 2)
    if result["total_trades"]:
        result["win_pct"] = round(result["wins"] / result["total_trades"] * 100, 1)
    return result

def _parse_xml(path: Path, out: dict):
    try:
        tree = ET.parse(str(path))
        root = tree.getroot()
        deals = []
        for row in root.iter("Row"):
            data = {c.get("Name", ""): c.get("Value", "") for c in row}
            deals.append(data)

        for row in root.iter("Cell"):
            name = row.get("Name", "").lower()
            val  = row.get("Value", "0").replace(",", "").replace("%", "").strip()
            try:
                fval = float(val)
            except ValueError:
                continue
            if "total net profit" in name:    out["net_profit"]       = fval
            elif "profit factor" in name:     out["profit_factor"]    = round(fval, 2)
            elif "max drawdown" in name and "%" in row.get("Value",""):
                out["max_drawdown_pct"] = round(fval, 2)
            elif "total trades" in name:      out["total_trades"]     = int(fval)
            elif "short trades (won" in name or "long trades (won" in name:
                pass  # handled separately below
    except Exception as e:
        print(f"[mt5] XML parse error: {e}")

def _parse_html(path: Path, out: dict):
    """Parse MT5 HTML report — extract key metrics from table rows."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        import re
        def grab(pattern):
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                try:
                    return float(m.group(1).replace(" ", "").replace(",", ""))
                except:
                    return None
            return None
        out["net_profit"]       = grab(r"Total Net Profit[^<]*?<[^>]+>([\-\d\., ]+)") or 0
        out["profit_factor"]    = grab(r"Profit Factor[^<]*?<[^>]+>([\d\., ]+)") or 0
        out["max_drawdown_pct"] = grab(r"Maximal Drawdown[^<]*?<[^>]+>[^<]*([\d\.]+)%") or 0
        out["total_trades"]     = int(grab(r"Total Trades[^<]*?<[^>]+>([\d]+)") or 0)
        wins_m = re.search(r"Short Trades[^<]*?\(won\s*([\d]+)%\)", text, re.I)
        if wins_m:
            out["win_pct"] = float(wins_m.group(1))
            out["wins"] = round(out["total_trades"] * out["win_pct"] / 100)
            out["losses"] = out["total_trades"] - out["wins"]
    except Exception as e:
        print(f"[mt5] HTML parse error: {e}")

def process_job(job: dict):
    p = job.get("params", {})
    ea_file_id  = p.get("ea_file_id")
    set_file_id = p.get("set_file_id")
    symbol      = p.get("symbol",   "XAUUSD")
    timeframe   = p.get("timeframe","H1")
    dt_from     = p.get("dt_from",  "2024.01.01").replace("-", ".")
    dt_to       = p.get("dt_to",    "2024.12.31").replace("-", ".")
    deposit     = float(p.get("deposit", 10000))
    period      = TF_PERIODS.get(timeframe, "60")

    experts_dir = find_experts_dir()
    if not experts_dir:
        raise RuntimeError("Cannot find MT5 Experts folder — is MT5 installed?")

    # Download EA
    ea_name = p.get("ea_name", f"tf_{ea_file_id}.ex5")
    if not ea_name.endswith(".ex5"):
        ea_name += ".ex5"
    download_ea(ea_file_id, ea_name, experts_dir)

    # Download SET file if provided
    set_path = ""
    if set_file_id:
        set_name = p.get("set_name", f"tf_{set_file_id}.set")
        set_dest = experts_dir / set_name
        r = requests.get(f"{BACKEND}/native/agent/file/{set_file_id}", headers=HEADERS, timeout=30)
        r.raise_for_status()
        set_dest.write_bytes(r.content)
        set_path = str(set_dest)

    ini = write_ini(ea_name, symbol, period, dt_from, dt_to, deposit, set_path)
    report = run_mt5(ini)

    if not report:
        raise RuntimeError("MT5 Strategy Tester finished but no report was generated — "
                           "check that the EA compiles and the date range has tick data.")

    result = parse_report(report, deposit)
    result["ea_name"] = ea_name
    print(f"[mt5] result: net={result['net_profit']} trades={result['total_trades']} dd={result['max_drawdown_pct']}%")
    return result

def main():
    print(f"[mt5-bridge] backend={BACKEND}")
    if not TOKEN:
        print("[mt5-bridge] WARNING: TICKFORGE_BRIDGE_TOKEN not set")

    while True:
        try:
            requests.post(f"{BACKEND}/native/agent/heartbeat", headers=HEADERS, timeout=5)
            resp = requests.post(f"{BACKEND}/native/agent/claim", headers=HEADERS, timeout=10)

            if resp.status_code == 204:
                time.sleep(5)
                continue

            job = resp.json()
            job_id = job.get("id")
            print(f"[mt5-bridge] claimed job {job_id}")

            try:
                result = process_job(job)
                requests.post(f"{BACKEND}/native/agent/result/{job_id}",
                              json={"status": "complete", "result": result},
                              headers=HEADERS, timeout=15)
                print(f"[mt5-bridge] job {job_id} → complete")
            except Exception as e:
                print(f"[mt5-bridge] job {job_id} → failed: {e}")
                requests.post(f"{BACKEND}/native/agent/result/{job_id}",
                              json={"status": "failed", "error": str(e)},
                              headers=HEADERS, timeout=15)
        except Exception as e:
            print(f"[mt5-bridge] poll error: {e}")

        time.sleep(5)

if __name__ == "__main__":
    main()
