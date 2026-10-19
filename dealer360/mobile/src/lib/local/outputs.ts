/** Condition report and drag-to-spin walkaround viewer as self-contained HTML (images embedded). */
import { manipulateAsync, SaveFormat } from 'expo-image-manipulator';

import { load } from './store';
import { anchorFor, ANCHORS } from './zones';

const WALK = ['front', 'front_nearside', 'nearside', 'rear_nearside', 'rear', 'rear_offside', 'offside', 'front_offside'];
const esc = (s: unknown) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]!));
const SEV_COL: Record<string, string> = { minor: '#d97706', moderate: '#ea580c', severe: '#dc2626' };

async function dataUri(uri: string, width: number): Promise<string> {
  const r = await manipulateAsync(uri, [{ resize: { width } }], { compress: 0.7, format: SaveFormat.JPEG, base64: true });
  return `data:image/jpeg;base64,${r.base64}`;
}

export async function buildReport(vid: number): Promise<string> {
  const db = await load();
  const v = db.vehicles.find((x) => x.id === vid);
  if (!v) throw new Error('Vehicle not found');
  const defects = db.defects.filter((d) => d.vehicle_id === vid && d.status !== 'rejected');
  const dots = defects.map((d, i) => {
    const [x, y] = anchorFor(panelId(d.panel), d.side);
    return `<circle cx="${x}" cy="${y}" r="9" fill="${SEV_COL[d.severity]}"/><text x="${x}" y="${y + 4}" font-size="11" text-anchor="middle" fill="#fff">${i + 1}</text>`;
  }).join('');
  const cards = (await Promise.all(defects.map(async (d, i) => `
    <div class="card"><img src="${d.crop_url ? await dataUri(d.crop_url, 360) : ''}"/>
    <div><b>${i + 1}. ${esc(d.label.replace('_', ' '))} — ${esc(d.panel)}</b>
    <div class="m">${esc(d.description)}</div>
    <div class="m">${d.size_mm ? `≈ ${d.size_mm.length_mm} × ${d.size_mm.width_mm} mm` : 'Size not estimated'} · confidence ${Math.round(d.score * 100)}% · ${d.status}</div>
    ${d.note ? `<div class="m">Note: ${esc(d.note)}</div>` : ''}
    <span class="sev" style="background:${SEV_COL[d.severity]}">${d.severity}</span></div></div>`))).join('');
  return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font-family:-apple-system,Roboto,sans-serif;margin:16px;color:#111}h1{margin:0}.m{color:#555;font-size:13px;margin:2px 0}
.card{display:flex;gap:12px;border:1px solid #ddd;border-radius:10px;padding:10px;margin:10px 0;break-inside:avoid}.card img{width:120px;height:120px;object-fit:cover;border-radius:8px}
.sev{color:#fff;border-radius:99px;padding:2px 10px;font-size:12px}svg{max-width:200px}</style></head><body>
<h1>Condition report</h1><div class="m">${esc([v.reg, v.make, v.model, v.year].filter(Boolean).join(' · ') || `Vehicle ${vid}`)} · ${new Date().toLocaleDateString()}</div>
<div class="m">${defects.length} defect(s) logged. Positions and sizes are approximate; AI findings should be confirmed by a person.</div>
<svg viewBox="0 0 200 440"><rect x="30" y="10" width="140" height="420" rx="50" fill="#f3f4f6" stroke="#9ca3af"/>${dots}</svg>${cards || '<p>No defects.</p>'}</body></html>`;
}

// the stored panel label ("Nearside front door") -> id used for diagram anchors
function panelId(label: string): string {
  const l = label.toLowerCase().replace(/^(nearside|offside) /, '');
  const map: [string, string][] = [['front door window', 'front_door_window'], ['rear door window', 'rear_door_window'], ['front door', 'front_door'], ['rear door', 'rear_door'],
    ['front wing', 'front_wing'], ['rear quarter', 'rear_quarter'], ['front bumper', 'front_bumper'], ['rear bumper', 'rear_bumper'], ['headlight', 'headlight'],
    ['tail light', 'taillight'], ['a-pillar', 'a_pillar'], ['sill', 'sill'], ['front wheel', 'front_wheel'], ['rear wheel', 'rear_wheel'], ['bonnet', 'bonnet'],
    ['grille', 'grille'], ['windscreen', 'windscreen'], ['roof', 'roof'], ['rear screen', 'rear_screen'], ['tailgate', 'tailgate']];
  return map.find(([k]) => l.startsWith(k))?.[1] ?? 'roof';
}
void ANCHORS;

export async function buildViewer(vid: number): Promise<string> {
  const db = await load();
  const imgs: string[] = [];
  for (const view of WALK) {
    const shot = [...db.shots].reverse().find((s) => s.vehicle_id === vid && s.view === view);
    if (shot) imgs.push(await dataUri(shot.uri, 900));
  }
  if (imgs.length === 0) return '<html><body style="font-family:sans-serif;padding:24px">No walkaround photos yet. Use Guided capture first.</body></html>';
  return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<style>html,body{margin:0;background:#000;height:100%;overflow:hidden}img{width:100%;height:100%;object-fit:contain;touch-action:none;user-select:none}
#h{position:fixed;bottom:8px;left:0;right:0;text-align:center;color:#aaa;font:13px sans-serif}</style></head><body>
<img id="i"/><div id="h">Drag left / right to spin</div>
<script>var F=${JSON.stringify(imgs)},n=F.length,k=0,x0=null,i=document.getElementById('i');i.src=F[0];
function s(j){k=((j%n)+n)%n;i.src=F[k]}
i.addEventListener('pointerdown',function(e){x0=e.clientX;i.setPointerCapture(e.pointerId)});
i.addEventListener('pointermove',function(e){if(x0===null)return;var d=e.clientX-x0;if(Math.abs(d)>40){s(k+(d<0?1:-1));x0=e.clientX}});
i.addEventListener('pointerup',function(){x0=null});</script></body></html>`;
}
