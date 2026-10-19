/**
 * GoPro control over its own Wi-Fi access point (Open GoPro HTTP API).
 *
 * IMPORTANT: these endpoint paths are written from memory of the Open GoPro spec
 * and could NOT be checked against the current docs when this was built. They
 * are kept in one object so you can correct them quickly. Use the "Test
 * connection" button on the GoPro screen, then check the spec for your model:
 *   https://gopro.github.io/OpenGoPro/
 *
 * Requirements: a HERO9 or newer with Wi-Fi on (camera: Connections > Connect
 * Device > GoPro App), and the PHONE joined to the camera's Wi-Fi network.
 * While joined, the phone usually has no route to your server, so captures are
 * downloaded to the phone and queued for upload afterwards.
 */
import { Directory, File, Paths } from 'expo-file-system';

export const GOPRO = {
  base: 'http://10.5.5.9:8080',
  state: '/gopro/camera/state',
  shutterStart: '/gopro/camera/shutter/start',
  shutterStop: '/gopro/camera/shutter/stop',
  presetPhoto: '/gopro/camera/presets/set_group?id=1001',
  presetVideo: '/gopro/camera/presets/set_group?id=1000',
  lastCaptured: '/gopro/media/last_captured',
  mediaRoot: '/videos/DCIM',
};

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function call(path: string, timeoutMs = 8000): Promise<Response> {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const res = await fetch(GOPRO.base + path, { signal: ctl.signal });
    if (!res.ok) throw new Error(`GoPro answered ${res.status} for ${path}`);
    return res;
  } catch (e: any) {
    if (e?.name === 'AbortError') throw new Error('The GoPro did not answer. Is your phone on its Wi-Fi?');
    throw e;
  } finally {
    clearTimeout(t);
  }
}

export async function testConnection(): Promise<string> {
  const res = await call(GOPRO.state, 5000);
  await res.text();
  return 'Connected to the GoPro.';
}

async function downloadLast(): Promise<string> {
  const j = await (await call(GOPRO.lastCaptured)).json();
  const folder = j.folder ?? j.d;
  const file = j.file ?? j.n;
  if (!folder || !file) throw new Error('Could not find the file the GoPro just captured');
  const dir = new Directory(Paths.cache, 'gopro');
  if (!dir.exists) dir.create();
  const dest = new File(dir, String(file));
  if (dest.exists) dest.delete();
  const out = await File.downloadFileAsync(`${GOPRO.base}${GOPRO.mediaRoot}/${folder}/${file}`, dest);
  return out.uri;
}

/** Take one photo and return the local file URI. */
export async function takePhoto(): Promise<string> {
  await call(GOPRO.presetPhoto);
  await sleep(600);
  await call(GOPRO.shutterStart);
  await sleep(2200);
  return downloadLast();
}

/** Record a short clip and return the local file URI. */
export async function recordClip(seconds = 4): Promise<string> {
  await call(GOPRO.presetVideo);
  await sleep(600);
  await call(GOPRO.shutterStart);
  await sleep(seconds * 1000);
  await call(GOPRO.shutterStop);
  await sleep(2500);
  return downloadLast();
}
