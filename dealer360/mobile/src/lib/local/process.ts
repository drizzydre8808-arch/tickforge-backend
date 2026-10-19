/** Ingest a capture on the device: detect -> locate on the car -> crop -> log. Port of backend/app/pipeline.py. */
import { manipulateAsync, SaveFormat } from 'expo-image-manipulator';
import { getThumbnailAsync } from 'expo-video-thumbnails';

import { ApiError } from '../errors';
import type { Defect, ShotResult, UploadJob } from '../types';
import { detect, type RawDet } from './detect';
import { load, keepFile, nextId, save, type ShotRec } from './store';
import { DEFAULT_FRAME_BOX, DEFAULT_LENGTH_MM, DEFAULT_WIDTH_MM, resolveZone } from './zones';

const SEV = ['minor', 'moderate', 'severe'] as const;
const HIGH_RISK = new Set(['crack', 'rust']);
const SIDE_VIEWS = new Set(['nearside', 'offside']);
const END_VIEWS = new Set(['front', 'rear']);

function severityFor(label: string, b: number[]): (typeof SEV)[number] {
  const fw = DEFAULT_FRAME_BOX[2] - DEFAULT_FRAME_BOX[0], fh = DEFAULT_FRAME_BOX[3] - DEFAULT_FRAME_BOX[1];
  const area = Math.max(0, (b[2] - b[0]) * (b[3] - b[1])) / (fw * fh);
  let idx = area < 0.0015 ? 0 : area < 0.008 ? 1 : 2;
  if (label === 'scratch') {
    const len = Math.max(b[2] - b[0], b[3] - b[1]) / fw;
    idx = len < 0.06 ? 0 : len < 0.18 ? 1 : 2;
  }
  if (HIGH_RISK.has(label)) idx = Math.max(idx, 1);
  return SEV[idx];
}

function sizeMm(b: number[], view: string, w: number, h: number, length: number, width: number, mmpp?: number) {
  let src = 'client';
  if (!mmpp) {
    const real = SIDE_VIEWS.has(view) ? length : END_VIEWS.has(view) ? width : 0;
    if (!real) return null;
    mmpp = real / ((DEFAULT_FRAME_BOX[2] - DEFAULT_FRAME_BOX[0]) * w);
    src = 'vehicle_size';
  }
  const bw = (b[2] - b[0]) * w * mmpp, bh = (b[3] - b[1]) * h * mmpp;
  const l = Math.max(bw, bh), wd = Math.min(bw, bh);
  return {
    length_mm: Math.round(l * 10) / 10, width_mm: Math.round(wd * 10) / 10, area_mm2: Math.round(bw * bh),
    min_detectable_mm: Math.round(mmpp * 3 * 100) / 100, scale_source: src, approximate: true,
  };
}

interface Frame { uri: string; w: number; h: number }

async function normalise(uri: string): Promise<Frame> {
  // re-encode (bakes in EXIF rotation) and cap the size so uploads/tiles stay reasonable
  const probe = await manipulateAsync(uri, [], { format: SaveFormat.JPEG });
  const big = Math.max(probe.width, probe.height) > 3000;
  const r = big
    ? await manipulateAsync(uri, [{ resize: probe.width >= probe.height ? { width: 3000 } : { height: 3000 } }], { compress: 0.92, format: SaveFormat.JPEG })
    : await manipulateAsync(uri, [], { compress: 0.95, format: SaveFormat.JPEG });
  return { uri: r.uri, w: r.width, h: r.height };
}

async function cropOut(f: Frame, box: number[], pad = 0.5) {
  const bw = (box[2] - box[0]) * f.w, bh = (box[3] - box[1]) * f.h;
  const side = Math.max(bw, bh) * (1 + pad * 2) + 80;
  const cx = ((box[0] + box[2]) / 2) * f.w, cy = ((box[1] + box[3]) / 2) * f.h;
  const s = Math.min(side, f.w, f.h);
  const x = Math.round(Math.min(Math.max(0, cx - s / 2), f.w - s)), y = Math.round(Math.min(Math.max(0, cy - s / 2), f.h - s));
  return manipulateAsync(f.uri, [{ crop: { originX: x, originY: y, width: Math.round(s), height: Math.round(s) } }, { resize: { width: 600 } }], { compress: 0.9, format: SaveFormat.JPEG });
}

export async function processJob(job: UploadJob, apiKey: string): Promise<ShotResult> {
  const db = await load();
  const vehicle = db.vehicles.find((v) => v.id === job.vehicleId);
  if (!vehicle) throw new ApiError(404, 'Vehicle not found');
  if (job.kind === 'equirect') throw new ApiError(400, '360 stitched photos are not supported in the standalone app. Import flat photos or a video clip instead.');

  const length = vehicle.length_mm || DEFAULT_LENGTH_MM, width = vehicle.width_mm || DEFAULT_WIDTH_MM;
  const frames: Frame[] = [];
  let tracking: ShotResult['tracking'];

  if (job.kind === 'video') {
    for (const t of [300, 1200, 2100, 3000]) {
      try {
        const th = await getThumbnailAsync(job.uri, { time: t, quality: 1 });
        frames.push(await normalise(th.uri));
      } catch { /* clip shorter than this timestamp */ }
    }
    if (frames.length === 0) throw new ApiError(400, 'Could not read frames from that video');
  } else {
    frames.push(await normalise(job.uri));
  }

  const perFrame: RawDet[][] = [];
  for (const f of frames) perFrame.push(await detect(apiKey, f.uri, f.w, f.h, job.kind === 'video' ? [1, 1] : [2, 2]));

  // Video: a real defect stays on the same part of the car in several frames; glare drifts.
  let kept: { det: RawDet; frame: Frame }[] = [];
  if (job.kind === 'video' && frames.length >= 3) {
    const rejected: { label: string; hits: number; visible_in: number }[] = [];
    perFrame.forEach((dets, i) => dets.forEach((d) => {
      const hits = perFrame.filter((o) => o.some((x) => x.label === d.label && Math.hypot((x.box[0] + x.box[2] - d.box[0] - d.box[2]) / 2, (x.box[1] + x.box[3] - d.box[1] - d.box[3]) / 2) < 0.06)).length;
      if (hits >= 2) {
        if (!kept.some((k) => k.det.label === d.label && Math.hypot((k.det.box[0] + k.det.box[2] - d.box[0] - d.box[2]) / 2, (k.det.box[1] + k.det.box[3] - d.box[1] - d.box[3]) / 2) < 0.06)) kept.push({ det: d, frame: frames[i] });
      } else rejected.push({ label: d.label, hits, visible_in: frames.length });
    }));
    tracking = { frames_extracted: frames.length, frames_analysed: frames.length, confirmed: kept.length, rejected_as_glare_or_noise: rejected };
  } else {
    kept = perFrame.flatMap((dets, i) => dets.map((det) => ({ det, frame: frames[i] })));
  }

  const shotId = await nextId();
  const base = frames[Math.floor(frames.length / 2)];
  const stored = keepFile(job.vehicleId, base.uri, `shot-${shotId}.jpg`);
  const shot: ShotRec = {
    id: shotId, vehicle_id: job.vehicleId, view: job.view, kind: job.kind, uri: stored, width: base.w, height: base.h,
    source_camera: job.sourceCamera, created_at: new Date().toISOString(),
  };
  db.shots.push(shot);

  const result: Defect[] = [];
  for (const { det, frame } of kept) {
    const zone = resolveZone(job.view, det.box);
    if (!zone) continue; // outside the car frame -> background
    const existing = db.defects.find((d) => d.vehicle_id === job.vehicleId && d.label === det.label && d.panel === zone.panel && d.status !== 'rejected' &&
      Math.abs((d.zone?.car_position?.along_length_pct ?? d.zone?.car_position?.across_width_pct_from_offside ?? 0) - (zone.car_position.along_length_pct ?? zone.car_position.across_width_pct_from_offside ?? 0)) <= 8 &&
      Math.abs((d.zone?.car_position?.height_pct ?? 0) - (zone.car_position.height_pct ?? 0)) <= 8);
    if (existing) {
      if (!existing.seen_in.includes(job.view)) existing.seen_in.push(job.view);
      if (det.score > existing.score) existing.score = det.score;
      continue;
    }
    const id = await nextId();
    const crop = await cropOut(frame, det.box);
    const ov = await manipulateAsync(frame.uri, [{ resize: { width: 1000 } }], { compress: 0.8, format: SaveFormat.JPEG });
    const d: Defect = {
      id, vehicle_id: job.vehicleId, shot_id: shotId, label: det.label, score: det.score,
      severity: severityFor(det.label, det.box), panel: zone.panel, side: zone.side, band: zone.band,
      description: zone.description, box: det.box, status: 'pending', seen_in: [job.view], detector: 'claude-vision',
      size_mm: sizeMm(det.box, job.view, frame.w, frame.h, length, width, job.mmPerPx),
      crop_url: keepFile(job.vehicleId, crop.uri, `crop-${id}.jpg`),
      overview_url: keepFile(job.vehicleId, ov.uri, `overview-${id}.jpg`),
      zone: { car_position: zone.car_position, also_touches: zone.also_touches },
    };
    db.defects.push(d);
    result.push(d);
  }
  await save();
  return { shot_id: shotId, defects: result, tracking };
}
