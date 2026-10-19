import * as DocumentPicker from 'expo-document-picker';
import * as ImagePicker from 'expo-image-picker';
import { useLocalSearchParams } from 'expo-router';
import React, { useState } from 'react';
import { Text } from 'react-native';

import { Button, Card, Chip, Field, H, Muted, Row, Screen } from '@/components/ui';
import { palette } from '@/lib/theme';
import { makeJob, submit } from '@/lib/uploader';
import { ALL_VIEWS, WALKAROUND, type Lens, type MediaKind, type View } from '@/lib/types';

const SOURCES = ['Insta360', 'GoPro', 'DJI', 'USB 360', 'Other'];
const KINDS: { k: MediaKind; t: string }[] = [
  { k: 'photo', t: 'Flat photo' },
  { k: 'video', t: 'Video clip' },
];
// Default evenly spaced yaw per walkaround view for a 360 taken from the car's centre
const DEFAULT_YAW: Record<string, number> = {
  front: 0, front_offside: 45, offside: 90, rear_offside: 135, rear: 180, rear_nearside: 225, nearside: 270, front_nearside: 315,
};

export default function Import() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [source, setSource] = useState('Insta360');
  const [kind, setKind] = useState<MediaKind>('photo');
  const [view, setView] = useState<View>('nearside');
  const [fov, setFov] = useState('');
  const [mm, setMm] = useState('');
  const [log, setLog] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  async function pick(): Promise<string | null> {
    if (kind === 'equirect') {
      const r = await DocumentPicker.getDocumentAsync({ type: 'image/*', copyToCacheDirectory: true });
      return r.canceled ? null : r.assets[0].uri;
    }
    const r = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: kind === 'video' ? ['videos'] : ['images'], quality: 1,
    });
    return r.canceled ? null : r.assets[0].uri;
  }

  async function go() {
    setBusy(true);
    try {
      const uri = await pick();
      if (!uri) return;
      const lens: Lens | undefined = fov.trim() && Number(fov) > 0 ? { model: 'equidistant', fov_deg: Number(fov) } : undefined;
      const mmPerPx = mm.trim() && Number(mm) > 0 ? Number(mm) : undefined;
      const out = await submit(makeJob({
        vehicleId: Number(id), kind, uri, view, sourceCamera: source, mmPerPx, lens,
        yawViews: kind === 'equirect' ? DEFAULT_YAW : undefined,
      }));
      const line =
        out.status === 'sent' ? `${source} ${kind}: ${out.result.defects.length} defect(s)${out.result.tracking?.rejected_as_glare_or_noise?.length ? `, ${out.result.tracking.rejected_as_glare_or_noise.length} rejected as glare` : ''}`
        : out.status === 'queued' ? `Saved for later: ${out.error}` : `Rejected: ${out.error}`;
      setLog((l) => [line, ...l]);
    } catch (e: any) {
      setLog((l) => [e.message, ...l]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen>
      <Muted>
        Export from the camera’s own app first (Insta360 Studio/app → stitched JPG or MP4; GoPro/DJI → copy to the phone), then pick the file here.
      </Muted>
      <H>Camera</H>
      <Row>{SOURCES.map((s) => <Chip key={s} text={s} color={palette.brand} active={source === s} onPress={() => setSource(s)} />)}</Row>
      <H>File type</H>
      <Row>{KINDS.map((k) => <Chip key={k.k} text={k.t} color={palette.brand} active={kind === k.k} onPress={() => setKind(k.k)} />)}</Row>
      {kind === 'equirect' ? (
        <Card><Muted>The 360 is cut into the 8 walkaround views assuming the camera sat at the car’s centre facing the front. Rotate the image first if not.</Muted></Card>
      ) : (
        <>
          <H>Which side of the car?</H>
          <Row>
            {[...WALKAROUND.map((w) => w.view), ...ALL_VIEWS.filter((v) => v === 'roof')].map((v) => (
              <Chip key={v} text={v.replace('_', ' ')} color={palette.brand} active={view === v} onPress={() => setView(v)} />
            ))}
          </Row>
        </>
      )}
      <Field label="Lens FOV degrees (fisheye only, optional)" value={fov} onChangeText={setFov} keyboardType="decimal-pad" />
      <Field label="mm per pixel (optional, if known)" value={mm} onChangeText={setMm} keyboardType="decimal-pad" />
      <Button title="Choose file & analyse" onPress={go} busy={busy} />
      {log.map((l, i) => <Text key={i} style={{ color: palette.ink }}>{l}</Text>)}
    </Screen>
  );
}
