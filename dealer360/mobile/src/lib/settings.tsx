import * as SecureStore from 'expo-secure-store';
import React, { createContext, useContext, useEffect, useState } from 'react';

import { configureApi } from './api';

export interface Settings {
  anthropicKey: string;
  dvlaKey: string;
}

const KEY = 'dealer360.settings';
// Optionally baked in at build time (see eas.json env); the Settings screen overrides them.
const DEFAULTS: Settings = {
  anthropicKey: process.env.EXPO_PUBLIC_ANTHROPIC_API_KEY || '',
  dvlaKey: process.env.EXPO_PUBLIC_DVLA_API_KEY || '',
};

async function load(): Promise<Settings> {
  try {
    const raw = await SecureStore.getItemAsync(KEY);
    const saved = raw ? JSON.parse(raw) : {};
    return { anthropicKey: saved.anthropicKey || DEFAULTS.anthropicKey, dvlaKey: saved.dvlaKey || DEFAULTS.dvlaKey };
  } catch {
    return DEFAULTS;
  }
}

interface Ctx {
  settings: Settings;
  ready: boolean;
  save: (s: Settings) => Promise<void>;
}

const SettingsContext = createContext<Ctx>({ settings: DEFAULTS, ready: false, save: async () => {} });

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  const [settings, setSettings] = useState<Settings>(DEFAULTS);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    load().then((s) => {
      configureApi(s);
      setSettings(s);
      setReady(true);
    });
  }, []);

  const save = async (s: Settings) => {
    const clean = { anthropicKey: s.anthropicKey.trim(), dvlaKey: s.dvlaKey.trim() };
    await SecureStore.setItemAsync(KEY, JSON.stringify(clean));
    configureApi(clean);
    setSettings(clean);
  };

  return <SettingsContext.Provider value={{ settings, ready, save }}>{children}</SettingsContext.Provider>;
}

export const useSettings = () => useContext(SettingsContext);
