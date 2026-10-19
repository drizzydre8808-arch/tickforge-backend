import { useLocalSearchParams } from 'expo-router';
import React from 'react';
import { Share, View } from 'react-native';
import { WebView } from 'react-native-webview';

import { Button } from '@/components/ui';
import { reportUrl, viewerUrl } from '@/lib/api';

export default function Web() {
  const { id, mode } = useLocalSearchParams<{ id: string; mode?: string }>();
  const url = mode === 'report' ? reportUrl(Number(id)) : viewerUrl(Number(id));
  return (
    <View style={{ flex: 1 }}>
      <WebView source={{ uri: url }} originWhitelist={['*']} javaScriptEnabled style={{ flex: 1 }} />
      <View style={{ padding: 8 }}>
        <Button title="Share link" kind="ghost" onPress={() => Share.share({ message: url })} />
      </View>
    </View>
  );
}
