import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';

import { SettingsProvider } from '@/lib/settings';
import { palette } from '@/lib/theme';

export default function Layout() {
  return (
    <SettingsProvider>
      <StatusBar style="dark" />
      <Stack screenOptions={{ headerStyle: { backgroundColor: palette.card }, headerTitleStyle: { color: palette.ink } }}>
        <Stack.Screen name="index" options={{ title: 'Dealer360' }} />
        <Stack.Screen name="settings" options={{ title: 'Settings' }} />
        <Stack.Screen name="uploads" options={{ title: 'Upload queue' }} />
        <Stack.Screen name="vehicle/new" options={{ title: 'New vehicle' }} />
        <Stack.Screen name="vehicle/[id]/index" options={{ title: 'Vehicle' }} />
        <Stack.Screen name="vehicle/[id]/capture" options={{ title: 'Guided capture' }} />
        <Stack.Screen name="vehicle/[id]/import" options={{ title: 'Import from camera' }} />
        <Stack.Screen name="vehicle/[id]/gopro" options={{ title: 'GoPro' }} />
        <Stack.Screen name="vehicle/[id]/web" options={{ title: 'Viewer' }} />
        <Stack.Screen name="vehicle/[id]/defect/[did]" options={{ title: 'Defect' }} />
      </Stack>
    </SettingsProvider>
  );
}
