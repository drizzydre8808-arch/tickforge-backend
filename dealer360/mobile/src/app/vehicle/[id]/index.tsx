import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import React, { useCallback, useState } from 'react';
import { Image, Text, View } from 'react-native';

import { Button, Card, Chip, H, Muted, Row, Screen } from '@/components/ui';
import { absUrl, api, withKey } from '@/lib/api';
import { niceLabel, palette } from '@/lib/theme';
import type { Defect, Vehicle } from '@/lib/types';

export default function VehicleScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const vid = Number(id);
  const [v, setV] = useState<Vehicle | null>(null);
  const [defects, setDefects] = useState<Defect[]>([]);
  const [err, setErr] = useState('');

  useFocusEffect(
    useCallback(() => {
      Promise.all([api.vehicle(vid), api.defects(vid)])
        .then(([a, b]) => { setV(a); setDefects(b); setErr(''); })
        .catch((e) => setErr(e.message));
    }, [vid]),
  );

  return (
    <Screen>
      <Card>
        <H>{v?.reg || `Vehicle ${vid}`}</H>
        <Muted>{[v?.make, v?.model, v?.year].filter(Boolean).join(' ')}</Muted>
        {err ? <Text style={{ color: palette.danger }}>{err}</Text> : null}
      </Card>
      <Row>
        <Button title="Guided capture" onPress={() => router.push(`/vehicle/${vid}/capture`)} />
        <Button title="Import" kind="ghost" onPress={() => router.push(`/vehicle/${vid}/import`)} />
        <Button title="GoPro" kind="ghost" onPress={() => router.push(`/vehicle/${vid}/gopro`)} />
      </Row>
      <Row>
        <Button title="360 viewer" kind="ghost" onPress={() => router.push({ pathname: '/vehicle/[id]/web', params: { id: String(vid), mode: 'viewer' } })} />
        <Button title="Condition report" kind="ghost" onPress={() => router.push({ pathname: '/vehicle/[id]/web', params: { id: String(vid), mode: 'report' } })} />
      </Row>
      <H>Defects ({defects.length})</H>
      {defects.length === 0 ? <Muted>None logged yet.</Muted> : null}
      {defects.map((d) => (
        <Card key={d.id} onPress={() => router.push(`/vehicle/${vid}/defect/${d.id}`)}>
          <View style={{ flexDirection: 'row', gap: 12 }}>
            {d.crop_url ? <Image source={{ uri: withKey(absUrl(d.crop_url)) }} style={{ width: 72, height: 72, borderRadius: 8 }} /> : null}
            <View style={{ flex: 1, gap: 4 }}>
              <Text style={{ fontWeight: '700', color: palette.ink }}>{niceLabel[d.label] ?? d.label} — {d.panel}</Text>
              <Muted>{d.description}</Muted>
              <Row>
                <Chip text={d.severity} color={palette.sev[d.severity]} active />
                <Chip text={d.status} />
              </Row>
            </View>
          </View>
        </Card>
      ))}
    </Screen>
  );
}
