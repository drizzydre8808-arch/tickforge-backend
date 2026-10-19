import React from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View, type TextInputProps } from 'react-native';

import { palette } from '@/lib/theme';

export function Screen({ children, scroll = true }: { children: React.ReactNode; scroll?: boolean }) {
  if (!scroll) return <View style={s.screen}>{children}</View>;
  return (
    <ScrollView style={s.screen} contentContainerStyle={{ padding: 16, gap: 12 }} keyboardShouldPersistTaps="handled">
      {children}
    </ScrollView>
  );
}

export function Card({ children, onPress }: { children: React.ReactNode; onPress?: () => void }) {
  const body = <View style={s.card}>{children}</View>;
  return onPress ? <Pressable onPress={onPress}>{body}</Pressable> : body;
}

export function H({ children }: { children: React.ReactNode }) {
  return <Text style={s.h}>{children}</Text>;
}
export function Muted({ children }: { children: React.ReactNode }) {
  return <Text style={s.muted}>{children}</Text>;
}

export function Button({
  title, onPress, kind = 'primary', busy, disabled,
}: { title: string; onPress: () => void; kind?: 'primary' | 'ghost' | 'danger'; busy?: boolean; disabled?: boolean }) {
  const bg = kind === 'primary' ? palette.brand : kind === 'danger' ? palette.danger : 'transparent';
  const fg = kind === 'ghost' ? palette.brand : palette.brandInk;
  return (
    <Pressable
      onPress={onPress}
      disabled={busy || disabled}
      style={[s.btn, { backgroundColor: bg, borderColor: kind === 'ghost' ? palette.brand : bg, opacity: busy || disabled ? 0.55 : 1 }]}>
      {busy ? <ActivityIndicator color={fg} /> : <Text style={[s.btnText, { color: fg }]}>{title}</Text>}
    </Pressable>
  );
}

export function Field({ label, ...rest }: { label: string } & TextInputProps) {
  return (
    <View style={{ gap: 4 }}>
      <Text style={s.label}>{label}</Text>
      <TextInput placeholderTextColor={palette.mute} autoCapitalize="none" autoCorrect={false} {...rest} style={s.input} />
    </View>
  );
}

export function Chip({ text, color = palette.mute, active, onPress }: { text: string; color?: string; active?: boolean; onPress?: () => void }) {
  return (
    <Pressable onPress={onPress} style={[s.chip, { borderColor: color, backgroundColor: active ? color : 'transparent' }]}>
      <Text style={{ color: active ? '#fff' : color, fontSize: 12, fontWeight: '600' }}>{text}</Text>
    </Pressable>
  );
}

export function Row({ children }: { children: React.ReactNode }) {
  return <View style={{ flexDirection: 'row', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>{children}</View>;
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: palette.bg },
  card: { backgroundColor: palette.card, borderRadius: 12, padding: 14, gap: 6, borderWidth: 1, borderColor: palette.line },
  h: { fontSize: 18, fontWeight: '700', color: palette.ink },
  muted: { fontSize: 13, color: palette.mute },
  btn: { borderRadius: 10, borderWidth: 1, paddingVertical: 12, paddingHorizontal: 16, alignItems: 'center', minHeight: 46, justifyContent: 'center' },
  btnText: { fontSize: 15, fontWeight: '600' },
  label: { fontSize: 12, fontWeight: '600', color: palette.mute },
  input: { borderWidth: 1, borderColor: palette.line, borderRadius: 10, padding: 10, fontSize: 15, color: palette.ink, backgroundColor: '#fff' },
  chip: { borderWidth: 1, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
});
