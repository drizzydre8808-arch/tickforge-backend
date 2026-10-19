import { CameraView, useCameraPermissions } from 'expo-camera';
import { router, useLocalSearchParams } from 'expo-router';
import React, { useRef, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Button, Muted } from '@/components/ui';
import { palette } from '@/lib/theme';
import { makeJob, submit } from '@/lib/uploader';
import { WALKAROUND } from '@/lib/types';

// Same box the backend assumes contains the car (x0,y0,x1,y1 as fractions)
const BOX = [0.04, 0.22, 0.96, 0.88];

export default function Capture() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [perm, ask] = useCameraPermissions();
  const cam = useRef<CameraView>(null);
  const [i, setI] = useState(0);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');

  if (!perm) return <View />;
  if (!perm.granted) {
    return (
      <View style={{ padding: 16, gap: 12 }}>
        <Muted>Camera permission is needed for guided capture.</Muted>
        <Button title="Allow camera" onPress={ask} />
      </View>
    );
  }

  const step = WALKAROUND[i];

  async function shoot() {
    setBusy(true);
    try {
      const pic = await cam.current?.takePictureAsync({ quality: 0.95 });
      if (!pic) throw new Error('No picture taken');
      const out = await submit(makeJob({ vehicleId: Number(id), kind: 'photo', uri: pic.uri, view: step.view, sourceCamera: 'phone' }));
      if (out.status === 'sent') setStatus(`${step.title}: ${out.result.defects.length} defect(s) found`);
      else if (out.status === 'queued') setStatus(`${step.title}: saved, will analyse later (${out.error})`);
      else setStatus(`${step.title}: rejected (${out.error})`);
      if (i + 1 < WALKAROUND.length) setI(i + 1);
      else router.back();
    } catch (e: any) {
      setStatus(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={{ flex: 1, backgroundColor: '#000' }}>
      <View style={{ width: '100%', aspectRatio: 3 / 4 }}>
        <CameraView ref={cam} style={StyleSheet.absoluteFill} facing="back" ratio="4:3" />
        <View
          pointerEvents="none"
          style={{
            position: 'absolute', borderWidth: 2, borderColor: '#fff', borderStyle: 'dashed', borderRadius: 6,
            left: `${BOX[0] * 100}%`, top: `${BOX[1] * 100}%`, width: `${(BOX[2] - BOX[0]) * 100}%`, height: `${(BOX[3] - BOX[1]) * 100}%`,
          }}
        />
      </View>
      <View style={{ padding: 16, gap: 8, backgroundColor: palette.card, flex: 1 }}>
        <Text style={{ fontWeight: '700', fontSize: 16 }}>{i + 1}/{WALKAROUND.length} · {step.title}</Text>
        <Muted>{step.hint} Fit the whole car inside the dashed box.</Muted>
        {status ? <Muted>{status}</Muted> : null}
        <Button title="Capture" onPress={shoot} busy={busy} />
        <Button title="Skip this view" kind="ghost" onPress={() => (i + 1 < WALKAROUND.length ? setI(i + 1) : router.back())} />
      </View>
    </View>
  );
}
