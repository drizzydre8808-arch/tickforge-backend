"""HTML condition report: summary, top-down location diagram, one card per defect."""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Callable, Optional

from jinja2 import Environment, select_autoescape

from . import zones

SEV_COLOUR = {"minor": "#d9a400", "moderate": "#ea7a00", "severe": "#d92d20"}
LABEL_NICE = {
    "dent": "Dent", "chip": "Paint chip", "scratch": "Scratch", "crack": "Crack", "rust": "Rust",
    "paint_damage": "Paint damage / chip", "broken_part": "Broken part", "tyre_damage": "Tyre damage",
    "glass_damage": "Glass damage", "misaligned_panel": "Misaligned panel", "other": "Other",
}

TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Condition report {{ title }}</title>
<style>
 :root{--ink:#1c2430;--mute:#667085;--line:#e4e7ec;--bg:#f7f8fa;--card:#fff}
 *{box-sizing:border-box} body{margin:0;font:15px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;color:var(--ink);background:var(--bg)}
 .wrap{max-width:980px;margin:0 auto;padding:20px 16px 60px}
 h1{font-size:22px;margin:0 0 2px} h2{font-size:17px;margin:28px 0 10px}
 .sub{color:var(--mute)} .grid{display:grid;gap:14px}
 .summary{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}
 .stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
 .stat b{display:block;font-size:24px}
 .two{display:grid;grid-template-columns:240px 1fr;gap:16px;align-items:start}
 @media(max-width:640px){.two{grid-template-columns:1fr}.summary{grid-template-columns:repeat(2,1fr)}}
 .card{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
 .defect{display:grid;grid-template-columns:260px 1fr;gap:0}
 @media(max-width:640px){.defect{grid-template-columns:1fr}}
 .defect img{width:100%;display:block;background:#000}
 .body{padding:14px}
 .pill{display:inline-block;padding:2px 9px;border-radius:99px;font-size:12px;font-weight:600;color:#fff}
 .st{font-size:12px;border:1px solid var(--line);border-radius:99px;padding:1px 8px;color:var(--mute);margin-left:6px}
 .st.confirmed{color:#067647;border-color:#abefc6;background:#ecfdf3}
 table{border-collapse:collapse;width:100%;margin-top:8px} td{padding:4px 0;vertical-align:top;border-top:1px solid var(--line)}
 td:first-child{color:var(--mute);width:42%}
 .num{display:inline-flex;width:24px;height:24px;border-radius:50%;color:#fff;align-items:center;justify-content:center;font-weight:700;font-size:13px;margin-right:8px}
 .note{font-size:13px;color:var(--mute);margin-top:30px}
 .thumbs{display:flex;gap:8px;flex-wrap:wrap} .thumbs figure{margin:0;width:150px} .thumbs img{width:100%;border-radius:8px;border:1px solid var(--line)}
 .thumbs figcaption{font-size:12px;color:var(--mute)}
</style></head><body><div class="wrap">
<h1>Condition report</h1>
<div class="sub">{{ title }}{% if vehicle.vin %} · VIN {{ vehicle.vin }}{% endif %} · generated {{ generated }}</div>

<div class="summary">
 <div class="stat"><b>{{ defects|length }}</b>Items logged</div>
 <div class="stat"><b style="color:{{ sev_colour.severe }}">{{ counts.severe }}</b>Severe</div>
 <div class="stat"><b style="color:{{ sev_colour.moderate }}">{{ counts.moderate }}</b>Moderate</div>
 <div class="stat"><b style="color:{{ sev_colour.minor }}">{{ counts.minor }}</b>Minor</div>
</div>

<div class="two">
 <div class="card" style="padding:10px">{{ diagram|safe }}<div class="sub" style="font-size:12px;text-align:center">Top view · front at top · nearside = left</div></div>
 <div class="card" style="padding:12px 14px">
  <b>Where to look</b>
  {% if defects %}<table>{% for d in defects %}<tr><td><span class="num" style="background:{{ sev_colour[d.severity] }}">{{ loop.index }}</span></td>
   <td><b>{{ nice[d.label] }}</b> — {{ d.panel }}<br><span class="sub">{{ d.description }}</span></td></tr>{% endfor %}</table>
  {% else %}<p class="sub">Nothing logged.</p>{% endif %}
 </div>
</div>

<h2>Defect detail</h2>
<div class="grid">
{% for d in defects %}
 <div class="card defect">
  <a href="{{ d.overview_url }}"><img src="{{ d.crop_url }}" alt="Close-up of defect {{ loop.index }}"></a>
  <div class="body">
   <div><span class="num" style="background:{{ sev_colour[d.severity] }}">{{ loop.index }}</span>
    <b>{{ nice[d.label] }}</b>
    <span class="pill" style="background:{{ sev_colour[d.severity] }}">{{ d.severity }}</span>
    <span class="st {{ d.status }}">{{ d.status }}</span></div>
   <table>
    <tr><td>Panel</td><td>{{ d.panel }}</td></tr>
    <tr><td>Location</td><td>{{ d.description }}</td></tr>
    {% if d.zone.car_position %}<tr><td>On the car</td><td>
      {% set cp = d.zone.car_position %}
      {% if cp.along_length_pct is defined %}{{ cp.along_length_pct }}% of the way from the front bumper to the rear bumper{% endif %}
      {% if cp.across_width_pct_from_offside is defined %}{% if cp.along_length_pct is defined %}; {% endif %}{{ cp.across_width_pct_from_offside }}% across from the offside{% endif %}
      {% if cp.height_pct is defined %}; about {{ cp.height_pct }}% of the way up from the ground{% endif %}</td></tr>{% endif %}
    {% if d.size_mm %}<tr><td>Approx. size</td><td>{{ d.size_mm.length_mm }} × {{ d.size_mm.width_mm }} mm (≈ {{ d.size_mm.area_mm2 }} mm²)<br><span class="sub">Smallest mark this photo can show: ~{{ d.size_mm.min_detectable_mm }} mm</span></td></tr>{% endif %}
    <tr><td>Seen from</td><td>{{ d.seen_in|join(', ')|replace('_', ' ') }}</td></tr>
    <tr><td>Confidence</td><td>{{ (d.score * 100)|round|int }}% · {{ d.detector }}</td></tr>
    {% if d.note %}<tr><td>Note</td><td>{{ d.note }}</td></tr>{% endif %}
   </table>
  </div>
 </div>
{% endfor %}
</div>

{% if photos %}<h2>Walkaround photos</h2>
<div class="thumbs">{% for p in photos %}<figure><img src="{{ p.url }}" alt="{{ p.view }}"><figcaption>{{ p.view|replace('_',' ') }}</figcaption></figure>{% endfor %}</div>{% endif %}

<p class="note">Defects are found by an automated detector and located using a generic vehicle panel map, so positions are approximate
and items marked “pending” have not been confirmed by a person. Sizes are estimates assuming the vehicle fills the guide frame.</p>
</div></body></html>"""

_env = Environment(autoescape=select_autoescape(default=True))
_tpl = _env.from_string(TEMPLATE)


def diagram_svg(defects: list[dict]) -> str:
    parts = ['<svg viewBox="0 0 200 440" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:220px;display:block;margin:0 auto">',
             '<rect x="22" y="8" width="156" height="424" rx="46" fill="#eef1f5" stroke="#98a2b3" stroke-width="2"/>',
             '<rect x="44" y="118" width="112" height="46" rx="10" fill="#d0d5dd"/>',   # windscreen
             '<rect x="44" y="165" width="112" height="120" rx="8" fill="#e4e7ec" stroke="#cbd0d8"/>',  # roof/cabin
             '<rect x="48" y="286" width="104" height="34" rx="8" fill="#d0d5dd"/>',   # rear screen
             '<rect x="4" y="70" width="14" height="48" rx="6" fill="#475467"/><rect x="182" y="70" width="14" height="48" rx="6" fill="#475467"/>',
             '<rect x="4" y="322" width="14" height="48" rx="6" fill="#475467"/><rect x="182" y="322" width="14" height="48" rx="6" fill="#475467"/>',
             ]
    used: dict[tuple[int, int], int] = {}
    for i, d in enumerate(defects, 1):
        x, y = zones.anchor_for(d["panel_id"], d["side"])
        k = used.get((x, y), 0)
        used[(x, y)] = k + 1
        x, y = x + 14 * k, y + 10 * k
        parts.append(f'<circle cx="{x}" cy="{y}" r="11" fill="{SEV_COLOUR.get(d["severity"], "#667085")}" stroke="#fff" stroke-width="2"/>'
                     f'<text x="{x}" y="{y + 4}" text-anchor="middle" font-size="12" font-weight="700" fill="#fff" font-family="sans-serif">{i}</text>')
    parts.append("</svg>")
    return "".join(parts)


def build_report(vehicle: dict, defects: list[dict], shots: list[dict], generated: str,
                 media_url: Callable[[str], str]) -> str:
    items = []
    for d in defects:
        items.append({**d, "crop_url": media_url(d["crop_path"]) if d.get("crop_path") else "",
                      "overview_url": media_url(d["overview_path"]) if d.get("overview_path") else ""})
    counts = {s: sum(1 for d in defects if d["severity"] == s) for s in ("minor", "moderate", "severe")}
    latest: dict[str, dict] = {}
    for s in shots:
        if s.get("view") and s["kind"] in ("photo", "derived"):
            latest[s["view"]] = s
    order = zones.WALKAROUND_ORDER + [v for v in latest if v not in zones.WALKAROUND_ORDER]
    photos = [{"view": v, "url": media_url(latest[v]["path"])} for v in order if v in latest]
    title = " ".join(str(x) for x in [vehicle.get("reg"), vehicle.get("make"), vehicle.get("model"), vehicle.get("year")] if x) \
        or f"Vehicle #{vehicle['id']}"
    return _tpl.render(vehicle=vehicle, title=title, defects=items, counts=counts, sev_colour=SEV_COLOUR,
                       nice=LABEL_NICE, diagram=diagram_svg(defects), photos=photos, generated=generated)


def make_embedder(media_dir: Path, max_side: int = 900) -> Callable[[str], str]:
    """media_url replacement that inlines images as data URIs so the report is a single file."""
    import cv2

    def embed(rel: str) -> str:
        img = cv2.imread(str(media_dir / rel))
        if img is None:
            return ""
        k = min(1.0, max_side / max(img.shape[:2]))
        if k < 1:
            img = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])
        return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode() if ok else ""
    return embed
