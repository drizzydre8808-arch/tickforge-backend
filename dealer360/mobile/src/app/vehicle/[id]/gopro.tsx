import { useLocalSearchParams } from 'expo-router';
import React, { useState } from 'react';
import { Text } from 'react-native';

import { Button, Card, Chip, Muted, Row, Screen } from '@/components/ui';
import { recordClip, takePhoto, testConnection } from '@/lib/gopro';
import { palette } from '@/lib/theme';
import { makeJob, submit } from '@/lib/uploader';
import { WALKAROUND, type View } from '@/lib/types';

export default function GoPro() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [view, setView] = useState<View>('nearside');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');

  async function run(fn: () => Promise<string>, kind: 'photo' | 'video') {
    setBusy(true);
    setMsg('');
    try {
      const uri = await fn();
      const out = await submit(makeJob({ vehicleId: Number(id), kind, uri, view, sourceCamera: 'GoPro' }));
      setMsg(
        out.status === 'sent' ? `Uploaded: ${out.result.defects.length} defect(s)`
        : out.status === 'queued' ? 'Saved on the phone. Rejoin your normal Wi-Fi and open Upload queue to send it.'
        : `Server rejected it: ${out.error}`,
      );
    } catch (e: any) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen>
      <Card>
        <Muted>
          HERO9 or newer. Turn on the camera’s Wi-Fi, join it from your phone’s Wi-Fi settings, then test. While joined, the phone usually can’t reach your server, so uploads go to the queue.
        </Muted>
        <Muted>Control endpoints are unverified against current GoPro docs. If a call fails, correct them in src/lib/gopro.ts.</Muted>
      </Card>
      <Button title="Test connection" kind="ghost" onPress={async () => { setBusy(true); try { setMsg(await testConnection()); } catch (e: any) { setMsg(e.message); } finally { setBusy(false); } }} busy={busy} />
      <Row>{WALKAROUND.map((w) => <Chip key={w.view} text={w.view.replace('_', ' ')} color={palette.brand} active={view === w.view} onPress={() => setView(w.view)} />)}</Row>
      <Button title="Take photo" onPress={() => run(takePhoto, 'photo')} busy={busy} />
      <Button title="Record 4 s clip (glare-checked)" kind="ghost" onPress={() => run(() => recordClip(4), 'video')} busy={busy} />
      {msg ? <Text style={{ color: palette.ink }}>{msg}</Text> : null}
    </Screen>
  );
}
