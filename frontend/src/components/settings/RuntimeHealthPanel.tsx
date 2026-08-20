import { useEffect, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Grid,
  IconButton,
  Link,
  Paper,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material'
import {
  OpenInNew as OpenInNewIcon,
  Refresh as RefreshIcon,
  Timeline as TracingIcon,
} from '@mui/icons-material'
import { systemApi, type TaskStateSummary, type ObservabilityStatus, type DeadLetterRow } from '../../services/api'

// Runtime health -- state/memory management (crash-resume checkpointing,
// database/init/18_agent_task_state.sql) and observability/LLM tracing
// (core/telemetry.py), added 2026-08-20. Previously both were only
// visible via `docker logs`/direct DB query; this is the first admin-UI
// surface for either.

function formatTimestamp(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

export default function RuntimeHealthPanel() {
  const [taskState, setTaskState] = useState<TaskStateSummary | null>(null)
  const [observability, setObservability] = useState<ObservabilityStatus | null>(null)
  const [deadLetters, setDeadLetters] = useState<DeadLetterRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchAll = async () => {
    setLoading(true)
    setError(null)
    try {
      const [taskStateRes, obsRes, dlRes] = await Promise.all([
        systemApi.getTaskStateSummary(),
        systemApi.getObservabilityStatus(),
        systemApi.getDeadLetters({ limit: 25 }),
      ])
      setTaskState(taskStateRes.data)
      setObservability(obsRes.data)
      setDeadLetters(dlRes.data)
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'Failed to load runtime health')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchAll()
  }, [])

  const host = typeof window !== 'undefined' ? window.location.hostname : 'localhost'

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Box>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>Runtime Health</Typography>
          <Typography variant="body2" color="text.secondary">
            Crash-resume state and LLM/agent tracing — what the daemon is doing under the hood.
          </Typography>
        </Box>
        <IconButton onClick={fetchAll} size="small" disabled={loading}>
          <RefreshIcon />
        </IconButton>
      </Box>

      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}

      {/* --- State & memory management: agent_task_state --- */}
      <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
        State & Memory Management
      </Typography>
      <Grid container spacing={2} sx={{ mb: 2 }}>
        {[
          { key: 'pending', label: 'Pending' },
          { key: 'in_progress', label: 'In Progress' },
          { key: 'completed', label: 'Completed' },
          { key: 'failed', label: 'Failed' },
        ].map((tile) => (
          <Grid item xs={6} sm={3} key={tile.key}>
            <Card variant="outlined">
              <CardContent sx={{ textAlign: 'center', py: 1.5 }}>
                <Typography variant="h5" sx={{ fontWeight: 700 }}>
                  {loading && !taskState ? <Skeleton width={40} sx={{ mx: 'auto' }} /> : (taskState?.counts as any)?.[tile.key] ?? 0}
                </Typography>
                <Typography variant="caption" color="text.secondary">{tile.label}</Typography>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>

      <Paper variant="outlined" sx={{ mb: 3 }}>
        <Box sx={{ p: 1.5, pb: 0 }}>
          <Typography variant="body2" sx={{ fontWeight: 600 }}>
            Currently in progress ({taskState?.stuck.length ?? 0})
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Findings the daemon is actively processing, or was mid-processing when it last restarted —
            these are automatically re-queued and reprocessed on daemon startup, not lost.
          </Typography>
        </Box>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Finding</TableCell>
                <TableCell>Stage</TableCell>
                <TableCell align="right">Attempts</TableCell>
                <TableCell>Updated</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(taskState?.stuck || []).map((row) => (
                <TableRow key={row.finding_id} hover>
                  <TableCell sx={{ fontFamily: 'monospace', fontSize: '0.78rem' }}>{row.finding_id}</TableCell>
                  <TableCell>{row.stage || '—'}</TableCell>
                  <TableCell align="right">{row.attempts}</TableCell>
                  <TableCell>{formatTimestamp(row.updated_at)}</TableCell>
                </TableRow>
              ))}
              {(!taskState || taskState.stuck.length === 0) && !loading && (
                <TableRow><TableCell colSpan={4} align="center"><Typography color="text.secondary" sx={{ py: 1.5 }}>Nothing in progress right now.</Typography></TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      <Paper variant="outlined" sx={{ mb: 3 }}>
        <Box sx={{ p: 1.5, pb: 0 }}>
          <Typography variant="body2" sx={{ fontWeight: 600 }}>
            Recently failed ({taskState?.recent_failed.length ?? 0})
          </Typography>
        </Box>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Finding</TableCell>
                <TableCell>Stage reached</TableCell>
                <TableCell>Error</TableCell>
                <TableCell>Updated</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(taskState?.recent_failed || []).map((row) => (
                <TableRow key={row.finding_id} hover>
                  <TableCell sx={{ fontFamily: 'monospace', fontSize: '0.78rem' }}>{row.finding_id}</TableCell>
                  <TableCell>{row.stage || '—'}</TableCell>
                  <TableCell sx={{ maxWidth: 320, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    <Tooltip title={row.last_error || ''}><span>{row.last_error || '—'}</span></Tooltip>
                  </TableCell>
                  <TableCell>{formatTimestamp(row.updated_at)}</TableCell>
                </TableRow>
              ))}
              {(!taskState || taskState.recent_failed.length === 0) && !loading && (
                <TableRow><TableCell colSpan={4} align="center"><Typography color="text.secondary" sx={{ py: 1.5 }}>No recent failures.</Typography></TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      {/* --- Observability & LLM tracing --- */}
      <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
        Observability & LLM Tracing
      </Typography>
      <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
        {loading && !observability ? (
          <Skeleton height={40} />
        ) : (
          <>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 1.5 }}>
              <TracingIcon color={observability?.otel_enabled ? 'success' : 'disabled'} />
              <Chip
                size="small"
                color={observability?.otel_enabled ? 'success' : 'default'}
                label={observability?.otel_enabled ? 'Tracing active' : 'Tracing not enabled'}
              />
              <Typography variant="body2" color="text.secondary">{observability?.note}</Typography>
            </Box>
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
              <Button
                size="small"
                variant="outlined"
                endIcon={<OpenInNewIcon sx={{ fontSize: 14 }} />}
                component={Link}
                href={`http://${host}:${observability?.jaeger_port ?? 16686}`}
                target="_blank"
                rel="noopener"
              >
                Open Jaeger (traces)
              </Button>
              <Button
                size="small"
                variant="outlined"
                endIcon={<OpenInNewIcon sx={{ fontSize: 14 }} />}
                component={Link}
                href={`http://${host}:${observability?.grafana_port ?? 3001}`}
                target="_blank"
                rel="noopener"
              >
                Open Grafana (dashboards)
              </Button>
              <Button
                size="small"
                variant="outlined"
                endIcon={<OpenInNewIcon sx={{ fontSize: 14 }} />}
                component={Link}
                href={`http://${host}:${observability?.prometheus_port ?? 9095}`}
                target="_blank"
                rel="noopener"
              >
                Open Prometheus (metrics)
              </Button>
            </Box>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.5 }}>
              These links only resolve if the observability containers are running
              (<code>docker compose --profile observability up -d</code>) and reachable from your browser.
            </Typography>
          </>
        )}
      </Paper>

      {/* --- Background LLM job failures --- */}
      <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
        Background LLM Job Failures
      </Typography>
      <Paper variant="outlined">
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Function</TableCell>
                <TableCell>Agent</TableCell>
                <TableCell align="right">Attempts</TableCell>
                <TableCell>Error</TableCell>
                <TableCell>Failed at</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {deadLetters.map((row) => (
                <TableRow key={row.id} hover>
                  <TableCell sx={{ fontFamily: 'monospace', fontSize: '0.78rem' }}>{row.function_name}</TableCell>
                  <TableCell>{row.agent_id || '—'}</TableCell>
                  <TableCell align="right">{row.attempts}</TableCell>
                  <TableCell sx={{ maxWidth: 320, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    <Tooltip title={row.error}><span>{row.error}</span></Tooltip>
                  </TableCell>
                  <TableCell>{formatTimestamp(row.failed_at)}</TableCell>
                </TableRow>
              ))}
              {deadLetters.length === 0 && !loading && (
                <TableRow><TableCell colSpan={5} align="center"><Typography color="text.secondary" sx={{ py: 1.5 }}>No exhausted-retry LLM jobs on record.</Typography></TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>
    </Box>
  )
}
