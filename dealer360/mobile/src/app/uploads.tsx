import { useFocusEffect } from 'expo-router';
import React, { useCallback, useState } from 'react';
import { Text } from 'react-native';

import { Button, Card, Muted, Row, Screen } from '@/components/ui';
import { loadQueue, removeJob, runQueue } from '@/lib/queue';
import type { UploadJob } from '@/lib/types';

export default function Uploads() {
  const [q, setQ] = useState<UploadJob[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const refresh = useCallback(() => { loadQueue().then(setQ); }, []);
  useFocusEffect(refresh);

  async function retry() {
    setBusy(true);
    const r = await runQueue();
    setMsg(`${r.sent} sent, ${r.failed} failed`);
    setBusy(false);
    refresh();
  }

  return (
    <Screen>
      <Muted>Captures waiting for internet to be analysed (e.g. phone on a GoPro’s Wi-Fi). Rejoin your normal network, then retry.</Muted>
      <Button title="Retry all" onPress={retry} busy={busy} disabled={q.length === 0} />
      {msg ? <Muted>{msg}</Muted> : null}
      {q.map((j) => (
        <Card key={j.id}>
          <Text style={{ fontWeight: '700' }}>Vehicle {j.vehicleId} · {j.view} · {j.kind}</Text>
          <Muted>Tries: {j.attempts}{j.lastError ? ` · ${j.lastError}` : ''}</Muted>
          <Row><Button title="Discard" kind="danger" onPress={() => removeJob(j.id).then(refresh)} /></Row>
        </Card>
      ))}
      {q.length === 0 ? <Muted>Queue is empty.</Muted> : null}
    </Screen>
  );
}
