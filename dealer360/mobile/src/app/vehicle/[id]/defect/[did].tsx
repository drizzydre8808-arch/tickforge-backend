import { router, useLocalSearchParams } from 'expo-router';
import React, { useEffect, useState } from 'react';
import { Image, Text } from 'react-native';

import { Button, Card, Chip, Field, H, Muted, Row, Screen } from '@/components/ui';
import { absUrl, api, withKey } from '@/lib/api';
import { niceLabel, palette } from '@/lib/theme';
import type { Defect } from '@/lib/types';

export default function DefectScreen() {
  const { id, did } = useLocalSearchParams<{ id: string; did: string }>();
  const [d, setD] = useState<Defect | null>(null);
  const [note, setNote] = useState('');
  const [err, setErr] = useState('');

  useEffect(() => {
    api.defects(Number(id)).then((all) => {
      const f = all.find((x) => x.id === Number(did)) ?? null;
      setD(f);
      setNote(f?.note ?? '');
    }).catch((e) => setErr(e.message));
  }, [id, did]);

  async function patch(p: Parameters<typeof api.patchDefect>[1]) {
    try {
      setD(await api.patchDefect(Number(did), p));
    } catch (e: any) {
      setErr(e.message);
    }
  }

  if (!d) return <Screen>{err ? <Text style={{ color: palette.danger }}>{err}</Text> : <Muted>Loading…</Muted>}</Screen>;
  const sz = d.size_mm;
  const pos = d.zone?.car_position;

  return (
    <Screen>
      <H>{niceLabel[d.label] ?? d.label} — {d.panel}</H>
      {d.crop_url ? <Image source={{ uri: withKey(absUrl(d.crop_url)) }} style={{ width: '100%', aspectRatio: 1, borderRadius: 12 }} resizeMode="contain" /> : null}
      {d.overview_url ? <Image source={{ uri: withKey(absUrl(d.overview_url)) }} style={{ width: '100%', aspectRatio: 4 / 3, borderRadius: 12 }} resizeMode="contain" /> : null}
      <Card>
        <Muted>{d.description}</Muted>
        <Muted>Side: {d.side} · Band: {d.band}</Muted>
        {pos ? <Muted>Position on car: {Object.entries(pos).map(([k, v]) => `${k} ${Math.round(Number(v) * 100)}%`).join(', ')}</Muted> : null}
        {d.zone?.also_touches?.length ? <Muted>Also touches: {d.zone.also_touches.join(', ')}</Muted> : null}
        <Muted>Confidence {Math.round(d.score * 100)}% · seen in {d.seen_in?.length ?? 1} view(s) · {d.detector}</Muted>
        {sz ? (
          <Muted>
            {sz.approximate ? '≈ ' : ''}{sz.length_mm} × {sz.width_mm} mm, area {sz.area_mm2} mm² (scale: {sz.scale_source}; smallest detectable here ≈ {sz.min_detectable_mm} mm)
          </Muted>
        ) : <Muted>Size not estimated for this view.</Muted>}
      </Card>
      <Row>
        {(['minor', 'moderate', 'severe'] as const).map((s) => (
          <Chip key={s} text={s} color={palette.sev[s]} active={d.severity === s} onPress={() => patch({ severity: s })} />
        ))}
      </Row>
      <Field label="Note" value={note} onChangeText={setNote} multiline autoCapitalize="sentences" />
      <Button title="Save note" kind="ghost" onPress={() => patch({ note })} />
      <Row>
        <Button title="Confirm" onPress={() => patch({ status: 'confirmed' }).then(() => router.back())} />
        <Button title="Reject (false alarm)" kind="danger" onPress={() => patch({ status: 'rejected' }).then(() => router.back())} />
      </Row>
      {err ? <Text style={{ color: palette.danger }}>{err}</Text> : null}
    </Screen>
  );
}
