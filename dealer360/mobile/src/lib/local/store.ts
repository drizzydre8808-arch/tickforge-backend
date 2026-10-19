/** On-device database: one JSON file plus a media folder in app storage. */
import { Directory, File, Paths } from 'expo-file-system';

import type { Defect, Vehicle } from '../types';

export interface ShotRec {
  id: number; vehicle_id: number; view: string; kind: string; uri: string;
  width: number; height: number; source_camera?: string; created_at: string;
}
interface DB { next: number; vehicles: Vehicle[]; shots: ShotRec[]; defects: Defect[] }

const dbFile = new File(Paths.document, 'dealer360-db.json');
const mediaRoot = new Directory(Paths.document, 'media');
let db: DB | null = null;

export async function load(): Promise<DB> {
  if (db) return db;
  try {
    db = dbFile.exists ? (JSON.parse(await dbFile.text()) as DB) : { next: 1, vehicles: [], shots: [], defects: [] };
  } catch {
    db = { next: 1, vehicles: [], shots: [], defects: [] };
  }
  return db;
}

export async function save(): Promise<void> {
  if (!db) return;
  if (!dbFile.exists) dbFile.create();
  dbFile.write(JSON.stringify(db));
}

export const nextId = async () => { const d = await load(); return d.next++; };

export function vehicleDir(vid: number): Directory {
  if (!mediaRoot.exists) mediaRoot.create();
  const d = new Directory(mediaRoot, String(vid));
  if (!d.exists) d.create();
  return d;
}

/** Copy a (cache) file into the vehicle's media folder and return its permanent URI. */
export function keepFile(vid: number, srcUri: string, name: string): string {
  const dest = new File(vehicleDir(vid), name);
  if (dest.exists) dest.delete();
  new File(srcUri).copy(dest);
  return dest.uri;
}

export function removeVehicleMedia(vid: number) {
  try {
    const d = new Directory(mediaRoot, String(vid));
    if (d.exists) d.delete();
  } catch { /* best effort */ }
}
