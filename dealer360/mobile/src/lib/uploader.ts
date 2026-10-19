import { ApiError, uploadJob } from './api';
import { enqueue, newJobId } from './queue';
import type { MediaKind, ShotResult, UploadJob, View } from './types';

export type SubmitOutcome =
  | { status: 'sent'; result: ShotResult }
  | { status: 'queued'; error: string }      // network trouble: saved, will retry
  | { status: 'rejected'; error: string };   // server said no (bad view / image): retrying won't help

export function makeJob(p: Omit<UploadJob, 'id' | 'createdAt' | 'attempts'>): UploadJob {
  return { ...p, id: newJobId(), createdAt: Date.now(), attempts: 0 };
}

export async function submit(job: UploadJob): Promise<SubmitOutcome> {
  try {
    return { status: 'sent', result: await uploadJob(job) };
  } catch (e: any) {
    const err = e as ApiError;
    // 4xx (other than auth/timeouts) means the request itself is wrong
    if (err?.status && err.status >= 400 && err.status < 500 && err.status !== 401 && err.status !== 408) {
      return { status: 'rejected', error: err.message };
    }
    await enqueue({ ...job, attempts: job.attempts + 1 }, err?.message ?? 'network error');
    return { status: 'queued', error: err?.message ?? 'network error' };
  }
}

export type { MediaKind, View };
