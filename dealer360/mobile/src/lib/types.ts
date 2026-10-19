export type Severity = 'minor' | 'moderate' | 'severe';
export type DefectStatus = 'pending' | 'confirmed' | 'rejected';
export type MediaKind = 'photo' | 'equirect' | 'video';

export type View =
  | 'front' | 'front_nearside' | 'nearside' | 'rear_nearside'
  | 'rear' | 'rear_offside' | 'offside' | 'front_offside' | 'roof';

export const WALKAROUND: { view: View; title: string; hint: string }[] = [
  { view: 'front', title: 'Front', hint: 'Stand 3–4 m in front, centred on the bonnet.' },
  { view: 'front_nearside', title: 'Front nearside corner', hint: 'Front-left corner, car at 45°.' },
  { view: 'nearside', title: 'Nearside (left)', hint: 'Square on to the left side, whole car in the box.' },
  { view: 'rear_nearside', title: 'Rear nearside corner', hint: 'Rear-left corner, car at 45°.' },
  { view: 'rear', title: 'Rear', hint: 'Stand 3–4 m behind, centred on the tailgate.' },
  { view: 'rear_offside', title: 'Rear offside corner', hint: 'Rear-right corner, car at 45°.' },
  { view: 'offside', title: 'Offside (right)', hint: 'Square on to the right side, whole car in the box.' },
  { view: 'front_offside', title: 'Front offside corner', hint: 'Front-right corner, car at 45°.' },
];

export const ALL_VIEWS: View[] = [...WALKAROUND.map((w) => w.view), 'roof'];

export interface Vehicle {
  id: number;
  reg?: string | null;
  vin?: string | null;
  make?: string | null;
  model?: string | null;
  year?: number | null;
  length_mm?: number | null;
  width_mm?: number | null;
  notes?: string | null;
  created_at: string;
  shot_count?: number;
  defect_count?: number;
}

export interface SizeMm {
  length_mm: number;
  width_mm: number;
  area_mm2: number;
  min_detectable_mm: number;
  scale_source: string;
  approximate: boolean;
}

export interface Defect {
  id: number;
  vehicle_id: number;
  shot_id: number;
  label: string;
  score: number;
  severity: Severity;
  panel: string;
  side: string;
  band: string;
  description: string;
  box: number[];
  status: DefectStatus;
  seen_in: string[];
  detector: string;
  note?: string | null;
  size_mm?: SizeMm | null;
  crop_url?: string | null;
  overview_url?: string | null;
  zone?: { car_position?: Record<string, number>; also_touches?: string[] };
}

export interface TrackingInfo {
  frames_extracted: number;
  frames_analysed: number;
  frames_registered?: number;
  confirmed: number;
  rejected_as_glare_or_noise: { label: string; hits: number; visible_in: number }[];
  note?: string | null;
}

export interface ShotResult {
  shot_id: number;
  derived_shot_ids?: number[];
  defects: Defect[];
  tracking?: TrackingInfo;
}

export interface Lens {
  model: 'equidistant';
  fov_deg: number;
}

/** One capture waiting to be sent (or retried) */
export interface UploadJob {
  id: string;
  vehicleId: number;
  kind: MediaKind;
  uri: string;
  view: View;
  sourceCamera?: string;
  /** 360 only: which flat views to cut out, as view -> yaw degrees */
  yawViews?: Record<string, number>;
  mmPerPx?: number;
  lens?: Lens;
  createdAt: number;
  attempts: number;
  lastError?: string;
}
