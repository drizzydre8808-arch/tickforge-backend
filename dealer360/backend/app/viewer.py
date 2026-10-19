"""Customer-facing 360 viewer page: drag-to-spin walkaround + true 360 panoramas."""
from __future__ import annotations

VIEWER_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>360 view</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/pannellum/2.5.6/pannellum.css">
<style>
 :root{--ink:#1c2430;--mute:#667085;--line:#e4e7ec}
 *{box-sizing:border-box}body{margin:0;font:15px/1.4 -apple-system,Segoe UI,Roboto,sans-serif;color:var(--ink);background:#0f1318}
 header{padding:12px 16px;color:#fff;display:flex;justify-content:space-between;align-items:center}
 header b{font-size:17px}header span{color:#9aa4b2;font-size:13px}
 #stage{position:relative;background:#000;touch-action:pan-y;user-select:none;-webkit-user-select:none}
 #stage canvas{width:100%;display:block}
 #hint{position:absolute;left:0;right:0;bottom:10px;text-align:center;color:#fff;font-size:12px;text-shadow:0 1px 3px #000;pointer-events:none}
 .bar{display:flex;gap:8px;padding:10px 16px;align-items:center;color:#fff}
 .bar button{background:#1d2733;border:1px solid #2c3a4a;color:#fff;border-radius:8px;padding:8px 12px;font-size:14px}
 .bar .lbl{flex:1;text-align:center;color:#9aa4b2;text-transform:capitalize}
 #info{background:#fff;margin:8px 16px;border-radius:12px;padding:12px;display:none}
 #info img{width:100%;border-radius:8px;margin-bottom:8px}
 #pano{height:380px;margin:12px 16px;border-radius:12px;overflow:hidden;display:none;background:#000}
 .chips{display:flex;gap:8px;flex-wrap:wrap;padding:0 16px 24px}
 .chips button{background:#fff;border:1px solid var(--line);border-radius:99px;padding:6px 12px;font-size:13px}
 h3{color:#fff;margin:16px 16px 8px;font-size:15px}
 .empty{color:#9aa4b2;padding:30px 16px;text-align:center}
</style></head><body>
<header><b id="title">360 view</b><span id="count"></span></header>
<div id="stage"><canvas id="cv"></canvas><div id="hint">Drag to rotate · tap a red box for details</div></div>
<div class="bar"><button id="prev">‹</button><div class="lbl" id="lbl"></div><button id="next">›</button><button id="play">Auto</button></div>
<div id="info"></div>
<div id="panos" style="display:none"><h3>360° panoramas</h3><div class="chips" id="panoChips"></div><div id="pano"></div></div>
<div id="empty" class="empty" style="display:none">No photos yet.</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/pannellum/2.5.6/pannellum.js"></script>
<script>
const VID = __VID__, KEY = __KEY__;
const q = KEY ? ('?key=' + encodeURIComponent(KEY)) : '';
const cv = document.getElementById('cv'), ctx = cv.getContext('2d');
let frames = [], idx = 0, imgs = [], defects = [], timer = null, boxes = [];

fetch('/vehicles/' + VID + '/viewer-data' + q).then(r => r.json()).then(async data => {
  document.getElementById('title').textContent = data.title;
  frames = data.frames; defects = data.defects;
  document.getElementById('count').textContent = defects.length ? defects.length + ' flagged' : '';
  if (!frames.length && !data.panoramas.length) { document.getElementById('empty').style.display = 'block'; }
  imgs = await Promise.all(frames.map(f => new Promise(res => { const i = new Image(); i.onload = () => res(i); i.onerror = () => res(null); i.src = f.url; })));
  if (frames.length) draw();
  if (data.panoramas.length) {
    document.getElementById('panos').style.display = 'block';
    const chips = document.getElementById('panoChips');
    data.panoramas.forEach((p, k) => { const b = document.createElement('button'); b.textContent = p.label; b.onclick = () => openPano(p.url); chips.appendChild(b); if (k === 0 && !frames.length) openPano(p.url); });
  }
});

function openPano(url) {
  const el = document.getElementById('pano'); el.style.display = 'block';
  pannellum.viewer('pano', {type: 'equirectangular', panorama: url, autoLoad: true, showControls: true});
}

function draw() {
  const im = imgs[idx]; if (!im) return;
  cv.width = im.naturalWidth; cv.height = im.naturalHeight;
  ctx.drawImage(im, 0, 0);
  boxes = [];
  const f = frames[idx];
  const lw = Math.max(3, cv.width / 380);
  defects.filter(d => d.shot_id === f.shot_id).forEach(d => {
    const [x0, y0, x1, y1] = d.box, x = x0 * cv.width, y = y0 * cv.height, w = (x1 - x0) * cv.width, h = (y1 - y0) * cv.height;
    ctx.strokeStyle = '#ff3b30'; ctx.lineWidth = lw; ctx.strokeRect(x, y, w, h);
    boxes.push({x, y, w, h, d});
  });
  document.getElementById('lbl').textContent = f.view.replace(/_/g, ' ') + '  (' + (idx + 1) + '/' + frames.length + ')';
}

function step(n) { if (!frames.length) return; idx = (idx + n + frames.length) % frames.length; draw(); hideInfo(); }
document.getElementById('prev').onclick = () => step(-1);
document.getElementById('next').onclick = () => step(1);
document.getElementById('play').onclick = e => {
  if (timer) { clearInterval(timer); timer = null; e.target.textContent = 'Auto'; }
  else { timer = setInterval(() => step(1), 900); e.target.textContent = 'Stop'; }
};

let down = false, sx = 0, acc = 0, moved = false;
const stage = document.getElementById('stage');
stage.addEventListener('pointerdown', e => { down = true; sx = e.clientX; acc = 0; moved = false; stage.setPointerCapture(e.pointerId); });
stage.addEventListener('pointermove', e => {
  if (!down || !frames.length) return;
  const per = stage.clientWidth / Math.max(frames.length, 4), dx = e.clientX - sx;
  if (Math.abs(dx) > 6) moved = true;
  const n = Math.trunc((dx - acc) / per);
  if (n) { acc += n * per; step(-n); }
});
stage.addEventListener('pointerup', e => {
  down = false;
  if (moved) return;
  const r = cv.getBoundingClientRect(), px = (e.clientX - r.left) * cv.width / r.width, py = (e.clientY - r.top) * cv.height / r.height;
  const hit = boxes.find(b => px >= b.x - 10 && px <= b.x + b.w + 10 && py >= b.y - 10 && py <= b.y + b.h + 10);
  if (hit) showInfo(hit.d); else hideInfo();
});

function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c])); }
function showInfo(d) {
  const el = document.getElementById('info');
  el.innerHTML = (d.crop_url ? '<img src="' + esc(d.crop_url) + '">' : '') +
    '<b>' + esc(d.label.replace(/_/g, ' ')) + '</b> · ' + esc(d.severity) + '<br>' + esc(d.description);
  el.style.display = 'block';
}
function hideInfo() { document.getElementById('info').style.display = 'none'; }
</script></body></html>"""


def render_viewer(vehicle_id: int, key: str | None) -> str:
    import json
    return VIEWER_HTML.replace("__VID__", str(int(vehicle_id))).replace("__KEY__", json.dumps(key))
