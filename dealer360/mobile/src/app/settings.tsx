import { router } from 'expo-router';
import React, { useState } from 'react';

import { Button, Card, Field, Muted, Screen } from '@/components/ui';
import { api, configureApi } from '@/lib/api';
import { useSettings } from '@/lib/settings';

export default function SettingsScreen() {
  const { settings, save } = useSettings();
  const [anthropicKey, setAnthropicKey] = useState(settings.anthropicKey);
  const [dvlaKey, setDvlaKey] = useState(settings.dvlaKey);
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  async function test() {
    setBusy(true);
    configureApi({ anthropicKey: anthropicKey.trim(), dvlaKey: dvlaKey.trim() });
    try {
      const h = await api.health();
      setMsg(`AI detection connected (${h.detector}).`);
    } catch (e: any) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function doSave() {
    await save({ anthropicKey: anthropicKey.trim(), dvlaKey: dvlaKey.trim() });
    router.back();
  }

  return (
    <Screen>
      <Card>
        <Field label="Anthropic API key (damage detection)" value={anthropicKey} onChangeText={setAnthropicKey} secureTextEntry />
        <Field label="DVLA API key (plate lookup, optional)" value={dvlaKey} onChangeText={setDvlaKey} secureTextEntry />
        <Muted>Everything else runs on this device. Detection needs internet: each photo is sent to Anthropic for analysis. Keys are stored in the device&apos;s secure storage.</Muted>
      </Card>
      {msg ? <Muted>{msg}</Muted> : null}
      <Button title="Test AI connection" kind="ghost" onPress={test} busy={busy} />
      <Button title="Save" onPress={doSave} />
    </Screen>
  );
}
