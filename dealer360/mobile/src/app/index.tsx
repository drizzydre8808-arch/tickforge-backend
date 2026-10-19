import { router, useFocusEffect } from 'expo-router';
import React, { useCallback, useState } from 'react';
import { Text, View } from 'react-native';

import { Button, Card, H, Muted, Row, Screen } from '@/components/ui';
import { api } from '@/lib/api';
import { loadQueue } from '@/lib/queue';
import { useSettings } from '@/lib/settings';
import type { Vehicle } from '@/lib/types';

export default function Home() {
  const { ready } = useSettings();
  const [list, setList] = useState<Vehicle[]>([]);
  const [err, setErr] = useState('');
  const [queued, setQueued] = useState(0);

  useFocusEffect(
    useCallback(() => {
      if (!ready) return;
      loadQueue().then((q) => setQueued(q.length));
      api.vehicles().then((v) => { setList(v); setErr(''); }).catch((e) => setErr(e.message));
    }, [ready]),
  );

  return (
    <Screen>
      <Row>
        <Button title="New vehicle" onPress={() => router.push('/vehicle/new')} />
        <Button title="Settings" kind="ghost" onPress={() => router.push('/settings')} />
        {queued > 0 && <Button title={`Queue (${queued})`} kind="ghost" onPress={() => router.push('/uploads')} />}
      </Row>
      {err ? <Card><Text style={{ color: '#d92d20' }}>{err}</Text><Muted>Something went wrong reading local data.</Muted></Card> : null}
      {list.length === 0 && !err ? <Muted>No vehicles yet.</Muted> : null}
      {list.map((v) => (
        <Card key={v.id} onPress={() => router.push(`/vehicle/${v.id}`)}>
          <H>{v.reg || `Vehicle ${v.id}`}</H>
          <Muted>{[v.make, v.model, v.year].filter(Boolean).join(' ') || 'No details'}</Muted>
          <View><Muted>{v.shot_count ?? 0} shots · {v.defect_count ?? 0} defects</Muted></View>
        </Card>
      ))}
    </Screen>
  );
}
