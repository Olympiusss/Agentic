import React, { createContext, useContext, useState, useEffect, useMemo, useCallback } from 'react'
import { ThemeProvider as MuiThemeProvider, CssBaseline } from '@mui/material'
import { createM3Theme } from '../theme'
import { configApi } from '../services/api'

export type ThemePreference = 'light' | 'dark' | 'system'
type ResolvedMode = 'light' | 'dark'

interface ThemeContextType {
  /** The user's stored preference -- 'system' follows the OS setting. */
  preference: ThemePreference
  /** The actual light/dark mode currently rendered (resolves 'system'). */
  mode: ResolvedMode
  setPreference: (preference: ThemePreference) => void
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined)

export const useThemePreference = () => {
  const context = useContext(ThemeContext)
  if (!context) throw new Error('useThemePreference must be used within ThemeProvider')
  return context
}

function getSystemMode(): ResolvedMode {
  if (typeof window === 'undefined' || !window.matchMedia) return 'dark'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function isThemePreference(value: unknown): value is ThemePreference {
  return value === 'light' || value === 'dark' || value === 'system'
}

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [preference, setPreferenceState] = useState<ThemePreference>('dark')
  const [systemMode, setSystemMode] = useState<ResolvedMode>(getSystemMode)

  useEffect(() => {
    configApi.getTheme()
      .then(res => { if (isThemePreference(res.data.theme)) setPreferenceState(res.data.theme) })
      .catch(() => {})
  }, [])

  // Track the OS preference live so a 'system' selection updates without reload.
  useEffect(() => {
    if (!window.matchMedia) return
    const mql = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => setSystemMode(mql.matches ? 'dark' : 'light')
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [])

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next)
    configApi.setTheme(next).catch(() => {})
  }, [])

  const mode: ResolvedMode = preference === 'system' ? systemMode : preference

  const theme = useMemo(() => createM3Theme(mode), [mode])

  return (
    <ThemeContext.Provider value={{ preference, mode, setPreference }}>
      <MuiThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </MuiThemeProvider>
    </ThemeContext.Provider>
  )
}
