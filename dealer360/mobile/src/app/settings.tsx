import { router } from 'expo-router';
import React, { useState } from 'react';

import { Button, Card, Field, Muted, Screen } from '@/components/ui';
import { api, configureApi } from '@/lib/api';
import { useSettings } from '@/lib/settings';

export default function SettingsScreen() {
  const { settings, save } = useSettings();
  const [baseUrl, setBaseUrl] = useState(settings.baseUrl);
  const [apiKey, setApiKey] = useState(settings.apiKey);
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  async function test() {
    setBusy(true);
    configureApi({ baseUrl: baseUrl.trim().replace(/\/+$/, ''), apiKey: apiKey.trim() });
    try {
      const h = await api.health();
      setMsg(`Connected. Detector: ${h.detector}`);
    } catch (e: any) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function doSave() {
    await save({ baseUrl: baseUrl.trim().replace(/\/+$/, ''), apiKey: apiKey.trim() });
    router.back();
  }

  return (
    <Screen>
      <Card>
        <Field label="Server address" value={baseUrl} onChangeText={setBaseUrl} placeholder="http://192.168.1.10:8000" keyboardType="url" />
        <Field label="API key (if set on the server)" value={apiKey} onChangeText={setApiKey} secureTextEntry />
        <Muted>Phone and server must be on the same network. Use HTTPS in production.</Muted>
      </Card>
      {msg ? <Muted>{msg}</Muted> : null}
      <Button title="Test connection" kind="ghost" onPress={test} busy={busy} />
      <Button title="Save" onPress={doSave} />
    </Screen>
  );
}
