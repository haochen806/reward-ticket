"""Web UI for the award ticket monitor. Left: qualifying flights. Right: config filters."""

import json
import logging
import sqlite3
import sys
from pathlib import Path

import yaml
from flask import Flask, jsonify, request, Response

log = logging.getLogger(__name__)

app = Flask(__name__)

CONFIG_PATH = "config.yaml"
DB_PATH = "./data/awards.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.route("/")
def index():
    return HTML_PAGE


@app.route("/api/awards")
def api_awards():
    """Return all qualifying award seats from the database."""
    db = get_db()
    rows = db.execute(
        """SELECT id, airline, flight_number, origin, destination, date, cabin,
                  miles, tax, fare_class, seat_type, status, first_seen_at, last_seen_at
           FROM awards
           WHERE status NOT IN ('gone', 'dismissed')
           ORDER BY miles ASC, date ASC"""
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/queue")
def api_queue():
    """Return scan queue status."""
    db = get_db()
    rows = db.execute(
        "SELECT date, route, last_checked_at, status FROM scan_queue ORDER BY date"
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/config", methods=["GET"])
def api_get_config():
    """Return current YAML config as JSON."""
    try:
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f)
        return jsonify(cfg)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/config", methods=["POST"])
def api_save_config():
    """Save new config from JSON body to YAML file."""
    try:
        new_cfg = request.get_json()
        if not new_cfg:
            return jsonify({"error": "empty body"}), 400

        with open(CONFIG_PATH, "w") as f:
            yaml.dump(new_cfg, f, default_flow_style=False, sort_keys=False)

        return jsonify({"status": "saved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/awards/<award_id>/dismiss", methods=["POST"])
def api_dismiss(award_id):
    """Dismiss an award so it won't re-alert."""
    db = get_db()
    db.execute("UPDATE awards SET status = 'dismissed' WHERE id = ?", (award_id,))
    db.commit()
    db.close()
    return jsonify({"status": "dismissed"})


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Award Ticket Monitor</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; }
  .header { background: #1e293b; padding: 16px 24px; border-bottom: 1px solid #334155; display: flex; justify-content: space-between; align-items: center; }
  .header h1 { font-size: 20px; color: #38bdf8; }
  .header .status { font-size: 13px; color: #94a3b8; }
  .container { display: flex; height: calc(100vh - 57px); }
  .left { flex: 1; overflow-y: auto; padding: 20px; border-right: 1px solid #334155; }
  .right { width: 380px; overflow-y: auto; padding: 20px; background: #1e293b; }
  h2 { font-size: 15px; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 16px; }
  .card { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 16px; margin-bottom: 12px; }
  .card.hit { border-left: 4px solid #22c55e; }
  .card .flight { font-size: 18px; font-weight: 600; color: #f8fafc; }
  .card .route { color: #94a3b8; font-size: 13px; margin-top: 2px; }
  .card .details { display: flex; gap: 20px; margin-top: 10px; font-size: 14px; }
  .card .miles { color: #22c55e; font-weight: 600; font-size: 16px; }
  .card .tax { color: #94a3b8; }
  .card .seats { color: #f59e0b; }
  .card .date { color: #38bdf8; }
  .card .status-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; text-transform: uppercase; }
  .card .status-badge.new { background: #166534; color: #86efac; }
  .card .status-badge.alerted { background: #854d0e; color: #fde68a; }
  .card .status-badge.booked { background: #1e3a5f; color: #93c5fd; }
  .card .dismiss-btn { float: right; background: #334155; border: none; color: #94a3b8; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 12px; }
  .card .dismiss-btn:hover { background: #475569; color: #e2e8f0; }
  .empty { text-align: center; color: #64748b; padding: 40px; font-size: 15px; }
  label { display: block; font-size: 13px; color: #94a3b8; margin-bottom: 4px; margin-top: 12px; }
  input, select { width: 100%; padding: 8px 12px; background: #0f172a; border: 1px solid #334155; border-radius: 6px; color: #e2e8f0; font-size: 14px; }
  input:focus, select:focus { outline: none; border-color: #38bdf8; }
  .row { display: flex; gap: 10px; }
  .row > div { flex: 1; }
  .btn { width: 100%; padding: 10px; margin-top: 16px; background: #2563eb; border: none; border-radius: 6px; color: white; font-size: 14px; font-weight: 600; cursor: pointer; }
  .btn:hover { background: #1d4ed8; }
  .btn.secondary { background: #334155; }
  .btn.secondary:hover { background: #475569; }
  .queue-bar { display: flex; gap: 2px; margin-top: 8px; margin-bottom: 16px; }
  .queue-bar .tick { flex: 1; height: 20px; border-radius: 2px; font-size: 9px; display: flex; align-items: center; justify-content: center; color: #0f172a; font-weight: 600; }
  .tick.fresh { background: #22c55e; }
  .tick.stale { background: #f59e0b; }
  .tick.pending { background: #475569; }
  .saved-msg { color: #22c55e; font-size: 13px; margin-top: 8px; display: none; }
</style>
</head>
<body>
<div class="header">
  <h1>Award Ticket Monitor</h1>
  <div class="status" id="status">Loading...</div>
</div>
<div class="container">
  <div class="left">
    <h2>Qualifying Flights</h2>
    <div id="awards"></div>
  </div>
  <div class="right">
    <h2>Filters</h2>
    <div class="row">
      <div><label>Origin</label><input id="f-origin" value="NRT"></div>
      <div><label>Destination</label><input id="f-dest" value="SEA"></div>
    </div>
    <div class="row">
      <div><label>Cabin</label>
        <select id="f-cabin"><option value="J">Business (J)</option><option value="F">First (F)</option></select>
      </div>
      <div><label>Max Miles</label><input id="f-miles" type="number" value="100000"></div>
    </div>
    <div class="row">
      <div><label>Start Date</label><input id="f-start" type="date" value="2026-05-01"></div>
      <div><label>End Date</label><input id="f-end" type="date" value="2026-05-20"></div>
    </div>
    <button class="btn" onclick="saveConfig()">Save & Apply</button>
    <div class="saved-msg" id="saved-msg">Config saved. Monitor will pick up changes on next tick.</div>

    <h2 style="margin-top:24px">Scan Queue</h2>
    <div id="queue"></div>

    <button class="btn secondary" style="margin-top:12px" onclick="loadAll()">Refresh</button>
  </div>
</div>

<script>
async function loadAwards() {
  try {
    const r = await fetch('/api/awards');
    const awards = await r.json();
    const el = document.getElementById('awards');
    if (!awards.length) {
      el.innerHTML = '<div class="empty">No qualifying flights found yet.<br>The monitor is scanning...</div>';
      return;
    }
    el.innerHTML = awards.map(a => `
      <div class="card hit">
        <button class="dismiss-btn" onclick="dismiss('${a.id}')">Dismiss</button>
        <div class="flight">${a.airline} ${a.flight_number}</div>
        <div class="route">${a.origin} &rarr; ${a.destination}</div>
        <div class="details">
          <span class="date">${a.date}</span>
          <span class="miles">${Number(a.miles).toLocaleString()} mi</span>
          <span class="tax">+$${a.tax.toFixed(2)}</span>
          <span class="seats">${a.fare_class} class</span>
          <span class="status-badge ${a.status}">${a.status}</span>
        </div>
      </div>
    `).join('');
    document.getElementById('status').textContent = `${awards.length} flights | Last refresh: ${new Date().toLocaleTimeString()}`;
  } catch(e) {
    document.getElementById('awards').innerHTML = '<div class="empty">Error loading flights</div>';
  }
}

async function loadQueue() {
  try {
    const r = await fetch('/api/queue');
    const queue = await r.json();
    const el = document.getElementById('queue');
    if (!queue.length) { el.innerHTML = '<div class="empty">No dates in queue</div>'; return; }
    const now = Date.now();
    el.innerHTML = '<div class="queue-bar">' + queue.map(q => {
      const checked = q.last_checked_at ? new Date(q.last_checked_at).getTime() : 0;
      const age = (now - checked) / 1000;
      const cls = !checked ? 'pending' : age < 300 ? 'fresh' : 'stale';
      const day = q.date.slice(5);
      return `<div class="tick ${cls}" title="${q.date}: ${cls} (${Math.round(age)}s ago)">${day.slice(3)}</div>`;
    }).join('') + '</div>';
  } catch(e) {}
}

async function loadConfig() {
  try {
    const r = await fetch('/api/config');
    const cfg = await r.json();
    if (cfg.routes && cfg.routes[0]) {
      const route = cfg.routes[0];
      document.getElementById('f-origin').value = route.origin || '';
      document.getElementById('f-dest').value = route.destination || '';
      document.getElementById('f-cabin').value = route.cabin || 'J';
      document.getElementById('f-miles').value = route.max_miles || 100000;
      document.getElementById('f-start').value = route.start_date || '';
      document.getElementById('f-end').value = route.end_date || '';
    }
  } catch(e) {}
}

async function saveConfig() {
  const cfg = {
    scan_interval: 60,
    routes: [{
      origin: document.getElementById('f-origin').value,
      destination: document.getElementById('f-dest').value,
      cabin: document.getElementById('f-cabin').value,
      start_date: document.getElementById('f-start').value,
      end_date: document.getElementById('f-end').value,
      max_miles: parseInt(document.getElementById('f-miles').value),
    }],
    telegram: { bot_token: "YOUR_BOT_TOKEN_HERE", chat_id: "YOUR_CHAT_ID_HERE" },
    database: { path: "./data/awards.db" },
  };
  // Preserve existing telegram config
  try {
    const existing = await (await fetch('/api/config')).json();
    if (existing.telegram) cfg.telegram = existing.telegram;
    if (existing.database) cfg.database = existing.database;
  } catch(e) {}

  await fetch('/api/config', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(cfg) });
  document.getElementById('saved-msg').style.display = 'block';
  setTimeout(() => document.getElementById('saved-msg').style.display = 'none', 3000);
}

async function dismiss(id) {
  await fetch(`/api/awards/${id}/dismiss`, { method: 'POST' });
  loadAwards();
}

function loadAll() { loadAwards(); loadQueue(); loadConfig(); }

loadAll();
setInterval(loadAwards, 15000);
setInterval(loadQueue, 15000);
</script>
</body>
</html>
"""


def main():
    global CONFIG_PATH, DB_PATH

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    CONFIG_PATH = config_path

    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        DB_PATH = cfg.get("database", {}).get("path", "./data/awards.db")
    except Exception:
        pass

    log.info(f"Web UI starting on http://0.0.0.0:8080")
    app.run(host="0.0.0.0", port=8080, debug=False)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
