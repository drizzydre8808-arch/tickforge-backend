import * as ImagePicker from 'expo-image-picker';
import { router } from 'expo-router';
import React, { useState } from 'react';
import { Text } from 'react-native';

import { Button, Field, Screen } from '@/components/ui';
import { api, lookupPlate, readPlate } from '@/lib/api';

export default function NewVehicle() {
  const [f, setF] = useState({ reg: '', vin: '', make: '', model: '', year: '', length_mm: '', width_mm: '' });
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (v: string) => setF((p) => ({ ...p, [k]: v }));
  const num = (v: string) => (v.trim() && !isNaN(Number(v)) ? Number(v) : undefined);

  const [info, setInfo] = useState('');
  const [scanBusy, setScanBusy] = useState(false);

  async function scan() {
    setScanBusy(true);
    setErr('');
    try {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) throw new Error('Camera permission needed');
      const r = await ImagePicker.launchCameraAsync({ quality: 0.9 });
      if (r.canceled) return;
      const p = await readPlate(r.assets[0].uri);
      if (p.best) {
        setF((x) => ({ ...x, reg: p.best! }));
        setInfo(`Read ${p.best}. Check it matches the plate, then tap Look up.`);
      } else {
        setInfo(p.candidates.length ? `Not sure: ${p.candidates.map((c) => c.vrm).join(', ')}. Type it in.` : 'Could not read the plate. Type it in.');
      }
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setScanBusy(false);
    }
  }

  async function lookup() {
    setScanBusy(true);
    setErr('');
    try {
      const d = await lookupPlate(f.reg.replace(/\s/g, ''));
      setF((x) => ({ ...x, reg: d.reg, make: d.make ?? x.make, year: d.year ? String(d.year) : x.year }));
      setInfo([d.colour, d.fuel, d.mot_status && `MOT ${d.mot_status}${d.mot_expiry ? ` to ${d.mot_expiry}` : ''}`, d.tax_status && `Tax ${d.tax_status}`].filter(Boolean).join(' · '));
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setScanBusy(false);
    }
  }

  async function create() {
    setBusy(true);
    try {
      const v = await api.createVehicle({
        reg: f.reg.trim().toUpperCase() || null, vin: f.vin.trim() || null,
        make: f.make.trim() || null, model: f.model.trim() || null,
        year: num(f.year), length_mm: num(f.length_mm), width_mm: num(f.width_mm),
      });
      router.replace(`/vehicle/${v.id}`);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen>
      <Button title="Scan number plate" kind="ghost" onPress={scan} busy={scanBusy} />
      <Field label="Registration" value={f.reg} onChangeText={set('reg')} autoCapitalize="characters" />
      <Button title="Look up (DVLA)" kind="ghost" onPress={lookup} busy={scanBusy} disabled={!f.reg.trim()} />
      {info ? <Text>{info}</Text> : null}
      <Field label="VIN" value={f.vin} onChangeText={set('vin')} />
      <Field label="Make" value={f.make} onChangeText={set('make')} autoCapitalize="words" />
      <Field label="Model" value={f.model} onChangeText={set('model')} autoCapitalize="words" />
      <Field label="Year" value={f.year} onChangeText={set('year')} keyboardType="number-pad" />
      <Field label="Length mm (improves size estimates)" value={f.length_mm} onChangeText={set('length_mm')} keyboardType="number-pad" />
      <Field label="Width mm" value={f.width_mm} onChangeText={set('width_mm')} keyboardType="number-pad" />
      {err ? <Text style={{ color: '#d92d20' }}>{err}</Text> : null}
      <Button title="Create" onPress={create} busy={busy} />
    </Screen>
  );
}
