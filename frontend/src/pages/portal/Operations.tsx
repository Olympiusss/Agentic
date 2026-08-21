import { useState, useEffect } from 'react'
import {
  Box,
  Typography,
  Tabs,
  Tab,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  CircularProgress,
  Alert,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Grid,
} from '@mui/material'
import { portalApi } from '../../services/api'

const TABS = ['Action Ledger', 'Pending Approvals', 'Decisions Declined', 'Performance Scorecard'] as const

interface LedgerEntry {
  decision_id: string
  agent_id: string
  reasoning: string
  recommended_action: string
  confidence_score: number
  autonomy_tier: string
  timestamp: string
  finding_id: string
  severity?: string
}

export default function PortalOperations() {
  const [tab, setTab] = useState(0)
  const [ledger, setLedger] = useState<LedgerEntry[]>([])
  const [declined, setDeclined] = useState<LedgerEntry[]>([])
  const [approvals, setApprovals] = useState<any[]>([])
  const [scorecard, setScorecard] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [rejectDialog, setRejectDialog] = useState<{ open: boolean; actionId: string | null }>({ open: false, actionId: null })
  const [rejectReason, setRejectReason] = useState('')
  const [acting, setActing] = useState<string | null>(null)

  const loadAll = async () => {
    setLoading(true)
    setError(null)
    try {
      const [ledgerRes, declinedRes, approvalsRes, scorecardRes] = await Promise.all([
        portalApi.getActionLedger(),
        portalApi.getActionLedger({ segment: 'declined' }),
        portalApi.getApprovals(),
        portalApi.getScorecard(),
      ])
      setLedger(ledgerRes.data.entries || [])
      setDeclined(declinedRes.data.entries || [])
      setApprovals(approvalsRes.data.actions || [])
      setScorecard(scorecardRes.data)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load Agentic Operations data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadAll() }, [])

  const handleApprove = async (actionId: string) => {
    setActing(actionId)
    try {
      await portalApi.approveAction(actionId)
      await loadAll()
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to approve')
    } finally {
      setActing(null)
    }
  }

  const handleReject = async () => {
    if (!rejectDialog.actionId || !rejectReason.trim()) return
    setActing(rejectDialog.actionId)
    try {
      await portalApi.rejectAction(rejectDialog.actionId, rejectReason)
      setRejectDialog({ open: false, actionId: null })
      setRejectReason('')
      await loadAll()
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to reject')
    } finally {
      setActing(null)
    }
  }

  const renderLedgerTable = (rows: LedgerEntry[], emptyLabel: string) => (
    <TableContainer component={Paper} variant="outlined">
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Timestamp</TableCell>
            <TableCell>Finding</TableCell>
            <TableCell>Autonomy Tier</TableCell>
            <TableCell>Confidence</TableCell>
            <TableCell>Reasoning</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={5} align="center" sx={{ py: 3 }}>
                <Typography variant="body2" color="text.secondary">{emptyLabel}</Typography>
              </TableCell>
            </TableRow>
          ) : (
            rows.map((r) => (
              <TableRow key={r.decision_id}>
                <TableCell>{new Date(r.timestamp).toLocaleString()}</TableCell>
                <TableCell>{r.finding_id}</TableCell>
                <TableCell><Chip label={r.autonomy_tier} size="small" /></TableCell>
                <TableCell>{Math.round((r.confidence_score || 0) * 100)}%</TableCell>
                <TableCell sx={{ maxWidth: 400 }}>
                  <Typography variant="body2" noWrap title={r.reasoning}>{r.reasoning}</Typography>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </TableContainer>
  )

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" py={6}>
        <CircularProgress />
      </Box>
    )
  }

  return (
    <Box>
      <Typography variant="h5" fontWeight={700} sx={{ mb: 2 }}>Agentic Operations Center</Typography>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        {TABS.map((label, i) => (
          <Tab key={label} label={i === 1 ? `${label} (${approvals.length})` : label} />
        ))}
      </Tabs>

      {tab === 0 && renderLedgerTable(ledger, 'No agent activity yet.')}

      {tab === 1 && (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Age</TableCell>
                <TableCell>Action</TableCell>
                <TableCell>Target</TableCell>
                <TableCell>Reason</TableCell>
                <TableCell align="right">Confidence</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {approvals.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} align="center" sx={{ py: 3 }}>
                    <Typography variant="body2" color="text.secondary">Nothing awaiting your approval.</Typography>
                  </TableCell>
                </TableRow>
              ) : (
                approvals.map((a) => (
                  <TableRow key={a.action_id}>
                    <TableCell>{new Date(a.created_at).toLocaleString()}</TableCell>
                    <TableCell>{a.action_type}</TableCell>
                    <TableCell>{a.target}</TableCell>
                    <TableCell sx={{ maxWidth: 300 }}>
                      <Typography variant="body2" noWrap title={a.reason}>{a.reason}</Typography>
                    </TableCell>
                    <TableCell align="right">{Math.round((a.confidence || 0) * 100)}%</TableCell>
                    <TableCell align="right">
                      <Button
                        size="small"
                        color="success"
                        disabled={acting === a.action_id}
                        onClick={() => handleApprove(a.action_id)}
                      >
                        Approve
                      </Button>
                      <Button
                        size="small"
                        color="error"
                        disabled={acting === a.action_id}
                        onClick={() => setRejectDialog({ open: true, actionId: a.action_id })}
                      >
                        Deny
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {tab === 2 && (
        <Box>
          <Alert severity="info" sx={{ mb: 2 }}>
            Findings the agent evaluated and chose not to act on -- surfaced deliberately, not hidden.
          </Alert>
          {renderLedgerTable(declined, 'No declined decisions in this window.')}
        </Box>
      )}

      {tab === 3 && scorecard && (
        <Grid container spacing={2}>
          <Grid item xs={12} sm={6} md={3}>
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="caption" color="text.secondary">Total Decisions</Typography>
              <Typography variant="h5">{scorecard.total_decisions}</Typography>
            </Paper>
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="caption" color="text.secondary">
                Human Overturn Rate {scorecard.graded_count ? `(${scorecard.graded_count} graded)` : ''}
              </Typography>
              <Typography variant="h5">
                {scorecard.human_overturn_rate != null ? `${Math.round(scorecard.human_overturn_rate * 100)}%` : 'Not enough data'}
              </Typography>
            </Paper>
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="caption" color="text.secondary">Avg. Accuracy Grade</Typography>
              <Typography variant="h5">{scorecard.avg_accuracy_grade ?? 'Not enough data'}</Typography>
            </Paper>
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="caption" color="text.secondary">Avg. Time Saved / Decision</Typography>
              <Typography variant="h5">
                {scorecard.avg_time_saved_minutes != null ? `${scorecard.avg_time_saved_minutes}m` : 'Not enough data'}
              </Typography>
            </Paper>
          </Grid>
        </Grid>
      )}

      <Dialog open={rejectDialog.open} onClose={() => setRejectDialog({ open: false, actionId: null })}>
        <DialogTitle>Deny Action</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            multiline
            minRows={2}
            label="Justification (required)"
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRejectDialog({ open: false, actionId: null })}>Cancel</Button>
          <Button
            color="error"
            variant="contained"
            disabled={!rejectReason.trim() || acting === rejectDialog.actionId}
            onClick={handleReject}
          >
            Deny
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
