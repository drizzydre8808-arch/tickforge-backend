/**
 * Durable upload queue.
 *
 * Why it exists: while the phone is joined to a GoPro's Wi-Fi it usually can't
 * reach your Dealer360 server. Captures are therefore copied into app storage and
 * retried later, instead of being lost or blocking the dealer.
 */
import { Directory, File, Paths } from 'expo-file-system';

import { uploadJob } from './api';
import type { UploadJob } from './types';

const dir = new Directory(Paths.document, 'pending');
const qfile = new File(Paths.document, 'upload-queue.json');

export function newJobId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export async function loadQueue(): Promise<UploadJob[]> {
  try {
    if (!qfile.exists) return [];
    const parsed = JSON.parse(await qfile.text());
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

async function saveQueue(q: UploadJob[]) {
  if (!qfile.exists) qfile.create();
  await qfile.write(JSON.stringify(q));
}

export async function enqueue(job: UploadJob, error?: string): Promise<UploadJob> {
  if (!dir.exists) dir.create();
  const ext = /\.[A-Za-z0-9]{2,5}$/.exec(job.uri)?.[0] ?? '';
  const dest = new File(dir, `${job.id}${ext}`);
  if (!dest.exists) new File(job.uri).copy(dest);
  const stored: UploadJob = { ...job, uri: dest.uri, lastError: error, attempts: job.attempts };
  const q = (await loadQueue()).filter((j) => j.id !== job.id);
  await saveQueue([...q, stored]);
  return stored;
}

export async function removeJob(id: string) {
  const q = await loadQueue();
  const job = q.find((j) => j.id === id);
  if (job) {
    try {
      const f = new File(job.uri);
      if (f.exists) f.delete();
    } catch {
      /* best effort */
    }
  }
  await saveQueue(q.filter((j) => j.id !== id));
}

/** Try everything in the queue once. Failed jobs stay queued with their last error. */
export async function runQueue(): Promise<{ sent: number; failed: number }> {
  let sent = 0;
  let failed = 0;
  for (const job of await loadQueue()) {
    try {
      await uploadJob(job);
      await removeJob(job.id);
      sent++;
    } catch (e: any) {
      failed++;
      const q = await loadQueue();
      await saveQueue(
        q.map((j) => (j.id === job.id ? { ...j, attempts: j.attempts + 1, lastError: String(e?.message ?? e) } : j)),
      );
    }
  }
  return { sent, failed };
}
