import { useState, useEffect } from 'react'
import {
  Box,
  Typography,
  Tabs,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TablePagination,
  Paper,
  Chip,
  CircularProgress,
  Alert,
  Tooltip,
} from '@mui/material'
import { findingsApi } from '../services/api'
import { SeverityChip } from '../components/ui'
import FindingDetailDialog from '../components/findings/FindingDetailDialog'

// Unified Priority Queue (Analyst Workbench v1, 2026-08-20). Segments
// match backend/api/findings.py::_compute_priority_and_segment()'s
// precedence order.
const SEGMENTS = [
  { key: 'needs_decision', label: 'Needs Your Decision' },
  { key: 'spot_check', label: 'Agent Handled -- Spot Check' },
  { key: 'in_progress', label: 'In Progress' },
  { key: 'multi_tenant_pattern', label: 'Multi-Tenant Pattern' },
] as const

type SegmentKey = typeof SEGMENTS[number]['key']

interface QueueRow {
  finding_id: string
  severity?: string
  entity_context?: { hostnames?: string[] }
  client_display_name?: string | null
  reasoning?: string
  confidence_score?: number
  priority_score: number
  segment: SegmentKey
  linked_case_id?: string | null
  sla_breached?: boolean
  sla_resolution_due?: string | null
}

function formatSlaCountdown(row: QueueRow): { label: string; color: 'error' | 'warning' | 'default' } | null {
  if (!row.linked_case_id) return null
  if (row.sla_breached) return { label: 'SLA breached', color: 'error' }
  if (!row.sla_resolution_due) return { label: 'No SLA', color: 'default' }
  const dueMs = new Date(row.sla_resolution_due).getTime() - Date.now()
  if (dueMs <= 0) return { label: 'SLA breached', color: 'error' }
  const hours = Math.round(dueMs / 3_600_000)
  if (hours <= 2) return { label: `Due in ${hours}h`, color: 'warning' }
  if (hours < 48) return { label: `Due in ${hours}h`, color: 'default' }
  return { label: `Due in ${Math.round(hours / 24)}d`, color: 'default' }
}

export default function Workbench() {
  const [tabValue, setTabValue] = useState(0)
  const [rows, setRows] = useState<QueueRow[]>([])
  const [total, setTotal] = useState(0)
  const [segmentCounts, setSegmentCounts] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(25)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(null)

  const activeSegment = SEGMENTS[tabValue].key

  const loadQueue = async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await findingsApi.getQueue({
        segment: activeSegment,
        offset: page * rowsPerPage,
        limit: rowsPerPage,
      })
      setRows(response.data.findings || [])
      setTotal(response.data.total || 0)
      setSegmentCounts(response.data.segment_counts || {})
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load the priority queue')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadQueue() }, [tabValue, page, rowsPerPage])

  const handleTabChange = (_: React.SyntheticEvent, newValue: number) => {
    setTabValue(newValue)
    setPage(0)
  }

  const handleRowClick = (findingId: string) => {
    setSelectedFindingId(findingId)
    setDialogOpen(true)
  }

  return (
    <Box>
      <Box display="flex" alignItems="center" justifyContent="space-between" mb={2}>
        <Box>
          <Typography variant="h5" fontWeight={600}>Workbench</Typography>
          <Typography variant="body2" color="text.secondary">
            The agent's draft, prioritized -- not the raw findings feed.
          </Typography>
        </Box>
      </Box>

      <Tabs value={tabValue} onChange={handleTabChange} sx={{ mb: 2 }}>
        {SEGMENTS.map((s, i) => (
          <Tab
            key={s.key}
            label={
              <Box display="flex" alignItems="center" gap={0.75}>
                {s.label}
                <Chip
                  label={segmentCounts[s.key] ?? 0}
                  size="small"
                  color={tabValue === i ? 'primary' : 'default'}
                  sx={{ height: 18, fontSize: '0.7rem' }}
                />
              </Box>
            }
          />
        ))}
      </Tabs>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <Paper variant="outlined">
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Client</TableCell>
                <TableCell>Asset</TableCell>
                <TableCell>Agent Summary</TableCell>
                <TableCell>Severity</TableCell>
                <TableCell align="right">Confidence</TableCell>
                <TableCell align="right">Priority</TableCell>
                <TableCell>SLA</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={7} align="center" sx={{ py: 4 }}>
                    <CircularProgress size={24} />
                  </TableCell>
                </TableRow>
              ) : rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} align="center" sx={{ py: 4 }}>
                    <Typography variant="body2" color="text.secondary">
                      Nothing in this queue right now.
                    </Typography>
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((row) => {
                  const sla = formatSlaCountdown(row)
                  const hostname = row.entity_context?.hostnames?.[0] || 'unknown'
                  return (
                    <TableRow
                      key={row.finding_id}
                      hover
                      onClick={() => handleRowClick(row.finding_id)}
                      sx={{ cursor: 'pointer' }}
                    >
                      <TableCell>{row.client_display_name || '—'}</TableCell>
                      <TableCell>{hostname}</TableCell>
                      <TableCell sx={{ maxWidth: 420 }}>
                        <Tooltip title={row.reasoning || ''}>
                          <Typography variant="body2" noWrap>
                            {row.reasoning ? row.reasoning.slice(0, 140) : 'No agent summary yet'}
                          </Typography>
                        </Tooltip>
                      </TableCell>
                      <TableCell>
                        <SeverityChip severity={row.severity || 'low'} />
                      </TableCell>
                      <TableCell align="right">
                        {row.confidence_score != null ? `${Math.round(row.confidence_score * 100)}%` : '—'}
                      </TableCell>
                      <TableCell align="right">{row.priority_score}</TableCell>
                      <TableCell>
                        {sla ? <Chip label={sla.label} size="small" color={sla.color} /> : '—'}
                      </TableCell>
                    </TableRow>
                  )
                })
              )}
            </TableBody>
          </Table>
        </TableContainer>
        <TablePagination
          rowsPerPageOptions={[10, 25, 50]}
          component="div"
          count={total}
          rowsPerPage={rowsPerPage}
          page={page}
          onPageChange={(_, p) => setPage(p)}
          onRowsPerPageChange={(e) => { setRowsPerPage(parseInt(e.target.value, 10)); setPage(0) }}
        />
      </Paper>

      <FindingDetailDialog
        open={dialogOpen}
        onClose={() => { setDialogOpen(false); setSelectedFindingId(null) }}
        findingId={selectedFindingId}
        onUpdate={loadQueue}
      />
    </Box>
  )
}
