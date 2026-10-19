// Port of backend/app/zones.py: maps a normalised box in a walkaround view to a car panel.
export const DEFAULT_FRAME_BOX = [0.04, 0.22, 0.96, 0.88];
export const DEFAULT_LENGTH_MM = 4400;
export const DEFAULT_WIDTH_MM = 1800;

type Row = [number, number, number, number, string, string];
const PANELS: Record<string, [string, boolean]> = {
  bonnet: ["Bonnet", false],
  grille: ["Grille", false],
  windscreen: ["Windscreen", false],
  roof: ["Roof", false],
  rear_screen: ["Rear screen", false],
  tailgate: ["Tailgate / boot lid", false],
  front_bumper: ["Front bumper", true],
  rear_bumper: ["Rear bumper", true],
  headlight: ["Headlight", true],
  taillight: ["Tail light", true],
  a_pillar: ["A-pillar", true],
  front_wing: ["Front wing", true],
  front_door: ["Front door", true],
  rear_door: ["Rear door", true],
  front_door_window: ["Front door window", true],
  rear_door_window: ["Rear door window", true],
  rear_quarter: ["Rear quarter panel", true],
  sill: ["Sill", true],
  front_wheel: ["Front wheel & tyre", true],
  rear_wheel: ["Rear wheel & tyre", true],
};
const SIDE: Row[] = [
  [0.09, 0.27, 0.62, 1.00, "front_wheel", "face"],
  [0.73, 0.91, 0.62, 1.00, "rear_wheel", "face"],
  [0.00, 0.26, 0.00, 0.38, "bonnet", "centre"],
  [0.26, 0.38, 0.00, 0.38, "a_pillar", "face"],
  [0.38, 0.60, 0.00, 0.38, "front_door_window", "face"],
  [0.60, 0.78, 0.00, 0.38, "rear_door_window", "face"],
  [0.78, 0.94, 0.00, 0.38, "rear_quarter", "face"],
  [0.94, 1.00, 0.00, 0.38, "tailgate", "centre"],
  [0.00, 0.07, 0.38, 0.80, "front_bumper", "face"],
  [0.07, 0.28, 0.38, 0.80, "front_wing", "face"],
  [0.28, 0.52, 0.38, 0.80, "front_door", "face"],
  [0.52, 0.74, 0.38, 0.80, "rear_door", "face"],
  [0.74, 0.93, 0.38, 0.80, "rear_quarter", "face"],
  [0.93, 1.00, 0.38, 0.80, "rear_bumper", "face"],
  [0.00, 0.09, 0.80, 1.00, "front_bumper", "face"],
  [0.27, 0.73, 0.80, 1.00, "sill", "face"],
  [0.91, 1.00, 0.80, 1.00, "rear_bumper", "face"],
];
const FRONT: Row[] = [
  [0.00, 0.12, 0.00, 0.35, "a_pillar", "offside"],
  [0.88, 1.00, 0.00, 0.35, "a_pillar", "nearside"],
  [0.12, 0.88, 0.00, 0.35, "windscreen", "centre"],
  [0.00, 0.16, 0.35, 0.62, "front_wing", "offside"],
  [0.84, 1.00, 0.35, 0.62, "front_wing", "nearside"],
  [0.16, 0.36, 0.35, 0.62, "headlight", "offside"],
  [0.64, 0.84, 0.35, 0.62, "headlight", "nearside"],
  [0.36, 0.64, 0.47, 0.62, "grille", "centre"],
  [0.16, 0.84, 0.35, 0.47, "bonnet", "centre"],
  [0.00, 0.20, 0.62, 1.00, "front_bumper", "offside"],
  [0.80, 1.00, 0.62, 1.00, "front_bumper", "nearside"],
  [0.20, 0.80, 0.62, 1.00, "front_bumper", "centre"],
];
const REAR: Row[] = [
  [0.00, 0.12, 0.00, 0.35, "rear_quarter", "offside"],
  [0.88, 1.00, 0.00, 0.35, "rear_quarter", "nearside"],
  [0.12, 0.88, 0.00, 0.35, "rear_screen", "centre"],
  [0.00, 0.16, 0.35, 0.62, "rear_quarter", "offside"],
  [0.84, 1.00, 0.35, 0.62, "rear_quarter", "nearside"],
  [0.16, 0.30, 0.35, 0.62, "taillight", "offside"],
  [0.70, 0.84, 0.35, 0.62, "taillight", "nearside"],
  [0.30, 0.70, 0.35, 0.62, "tailgate", "centre"],
  [0.00, 0.20, 0.62, 1.00, "rear_bumper", "offside"],
  [0.80, 1.00, 0.62, 1.00, "rear_bumper", "nearside"],
  [0.20, 0.80, 0.62, 1.00, "rear_bumper", "centre"],
];
const TOP: Row[] = [
  [0.0, 1.0, 0.00, 0.28, "bonnet", "centre"],
  [0.0, 1.0, 0.28, 0.40, "windscreen", "centre"],
  [0.0, 1.0, 0.40, 0.72, "roof", "centre"],
  [0.0, 1.0, 0.72, 0.82, "rear_screen", "centre"],
  [0.0, 1.0, 0.82, 1.00, "tailgate", "centre"],
];
const FACE_TABLES: Record<string, Row[]> = { nearside: SIDE, offside: SIDE, front: FRONT, rear: REAR, top: TOP };

interface Segment { face: string; x0: number; x1: number; reverse: boolean }
const S = (face: string, x0: number, x1: number, reverse = false): Segment => ({ face, x0, x1, reverse });
const VIEWS: Record<string, Segment[]> = {
  front: [S('front', 0, 1)],
  rear: [S('rear', 0, 1, true)],
  nearside: [S('nearside', 0, 1)],
  offside: [S('offside', 0, 1, true)],
  front_nearside: [S('front', 0, 0.4), S('nearside', 0.4, 1)],
  rear_nearside: [S('nearside', 0, 0.6), S('rear', 0.6, 1, true)],
  front_offside: [S('offside', 0, 0.6, true), S('front', 0.6, 1)],
  rear_offside: [S('rear', 0, 0.4, true), S('offside', 0.4, 1, true)],
  roof: [S('top', 0, 1)],
};

export const ANCHORS: Record<string, [number, number]> = {
  "bonnet|centre": [100, 85],
  "grille|centre": [100, 30],
  "windscreen|centre": [100, 140],
  "roof|centre": [100, 215],
  "rear_screen|centre": [100, 300],
  "tailgate|centre": [100, 355],
  "front_bumper|centre": [100, 22],
  "front_bumper|nearside": [55, 26],
  "front_bumper|offside": [145, 26],
  "rear_bumper|centre": [100, 418],
  "rear_bumper|nearside": [55, 414],
  "rear_bumper|offside": [145, 414],
  "headlight|nearside": [62, 46],
  "headlight|offside": [138, 46],
  "taillight|nearside": [62, 398],
  "taillight|offside": [138, 398],
  "a_pillar|nearside": [48, 140],
  "a_pillar|offside": [152, 140],
  "front_wing|nearside": [40, 95],
  "front_wing|offside": [160, 95],
  "front_door|nearside": [34, 175],
  "front_door|offside": [166, 175],
  "rear_door|nearside": [34, 250],
  "rear_door|offside": [166, 250],
  "front_door_window|nearside": [52, 180],
  "front_door_window|offside": [148, 180],
  "rear_door_window|nearside": [52, 250],
  "rear_door_window|offside": [148, 250],
  "rear_quarter|nearside": [40, 330],
  "rear_quarter|offside": [160, 330],
  "rear_quarter|centre": [100, 330],
  "sill|nearside": [24, 215],
  "sill|offside": [176, 215],
  "front_wheel|nearside": [16, 92],
  "front_wheel|offside": [184, 92],
  "rear_wheel|nearside": [16, 345],
  "rear_wheel|offside": [184, 345],
};
export const anchorFor = (panelId: string, side: string): [number, number] =>
  ANCHORS[`${panelId}|${side}`] ?? ANCHORS[`${panelId}|centre`] ?? [100, 220];

export interface ZoneResult {
  panel_id: string; side: string; panel: string; band: string; description: string;
  also_touches: string[]; car_position: Record<string, number>; face: string;
}

const clip = (x: number, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, x));
function label(pid: string, side: string): string {
  const [l, sided] = PANELS[pid];
  return sided && (side === 'nearside' || side === 'offside') ? `${side[0].toUpperCase()}${side.slice(1)} ${l[0].toLowerCase()}${l.slice(1)}` : l;
}
function locate(view: string, x: number, y: number) {
  const segs = VIEWS[view];
  if (!segs) throw new Error(`unknown view ${view}`);
  let seg = segs[segs.length - 1];
  for (const s of segs) if (s.x0 <= x && x <= s.x1) { seg = s; break; }
  let u = clip((x - seg.x0) / (seg.x1 - seg.x0));
  if (seg.reverse) u = 1 - u;
  const v = clip(y);
  let best: Row | null = null, bd = 1e9;
  for (const r of FACE_TABLES[seg.face]) {
    if (r[0] <= u && u <= r[1] && r[2] <= v && v <= r[3]) { best = r; break; }
    const du = Math.max(r[0] - u, 0, u - r[1]), dv = Math.max(r[2] - v, 0, v - r[3]);
    if (du * du + dv * dv < bd) { bd = du * du + dv * dv; best = r; }
  }
  return { face: seg.face, u, v, rect: best! };
}
const res = (face: string, r: Row): [string, string] => [r[4], r[5] === 'face' ? face : r[5]];
const third = (x: number, n: [string, string, string]) => (x < 1 / 3 ? n[0] : x < 2 / 3 ? n[1] : n[2]);

export function resolveZone(view: string, box: number[], fb = DEFAULT_FRAME_BOX): ZoneResult | null {
  const [fx0, fy0, fx1, fy1] = fb;
  const fw = fx1 - fx0, fh = fy1 - fy0;
  const [x0, y0, x1, y1] = box;
  const cx = ((x0 + x1) / 2 - fx0) / fw, cy = ((y0 + y1) / 2 - fy0) / fh;
  if (cx < -0.02 || cx > 1.02 || cy < -0.02 || cy > 1.02) return null;
  const { face, u, v, rect } = locate(view, clip(cx), clip(cy));
  const [pid, side] = res(face, rect);
  const lbl = label(pid, side);
  const along = rect[1] > rect[0] ? clip((u - rect[0]) / (rect[1] - rect[0])) : 0.5;
  const vertical = rect[3] > rect[2] ? clip((v - rect[2]) / (rect[3] - rect[2])) : 0.5;
  const seen = new Map<string, number>();
  const n = 7;
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
    const px = (x0 + ((x1 - x0) * (i + 0.5)) / n - fx0) / fw, py = (y0 + ((y1 - y0) * (j + 0.5)) / n - fy0) / fh;
    const l2 = locate(view, clip(px), clip(py));
    const k = res(l2.face, l2.rect).join('|');
    seen.set(k, (seen.get(k) ?? 0) + 1);
  }
  const also = [...seen.entries()].sort((a, b) => b[1] - a[1])
    .filter(([k, c]) => k !== `${pid}|${side}` && c / (n * n) >= 0.15)
    .map(([k]) => { const [p, s] = k.split('|'); return label(p, s); });
  let car: Record<string, number> = {};
  if (face === 'nearside' || face === 'offside') car = { along_length_pct: Math.round(u * 100), height_pct: Math.round((1 - v) * 100) };
  else if (face === 'front' || face === 'rear') car = { across_width_pct_from_offside: Math.round(u * 100), height_pct: Math.round((1 - v) * 100) };
  else car = { along_length_pct: Math.round(v * 100), across_width_pct_from_offside: Math.round(u * 100) };
  const topFace = face === 'top';
  const vert = topFace ? third(vertical, ['front third', 'middle', 'rear third']) : third(vertical, ['upper third', 'middle', 'lower third']);
  const ends = topFace ? ['offside edge', 'nearside edge'] : face === 'nearside' || face === 'offside' ? ['front edge', 'rear edge'] : ['offside edge', 'nearside edge'];
  const lat = along < 1 / 3 ? `towards the ${ends[0]}` : along > 2 / 3 ? `towards the ${ends[1]}` : 'in the centre';
  let description = `${lbl}, ${vert}, ${lat} of the panel`;
  if (also.length) description += '; also touches ' + also.join(', ');
  return { panel_id: pid, side, panel: lbl, band: topFace ? 'top' : v < 0.38 ? 'upper' : v < 0.8 ? 'mid' : 'lower', description, also_touches: also, car_position: car, face };
}
