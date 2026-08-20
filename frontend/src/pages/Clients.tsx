import { useEffect, useState } from 'react'
import {
  Box,
  Typography,
  IconButton,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  Paper,
  Grid,
  Tooltip,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Snackbar,
} from '@mui/material'
import {
  RefreshOutlined as RefreshIcon,
  SecurityOutlined as EdrIcon,
  VisibilityOutlined as SiemIcon,
  BusinessOutlined as ClientsIcon,
  LinkOutlined as LinkIcon,
  LinkOffOutlined as UnlinkIcon,
} from '@mui/icons-material'
import { clientsApi } from '../services/api'
import { StatCard } from '../components/ui'

interface ClientRecord {
  name: string
  has_edr: boolean
  has_siem: boolean
  s1_site_name: string | null
  av_deployment_name: string | null
  match_confidence: string | null
}

interface ClientRegistrySnapshot {
  generated_at: string
  clients: ClientRecord[]
  edr_only: number
  siem_only: number
  both: number
  total: number
  sentinelone_active: boolean
  alienvault_configured: boolean
  error: string | null
}

const PLATFORM_COLORS = {
  both: '#22C55E',
  edr: '#3B82F6',
  siem: '#8B5CF6',
}

function PlatformChip({ client }: { client: ClientRecord }) {
  if (client.has_edr && client.has_siem) {
    return <Chip size="small" label="EDR + SIEM" sx={{ bgcolor: `${PLATFORM_COLORS.both}22`, color: PLATFORM_COLORS.both, fontWeight: 600 }} />
  }
  if (client.has_edr) {
    return <Chip size="small" label="EDR only" sx={{ bgcolor: `${PLATFORM_COLORS.edr}22`, color: PLATFORM_COLORS.edr, fontWeight: 600 }} />
  }
  return <Chip size="small" label="SIEM only" sx={{ bgcolor: `${PLATFORM_COLORS.siem}22`, color: PLATFORM_COLORS.siem, fontWeight: 600 }} />
}

export default function Clients() {
  const [snapshot, setSnapshot] = useState<ClientRegistrySnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshKey, setRefreshKey] = useState(0)
  const [linkTarget, setLinkTarget] = useState<ClientRecord | null>(null)
  const [linkChoice, setLinkChoice] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' }>({
    open: false, message: '', severity: 'success',
  })

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    clientsApi.getAll()
      .then(res => { if (!cancelled) setSnapshot(res.data) })
      .catch(err => console.error('Failed to load client registry:', err))
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [refreshKey])

  const clients = snapshot?.clients || []
  // Candidates for linking: single-platform, unmatched rows on the
  // *other* side from whichever row the dialog was opened for.
  const unmatchedS1 = clients.filter(c => c.has_edr && !c.has_siem)
  const unmatchedAv = clients.filter(c => c.has_siem && !c.has_edr)

  const openLinkDialog = (client: ClientRecord) => {
    setLinkTarget(client)
    setLinkChoice('')
  }

  const closeLinkDialog = () => {
    setLinkTarget(null)
    setLinkChoice('')
  }

  const confirmLink = async () => {
    if (!linkTarget || !linkChoice) return
    const s1Name = linkTarget.has_edr ? linkTarget.s1_site_name! : linkChoice
    const avName = linkTarget.has_edr ? linkChoice : linkTarget.av_deployment_name!
    setSubmitting(true)
    try {
      const res = await clientsApi.createOverride(s1Name, avName)
      setSnapshot(res.data)
      setSnackbar({ open: true, message: `Linked "${s1Name}" to "${avName}"`, severity: 'success' })
      closeLinkDialog()
    } catch (err) {
      console.error('Failed to create override:', err)
      setSnackbar({ open: true, message: 'Failed to save link', severity: 'error' })
    } finally {
      setSubmitting(false)
    }
  }

  const unlink = async (client: ClientRecord) => {
    if (!client.s1_site_name) return
    setSubmitting(true)
    try {
      const res = await clientsApi.deleteOverride(client.s1_site_name)
      setSnapshot(res.data)
      setSnackbar({ open: true, message: `Unlinked "${client.name}"`, severity: 'success' })
    } catch (err) {
      console.error('Failed to remove override:', err)
      setSnackbar({ open: true, message: 'Failed to remove link', severity: 'error' })
    } finally {
      setSubmitting(false)
    }
  }

  // The dialog links whichever single platform this row already has to
  // an unmatched entry on the other side -- so the candidate list is
  // the *other* platform's unmatched rows.
  const linkCandidates = linkTarget?.has_edr ? unmatchedAv : unmatchedS1

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 700, mb: 0.5 }}>Clients</Typography>
          <Typography variant="body2" color="text.secondary">
            EDR (SentinelOne) and SIEM (AlienVault Central) coverage, auto-detected per client
          </Typography>
        </Box>
        <Tooltip title="Refresh">
          <IconButton onClick={() => setRefreshKey(k => k + 1)}>
            <RefreshIcon />
          </IconButton>
        </Tooltip>
      </Box>

      {snapshot?.error && (
        <Alert severity="warning" sx={{ mb: 2 }}>{snapshot.error}</Alert>
      )}
      {snapshot && !snapshot.sentinelone_active && (
        <Alert severity="info" sx={{ mb: 2 }}>SentinelOne is not connected -- EDR coverage cannot be detected right now.</Alert>
      )}
      {snapshot && !snapshot.alienvault_configured && (
        <Alert severity="info" sx={{ mb: 2 }}>AlienVault Central is not configured -- SIEM coverage cannot be detected right now (Settings -&gt; Integrations).</Alert>
      )}

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard title="Total Clients" value={snapshot?.total ?? 0} icon={<ClientsIcon />} />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard title="EDR + SIEM" value={snapshot?.both ?? 0} subtitle="Both platforms" icon={<ClientsIcon />} color={PLATFORM_COLORS.both} />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard title="EDR Only" value={snapshot?.edr_only ?? 0} subtitle="SentinelOne, no AlienVault" icon={<EdrIcon />} color={PLATFORM_COLORS.edr} />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard title="SIEM Only" value={snapshot?.siem_only ?? 0} subtitle="AlienVault, no SentinelOne" icon={<SiemIcon />} color={PLATFORM_COLORS.siem} />
        </Grid>
      </Grid>

      <TableContainer component={Paper} variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Client</TableCell>
              <TableCell>Coverage</TableCell>
              <TableCell>SentinelOne Site</TableCell>
              <TableCell>AlienVault Deployment</TableCell>
              <TableCell>Match</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {!loading && clients.length === 0 && (
              <TableRow>
                <TableCell colSpan={6}>
                  <Typography variant="body2" color="text.secondary" sx={{ py: 2, textAlign: 'center' }}>
                    No clients detected yet.
                  </Typography>
                </TableCell>
              </TableRow>
            )}
            {clients.map(client => {
              const isUnmatchedSingle = client.match_confidence === null && (client.has_edr !== client.has_siem)
              const isManual = client.match_confidence === 'manual'
              return (
                <TableRow key={client.name} hover>
                  <TableCell sx={{ fontWeight: 500 }}>{client.name}</TableCell>
                  <TableCell><PlatformChip client={client} /></TableCell>
                  <TableCell>{client.s1_site_name || '—'}</TableCell>
                  <TableCell>{client.av_deployment_name || '—'}</TableCell>
                  <TableCell>
                    {client.match_confidence
                      ? <Chip size="small" variant="outlined" label={client.match_confidence} />
                      : '—'}
                  </TableCell>
                  <TableCell align="right">
                    {isUnmatchedSingle && (
                      <Tooltip title="Link to the same client on the other platform">
                        <IconButton size="small" onClick={() => openLinkDialog(client)} disabled={submitting}>
                          <LinkIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    )}
                    {isManual && (
                      <Tooltip title="Remove this manual link">
                        <IconButton size="small" onClick={() => unlink(client)} disabled={submitting}>
                          <UnlinkIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </TableContainer>

      <Dialog open={!!linkTarget} onClose={closeLinkDialog} maxWidth="sm" fullWidth>
        <DialogTitle>Link "{linkTarget?.name}" to its {linkTarget?.has_edr ? 'AlienVault deployment' : 'SentinelOne site'}</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Pick the matching entry on the other platform. This overrides automatic name-matching for this client going forward.
          </Typography>
          <FormControl fullWidth size="small">
            <InputLabel id="link-choice-label">{linkTarget?.has_edr ? 'AlienVault deployment' : 'SentinelOne site'}</InputLabel>
            <Select
              labelId="link-choice-label"
              value={linkChoice}
              label={linkTarget?.has_edr ? 'AlienVault deployment' : 'SentinelOne site'}
              onChange={e => setLinkChoice(e.target.value)}
            >
              {linkCandidates.length === 0 && (
                <MenuItem value="" disabled>No unmatched candidates available</MenuItem>
              )}
              {linkCandidates.map(c => (
                <MenuItem key={c.name} value={linkTarget?.has_edr ? c.av_deployment_name! : c.s1_site_name!}>
                  {c.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </DialogContent>
        <DialogActions>
          <Button onClick={closeLinkDialog}>Cancel</Button>
          <Button variant="contained" onClick={confirmLink} disabled={!linkChoice || submitting}>Link</Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={snackbar.open}
        autoHideDuration={4000}
        onClose={() => setSnackbar(s => ({ ...s, open: false }))}
        message={snackbar.message}
      />
    </Box>
  )
}
