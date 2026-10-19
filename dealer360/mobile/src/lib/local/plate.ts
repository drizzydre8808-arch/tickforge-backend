/** UK number plate reading (on-device ML Kit OCR) and DVLA lookup. Port of backend/app/plate.py. */
import { extractTextFromImage, isSupported } from 'expo-text-extractor';

import { ApiError } from '../errors';
import type { PlateInfo, PlateRead } from '../types';

const UK = [/^[A-Z]{2}[0-9]{2}[A-Z]{3}$/, /^[A-Z][0-9]{1,3}[A-Z]{3}$/, /^[A-Z]{3}[0-9]{1,3}[A-Z]$/, /^[A-Z]{1,3}[0-9]{1,4}$/, /^[0-9]{1,4}[A-Z]{1,3}$/];
const TO_DIGIT: Record<string, string> = { O: '0', I: '1', Z: '2', S: '5', B: '8', G: '6', Q: '0' };
const TO_ALPHA: Record<string, string> = { '0': 'O', '1': 'I', '2': 'Z', '5': 'S', '8': 'B', '6': 'G' };

export const normalise = (t: string) => t.toUpperCase().replace(/[^A-Z0-9]/g, '');
export const isValidVrm = (s: string) => UK.some((p) => p.test(s));
function fixCurrent(s: string) {
  if (s.length !== 7) return s;
  return [...s].map((c, i) => (i === 2 || i === 3 ? TO_DIGIT[c] ?? c : TO_ALPHA[c] ?? c)).join('');
}

export async function readPlateLocal(uri: string): Promise<PlateRead> {
  if (!isSupported) throw new ApiError(400, 'Text recognition is not available on this device. Type the registration in.');
  const texts = await extractTextFromImage(uri);
  const votes = new Map<string, number>();
  for (const t of texts) {
    const n = normalise(t);
    for (const cand of [n, fixCurrent(n)]) {
      if (cand.length >= 2 && cand.length <= 8) votes.set(cand, (votes.get(cand) ?? 0) + 1);
    }
  }
  const cands = [...votes].map(([vrm, n]) => ({ vrm, valid: isValidVrm(vrm), votes: n }))
    .sort((a, b) => Number(b.valid) - Number(a.valid) || b.votes - a.votes || Number(b.vrm.length === 7) - Number(a.vrm.length === 7));
  return { best: cands[0]?.valid ? cands[0].vrm : null, candidates: cands.slice(0, 5) };
}

export async function dvlaLookup(vrmIn: string, apiKey: string): Promise<PlateInfo> {
  if (!apiKey) throw new ApiError(0, 'Add your DVLA API key in Settings');
  const vrm = normalise(vrmIn);
  if (!isValidVrm(vrm)) throw new ApiError(400, 'Not a valid UK registration');
  let res: Response;
  try {
    res = await fetch('https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles', {
      method: 'POST', headers: { 'x-api-key': apiKey, 'Content-Type': 'application/json' },
      body: JSON.stringify({ registrationNumber: vrm }),
    });
  } catch (e: any) {
    throw new ApiError(0, `No internet (${e?.message ?? 'network error'})`);
  }
  if (res.status === 404) throw new ApiError(404, 'DVLA has no record of that registration');
  if (!res.ok) throw new ApiError(res.status, `DVLA error ${res.status}`);
  const d = await res.json();
  const title = (s?: string) => (s ? s.charAt(0) + s.slice(1).toLowerCase() : null);
  return {
    reg: d.registrationNumber ?? vrm, make: title(d.make), year: d.yearOfManufacture ?? null, colour: title(d.colour),
    fuel: d.fuelType ?? null, mot_status: d.motStatus ?? null, mot_expiry: d.motExpiryDate ?? null,
    tax_status: d.taxStatus ?? null, tax_due: d.taxDueDate ?? null,
  };
}
