import { File } from 'expo-file-system';
import { fetch as expoFetch } from 'expo/fetch';

import type { Defect, DefectStatus, ShotResult, UploadJob, Vehicle } from './types';

let cfg = { baseUrl: '', apiKey: '' };

export function configureApi(s: { baseUrl: string; apiKey: string }) {
  cfg = { baseUrl: s.baseUrl.replace(/\/+$/, ''), apiKey: s.apiKey };
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** Server-relative path (e.g. /media/1/x.jpg?key=..) -> absolute URL */
export function absUrl(path: string | null | undefined): string {
  if (!path) return '';
  return /^https?:/i.test(path) ? path : cfg.baseUrl + path;
}

/** Add the API key to a URL so a WebView / <Image> can load it without custom headers. */
export function withKey(url: string): string {
  if (!cfg.apiKey || url.includes('key=')) return url;
  return url + (url.includes('?') ? '&' : '?') + 'key=' + encodeURIComponent(cfg.apiKey);
}

function headers(extra?: Record<string, string>): Record<string, string> {
  return { ...(cfg.apiKey ? { 'X-API-Key': cfg.apiKey } : {}), ...extra };
}

async function parseError(res: Response): Promise<ApiError> {
  let msg = `${res.status}`;
  try {
    const j = await res.json();
    if (j?.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
  } catch {
    /* body wasn't JSON */
  }
  return new ApiError(res.status, msg);
}

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = 20000): Promise<T> {
  if (!cfg.baseUrl) throw new ApiError(0, 'Set the server address in Settings first');
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const res = await fetch(cfg.baseUrl + path, {
      ...init,
      headers: headers({ ...(init.body && typeof init.body === 'string' ? { 'Content-Type': 'application/json' } : {}) }),
      signal: ctl.signal,
    });
    if (!res.ok) throw await parseError(res);
    return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
  } catch (e: any) {
    if (e instanceof ApiError) throw e;
    if (e?.name === 'AbortError') throw new ApiError(0, 'Timed out reaching the server');
    throw new ApiError(0, `Can't reach the server (${e?.message ?? 'network error'})`);
  } finally {
    clearTimeout(t);
  }
}

export const api = {
  health: () => request<{ ok: boolean; detector: string }>('/health', {}, 6000),
  profile: () => request<{ views: string[]; frame_box: number[]; detector: string }>('/capture-profile'),
  vehicles: () => request<Vehicle[]>('/vehicles'),
  vehicle: (id: number) => request<Vehicle>(`/vehicles/${id}`),
  createVehicle: (v: Partial<Vehicle>) => request<Vehicle>('/vehicles', { method: 'POST', body: JSON.stringify(v) }),
  deleteVehicle: (id: number) => request<void>(`/vehicles/${id}`, { method: 'DELETE' }),
  defects: (id: number) => request<Defect[]>(`/vehicles/${id}/defects`),
  patchDefect: (id: number, patch: { status?: DefectStatus; note?: string; severity?: string }) =>
    request<Defect>(`/defects/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
};

export function reportUrl(vehicleId: number, embed = false): string {
  return withKey(`${cfg.baseUrl}/vehicles/${vehicleId}/report${embed ? '?embed=1' : ''}`);
}
export function viewerUrl(vehicleId: number): string {
  return withKey(`${cfg.baseUrl}/vehicles/${vehicleId}/viewer`);
}

/** Send one capture. Photos/360 go to /shots, video clips to /videos. */
export async function uploadJob(job: UploadJob): Promise<ShotResult> {
  if (!cfg.baseUrl) throw new ApiError(0, 'Set the server address in Settings first');
  const form = new FormData();
  form.append('file', new File(job.uri) as unknown as Blob);
  form.append('view', job.view);
  if (job.sourceCamera) form.append('source_camera', job.sourceCamera);
  if (job.mmPerPx) form.append('mm_per_px', String(job.mmPerPx));
  if (job.lens) form.append('lens', JSON.stringify(job.lens));
  let path = `/vehicles/${job.vehicleId}/shots`;
  if (job.kind === 'video') {
    path = `/vehicles/${job.vehicleId}/videos`;
  } else {
    form.append('kind', job.kind);
    if (job.kind === 'equirect' && job.yawViews) form.append('yaw_views', JSON.stringify(job.yawViews));
  }
  try {
    const res = await expoFetch(cfg.baseUrl + path, { method: 'POST', headers: headers(), body: form });
    if (!res.ok) {
      let msg = `${res.status}`;
      try {
        const j = await res.json();
        if (j?.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
      } catch {
        /* not JSON */
      }
      throw new ApiError(res.status, msg);
    }
    return (await res.json()) as ShotResult;
  } catch (e: any) {
    if (e instanceof ApiError) throw e;
    throw new ApiError(0, `Upload failed (${e?.message ?? 'network error'})`);
  }
}

export interface PlateRead {
  best: string | null;
  candidates: { vrm: string; valid: boolean; votes: number }[];
  error?: string;
}
export interface PlateInfo {
  reg: string; make?: string | null; year?: number | null; colour?: string | null;
  fuel?: string | null; mot_status?: string | null; mot_expiry?: string | null;
  tax_status?: string | null; tax_due?: string | null;
}

export async function readPlate(uri: string): Promise<PlateRead> {
  const form = new FormData();
  form.append('file', new File(uri) as unknown as Blob);
  const res = await expoFetch(cfg.baseUrl + '/plate/read', { method: 'POST', headers: headers(), body: form });
  if (!res.ok) throw new ApiError(res.status, `Plate read failed (${res.status})`);
  return (await res.json()) as PlateRead;
}

export const lookupPlate = (vrm: string) =>
  request<PlateInfo>(`/plate/lookup/${encodeURIComponent(vrm)}`, {}, 15000);
