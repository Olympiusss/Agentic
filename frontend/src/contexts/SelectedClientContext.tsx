import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { clientsApi } from '../services/api'
import { useAuth } from './AuthContext'

export interface ClientRecord {
  name: string
  has_edr: boolean
  has_siem: boolean
  s1_site_name: string | null
  av_deployment_name: string | null
  av_deployment_fqdn: string | null
  match_confidence: string | null
  // Unified-schema foundation, 2026-08-20: the real, persisted clients.client_id
  // this record maps to -- the actual scoping key, not just a display name.
  client_id: string | null
}

interface SelectedClientContextType {
  clients: ClientRecord[]
  loading: boolean
  selectedClient: ClientRecord | null
  setSelectedClient: (client: ClientRecord | null) => void
  // True for role-client users -- the selector must not render for them
  // and their selection is fixed to their own org, not user-controlled.
  isLocked: boolean
}

const SelectedClientContext = createContext<SelectedClientContextType | undefined>(undefined)

const STORAGE_KEY = 'sentry.selectedClientName'

export const useSelectedClient = () => {
  const context = useContext(SelectedClientContext)
  if (!context) throw new Error('useSelectedClient must be used within SelectedClientProvider')
  return context
}

export const SelectedClientProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user, isAuthenticated } = useAuth()
  const [clients, setClients] = useState<ClientRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedClient, setSelectedClientState] = useState<ClientRecord | null>(null)
  const isLocked = user?.role_id === 'role-client'

  useEffect(() => {
    if (!isAuthenticated) return
    let cancelled = false
    clientsApi.getAll()
      .then(res => { if (!cancelled) setClients(res.data?.clients || []) })
      .catch(err => console.error('Failed to load client list:', err))
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [isAuthenticated])

  // Client-role users: auto-lock to their real, scoped client. Prefer the
  // real client_id FK (users.client_id, added 2026-08-20 -- this is what
  // the backend actually enforces in GET /findings for role-client users)
  // over the older `organisation` free-text name match, which stays as a
  // fallback for a role-client user who hasn't had client_id set yet (the
  // backend itself fails closed -- zero findings -- in that case, but the
  // UI can still show *something* sensible rather than nothing selected).
  useEffect(() => {
    if (!isLocked || clients.length === 0) return
    const byClientId = user?.client_id ? clients.find(c => c.client_id === user.client_id) : undefined
    setSelectedClientState(byClientId || clients.find(c => c.name === user?.organisation) || null)
  }, [isLocked, clients, user?.client_id, user?.organisation])

  // Admin/guest: restore a previously-selected client once the list loads.
  useEffect(() => {
    if (isLocked || clients.length === 0) return
    const savedName = localStorage.getItem(STORAGE_KEY)
    if (!savedName) return
    const match = clients.find(c => c.name === savedName)
    if (match) setSelectedClientState(match)
  }, [isLocked, clients])

  const setSelectedClient = useCallback((client: ClientRecord | null) => {
    if (isLocked) return
    setSelectedClientState(client)
    if (client) localStorage.setItem(STORAGE_KEY, client.name)
    else localStorage.removeItem(STORAGE_KEY)
  }, [isLocked])

  return (
    <SelectedClientContext.Provider value={{ clients, loading, selectedClient, setSelectedClient, isLocked }}>
      {children}
    </SelectedClientContext.Provider>
  )
}
