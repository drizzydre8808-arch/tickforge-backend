import * as Print from 'expo-print';
import { useLocalSearchParams } from 'expo-router';
import * as Sharing from 'expo-sharing';
import React, { useEffect, useState } from 'react';
import { Text, View } from 'react-native';
import { WebView } from 'react-native-webview';

import { Button, Muted } from '@/components/ui';
import { buildReport, buildViewer } from '@/lib/local/outputs';

export default function Web() {
  const { id, mode } = useLocalSearchParams<{ id: string; mode?: string }>();
  const [html, setHtml] = useState('');
  const [err, setErr] = useState('');
  const report = mode === 'report';

  useEffect(() => {
    (report ? buildReport(Number(id)) : buildViewer(Number(id))).then(setHtml).catch((e) => setErr(e.message));
  }, [id, report]);

  async function share() {
    try {
      const { uri } = await Print.printToFileAsync({ html });
      await Sharing.shareAsync(uri, { mimeType: 'application/pdf', dialogTitle: 'Condition report' });
    } catch (e: any) {
      setErr(e.message);
    }
  }

  if (err) return <View style={{ padding: 16 }}><Text>{err}</Text></View>;
  if (!html) return <View style={{ padding: 16 }}><Muted>Building…</Muted></View>;
  return (
    <View style={{ flex: 1 }}>
      <WebView source={{ html }} originWhitelist={['*']} javaScriptEnabled style={{ flex: 1 }} />
      {report ? <View style={{ padding: 8 }}><Button title="Share as PDF" kind="ghost" onPress={share} /></View> : null}
    </View>
  );
}
