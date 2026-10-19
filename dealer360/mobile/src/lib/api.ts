import { ApiError } from './errors';
import { DEFAULT_LENGTH_MM } from './local/zones';
import { processJob } from './local/process';
import { dvlaLookup, readPlateLocal } from './local/plate';
import { complete, VLM_MODEL } from './local/detect';
import { load, nextId, removeVehicleMedia, save } from './local/store';
import type { Defect, DefectStatus, PlateInfo, PlateRead, ShotResult, UploadJob, Vehicle } from './types';

export { ApiError };
export type { PlateInfo, PlateRead };
void DEFAULT_LENGTH_MM;

/** Everything now runs on the device; only the AI and DVLA keys are configured. */
let cfg = { anthropicKey: '', dvlaKey: '' };
export function configureApi(s: { anthropicKey: string; dvlaKey: string }) {
  cfg = { anthropicKey: s.anthropicKey, dvlaKey: s.dvlaKey };
}

/** Media is stored as local file:// URIs, so these are pass-throughs kept for the screens. */
export const absUrl = (p: string | null | undefined) => p ?? '';
export const withKey = (u: string) => u;

const counts = async (v: Vehicle): Promise<Vehicle> => {
  const db = await load();
  return {
    ...v,
    shot_count: db.shots.filter((s) => s.vehicle_id === v.id).length,
    defect_count: db.defects.filter((d) => d.vehicle_id === v.id && d.status !== 'rejected').length,
  };
};

export const api = {
  /** Checks the AI key with a tiny request. */
  health: async () => {
    if (!cfg.anthropicKey) throw new ApiError(401, 'Add your Anthropic API key to turn on damage detection');
    const px = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';
    await complete(cfg.anthropicKey, px, 'Reply with {"defects": []}', 20);
    return { ok: true, detector: VLM_MODEL };
  },
  vehicles: async () => {
    const db = await load();
    return Promise.all([...db.vehicles].reverse().map(counts));
  },
  vehicle: async (id: number) => {
    const v = (await load()).vehicles.find((x) => x.id === id);
    if (!v) throw new ApiError(404, 'Vehicle not found');
    return counts(v);
  },
  createVehicle: async (v: Partial<Vehicle>) => {
    const db = await load();
    const rec: Vehicle = { ...(v as Vehicle), id: await nextId(), created_at: new Date().toISOString() };
    db.vehicles.push(rec);
    await save();
    return rec;
  },
  deleteVehicle: async (id: number) => {
    const db = await load();
    db.vehicles = db.vehicles.filter((v) => v.id !== id);
    db.shots = db.shots.filter((s) => s.vehicle_id !== id);
    db.defects = db.defects.filter((d) => d.vehicle_id !== id);
    removeVehicleMedia(id);
    await save();
  },
  defects: async (id: number) => (await load()).defects.filter((d) => d.vehicle_id === id),
  patchDefect: async (id: number, patch: { status?: DefectStatus; note?: string; severity?: string }) => {
    const d = (await load()).defects.find((x) => x.id === id);
    if (!d) throw new ApiError(404, 'Defect not found');
    Object.assign(d, patch);
    await save();
    return d as Defect;
  },
};

export const uploadJob = (job: UploadJob): Promise<ShotResult> => processJob(job, cfg.anthropicKey);
export const readPlate = (uri: string) => readPlateLocal(uri);
export const lookupPlate = (vrm: string) => dvlaLookup(vrm, cfg.dvlaKey);
