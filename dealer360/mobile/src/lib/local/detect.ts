/**
 * Damage detection on the device: the photo is cut into overlapping tiles and each tile goes to a
 * Claude vision model with the inspection spec (port of backend/app/detection/vlm.py).
 * Needs internet + an Anthropic API key. Photos leave the device.
 */
import { manipulateAsync, SaveFormat } from 'expo-image-manipulator';

import { ApiError } from '../errors';
import { INSPECTION_SPEC } from './spec';

export const VLM_MODEL = 'claude-sonnet-5-5';
const JSON_ONLY = 'Return your response strictly in valid JSON format matching the schema defined in Output Specifications.';
const LABELS: Record<string, string> = {
  dent: 'dent', chip: 'chip', scratch: 'scratch', 'paint damage': 'paint_damage', paint_damage: 'paint_damage',
  'paint imperfection': 'paint_damage', rust: 'rust', crack: 'crack',
};

export interface RawDet { label: string; score: number; box: [number, number, number, number] }

export async function complete(apiKey: string, b64: string, text: string, maxTokens = 4096): Promise<string> {
  if (!apiKey) throw new ApiError(401, 'Add your Anthropic API key in Settings');
  let res: Response;
  try {
    res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'x-api-key': apiKey, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
      body: JSON.stringify({
        model: VLM_MODEL, max_tokens: maxTokens, system: INSPECTION_SPEC,
        messages: [{ role: 'user', content: [
          { type: 'image', source: { type: 'base64', media_type: 'image/jpeg', data: b64 } },
          { type: 'text', text },
        ] }],
      }),
    });
  } catch (e: any) {
    throw new ApiError(0, `No internet (${e?.message ?? 'network error'})`);
  }
  if (res.status === 401 || res.status === 403) throw new ApiError(401, 'Anthropic API key was rejected');
  if (res.status === 429 || res.status >= 500) throw new ApiError(0, `AI service busy (${res.status}), try again`);
  if (!res.ok) throw new ApiError(res.status, `AI request failed (${res.status})`);
  const j = await res.json();
  return (j.content ?? []).filter((b: any) => b.type === 'text').map((b: any) => b.text).join('');
}

function extractJson(t: string): any {
  t = t.trim().replace(/^```(?:json)?\s*|\s*```$/g, '');
  const a = t.indexOf('{'), b = t.lastIndexOf('}');
  if (a !== -1 && b > a) { try { return JSON.parse(t.slice(a, b + 1)); } catch { /* try array */ } }
  const c = t.indexOf('['), d = t.lastIndexOf(']');
  if (c !== -1 && d > c) return JSON.parse(t.slice(c, d + 1));
  throw new Error('no JSON in reply');
}

export function parseDefects(reply: string): any[] {
  let data = extractJson(reply);
  if (!Array.isArray(data)) {
    const k = ['defects', 'Defects', 'results', 'Defect_List'].find((x) => Array.isArray(data?.[x]));
    data = k ? data[k] : data?.Classification ? [data] : [];
  }
  return data.filter((d: any) => d && typeof d === 'object');
}

function iou(a: number[], b: number[]) {
  const w = Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])), h = Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
  const i = w * h, u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i;
  return u > 0 ? i / u : 0;
}
function nms(dets: RawDet[], thr: number): RawDet[] {
  const out: RawDet[] = [];
  for (const d of [...dets].sort((a, b) => b.score - a.score)) if (!out.some((o) => o.label === d.label && iou(o.box, d.box) > thr)) out.push(d);
  return out;
}

export async function detect(
  apiKey: string, uri: string, w: number, h: number, tiles: [number, number] = [2, 2], minScore = 0.35,
): Promise<RawDet[]> {
  const [rows, cols] = tiles;
  const ov = 0.12;
  const jobs: Promise<RawDet[]>[] = [];
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    const tx0 = Math.max(0, c / cols - ov / cols), tx1 = Math.min(1, (c + 1) / cols + ov / cols);
    const ty0 = Math.max(0, r / rows - ov / rows), ty1 = Math.min(1, (r + 1) / rows + ov / rows);
    jobs.push((async () => {
      const cw = Math.round((tx1 - tx0) * w), ch = Math.round((ty1 - ty0) * h);
      const acts: any[] = [{ crop: { originX: Math.round(tx0 * w), originY: Math.round(ty0 * h), width: cw, height: ch } }];
      if (Math.max(cw, ch) > 1568) acts.push({ resize: cw >= ch ? { width: 1568 } : { height: 1568 } });
      const t = await manipulateAsync(uri, acts, { compress: 0.9, format: SaveFormat.JPEG, base64: true });
      const items = parseDefects(await complete(apiKey, t.base64!, JSON_ONLY));
      const out: RawDet[] = [];
      for (const it of items) {
        const bb = it.Bounding_Box ?? it.bounding_box ?? it.bbox;
        if (!Array.isArray(bb) || bb.length !== 4) continue;
        const v = bb.map((x: any) => Math.min(1, Math.max(0, Number(x))));
        if (v.some((x: number) => isNaN(x))) continue;
        const [x0, x1] = [Math.min(v[0], v[2]), Math.max(v[0], v[2])], [y0, y1] = [Math.min(v[1], v[3]), Math.max(v[1], v[3])];
        if (x1 - x0 < 1e-4 || y1 - y0 < 1e-4) continue;
        const cls = String(it.Classification ?? '').trim().toLowerCase();
        const score = Number(it.Confidence_Score ?? 0.5);
        if (!(score >= minScore)) continue;
        out.push({
          label: LABELS[cls] ?? 'other', score: Math.min(1, score),
          box: [tx0 + x0 * (tx1 - tx0), ty0 + y0 * (ty1 - ty0), tx0 + x1 * (tx1 - tx0), ty0 + y1 * (ty1 - ty0)],
        });
      }
      return out;
    })());
  }
  // one failed tile (e.g. unparsable reply) shouldn't lose the rest, but auth/network errors must surface
  const settled = await Promise.allSettled(jobs);
  const fatal = settled.find((s) => s.status === 'rejected' && s.reason instanceof ApiError) as PromiseRejectedResult | undefined;
  const ok = settled.filter((s): s is PromiseFulfilledResult<RawDet[]> => s.status === 'fulfilled');
  if (fatal && ok.length === 0) throw fatal.reason;
  return nms(ok.flatMap((s) => s.value), 0.4);
}
