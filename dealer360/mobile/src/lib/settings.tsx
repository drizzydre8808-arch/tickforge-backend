import * as SecureStore from 'expo-secure-store';
import React, { createContext, useContext, useEffect, useState } from 'react';

import { configureApi } from './api';

export interface Settings {
  baseUrl: string;
  apiKey: string;
}

const KEY = 'dealer360.settings';
const DEFAULTS: Settings = { baseUrl: 'http://192.168.1.10:8000', apiKey: '' };

async function load(): Promise<Settings> {
  try {
    const raw = await SecureStore.getItemAsync(KEY);
    return raw ? { ...DEFAULTS, ...JSON.parse(raw) } : DEFAULTS;
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
    const clean = { baseUrl: s.baseUrl.trim().replace(/\/+$/, ''), apiKey: s.apiKey.trim() };
    await SecureStore.setItemAsync(KEY, JSON.stringify(clean));
    configureApi(clean);
    setSettings(clean);
  };

  return <SettingsContext.Provider value={{ settings, ready, save }}>{children}</SettingsContext.Provider>;
}

export const useSettings = () => useContext(SettingsContext);
