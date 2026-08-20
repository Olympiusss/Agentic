/**
 * ClientDetail -- per-client EDR (SentinelOne) and/or SIEM (AlienVault
 * Central) detail, shown when a client is selected via the header's
 * ClientSelector (2026-08-15). Renders nothing when no client is selected
 * -- the existing tenant-wide SentinelOneOverview shows as-is, unchanged.
 *
 * Time window defaults to 24h, matching AlienVault's own console default
 * (confirmed via a live screenshot from the user) -- always user-
 * adjustable via the range selector below, never hardcoded past that
 * default.
 */
import { useEffect, useState } from 'react'
import {
  Box, Grid, Typography, Paper, CircularProgress, Select, MenuItem,
  FormControl, InputLabel, Alert, Chip,
} from '@mui/material'
import {
  SecurityOutlined as EdrIcon, VisibilityOutlined as SiemIcon,
} from '@mui/icons-material'
import { StatCard } from '../ui'
import { clientsApi } from '../../services/api'
import { useSelectedClient } from '../../contexts/SelectedClientContext'

interface SiteSummary {
  kind: string
  site_name: string
  endpoint_count: number
  agents_offline: number
  groups: string[]
  error: string | null
}

interface AlarmsResult {
  kind: string
  hours_back: number
  total: number
  by_priority: Record<string, number>
  by_status: Record<string, number>
  error: string | null
}

interface EventCountResult {
  kind: string
  hours_back: number
  total: number
  error: string | null
}

interface DetailResponse {
  name: string
  hours_back: number
  edr?: SiteSummary
  siem?: { alarms: AlarmsResult; events: EventCountResult }
}

const RANGE_OPTIONS = [
  { label: 'Last hour', hours: 1 },
  { label: 'Last 24 hours', hours: 24 },
  { label: 'Last 7 days', hours: 24 * 7 },
  { label: 'Last 30 days', hours: 24 * 30 },
]

function UnavailableNote({ kind, error }: { kind: string; error: string | null }) {
  if (kind === 'not_authorized') {
    return (
      <Alert severity="info" sx={{ mt: 1 }}>
        Not available -- this AlienVault credential isn't authorized for this
        deployment's own API yet (a per-deployment access grant, separate
        from the central account connection).
      </Alert>
    )
  }
  return <Alert severity="warning" sx={{ mt: 1 }}>{error || 'Unavailable'}</Alert>
}

export default function ClientDetail() {
  const { selectedClient } = useSelectedClient()
  const [hoursBack, setHoursBack] = useState(24)
  const [detail, setDetail] = useState<DetailResponse | null>(null)
  const [loading, setLoading] = useState(false)

  // Clears stale data the instant the selected client (or range) changes,
  // and ignores any in-flight response that resolves after a newer
  // selection has already superseded it -- real bug, live 2026-08-15:
  // switching clients kept the PREVIOUS client's numbers on screen (under
  // the NEWLY selected client's title) until the new fetch resolved, and
  // a slow response for an old selection could still clobber a faster one
  // for whatever was clicked next. Both are guarded against below rather
  // than showing wrong data under a mismatched heading.
  useEffect(() => {
    if (!selectedClient) {
      setDetail(null)
      return
    }
    let cancelled = false
    setDetail(null)
    setLoading(true)
    clientsApi.getDetail(selectedClient.name, hoursBack)
      .then(res => { if (!cancelled) setDetail(res.data) })
      .catch(err => {
        console.error('Failed to load client detail:', err)
        if (!cancelled) setDetail(null)
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [selectedClient, hoursBack])

  if (!selectedClient) return null

  return (
    <Paper variant="outlined" sx={{ p: 2.5, mb: 3 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h6" sx={{ fontWeight: 700 }}>{selectedClient.name}</Typography>
        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel id="client-detail-range-label">Time range</InputLabel>
          <Select
            labelId="client-detail-range-label"
            label="Time range"
            value={hoursBack}
            onChange={e => setHoursBack(Number(e.target.value))}
          >
            {RANGE_OPTIONS.map(opt => (
              <MenuItem key={opt.hours} value={opt.hours}>{opt.label}</MenuItem>
            ))}
          </Select>
        </FormControl>
      </Box>

      {loading && !detail && (
        <Box display="flex" justifyContent="center" py={4}><CircularProgress size={24} /></Box>
      )}

      {detail && (
        <Grid container spacing={2}>
          {detail.edr && (
            <Grid item xs={12} md={selectedClient.has_siem ? 6 : 12}>
              <Box display="flex" alignItems="center" gap={1} mb={1}>
                <EdrIcon fontSize="small" color="primary" />
                <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>EDR -- SentinelOne</Typography>
              </Box>
              {detail.edr.kind === 'found' ? (
                <Grid container spacing={1.5}>
                  <Grid item xs={6}>
                    <StatCard title="Endpoints" value={detail.edr.endpoint_count} icon={<EdrIcon />} />
                  </Grid>
                  <Grid item xs={6}>
                    <StatCard title="Offline" value={detail.edr.agents_offline} icon={<EdrIcon />} />
                  </Grid>
                  <Grid item xs={12}>
                    <Typography variant="caption" color="text.secondary">
                      Groups: {detail.edr.groups.length ? detail.edr.groups.join(', ') : '—'}
                    </Typography>
                  </Grid>
                </Grid>
              ) : (
                <UnavailableNote kind={detail.edr.kind} error={detail.edr.error} />
              )}
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
                Alert/vulnerability totals shown elsewhere on this dashboard are tenant-wide, not scoped to this client yet.
              </Typography>
            </Grid>
          )}

          {detail.siem && (
            <Grid item xs={12} md={selectedClient.has_edr ? 6 : 12}>
              <Box display="flex" alignItems="center" gap={1} mb={1}>
                <SiemIcon fontSize="small" sx={{ color: '#8B5CF6' }} />
                <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>SIEM -- AlienVault Central</Typography>
              </Box>
              {detail.siem.alarms.kind === 'found' ? (
                <Grid container spacing={1.5}>
                  <Grid item xs={6}>
                    <StatCard title="Alarms" value={detail.siem.alarms.total} icon={<SiemIcon />} color="#8B5CF6" />
                  </Grid>
                  <Grid item xs={6}>
                    <StatCard
                      title="Events"
                      value={detail.siem.events.kind === 'found' ? detail.siem.events.total : '—'}
                      icon={<SiemIcon />}
                      color="#8B5CF6"
                    />
                  </Grid>
                  <Grid item xs={12}>
                    {Object.entries(detail.siem.alarms.by_priority).map(([priority, count]) => (
                      <Chip key={priority} size="small" label={`${priority}: ${count}`} sx={{ mr: 0.5, mb: 0.5 }} />
                    ))}
                  </Grid>
                </Grid>
              ) : (
                <UnavailableNote kind={detail.siem.alarms.kind} error={detail.siem.alarms.error} />
              )}
            </Grid>
          )}
        </Grid>
      )}
    </Paper>
  )
}
