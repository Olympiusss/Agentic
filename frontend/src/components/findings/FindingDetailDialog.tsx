import { useState, useEffect } from 'react'
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Select,
  MenuItem,
  FormControl,
  Grid,
  Typography,
  Chip,
  Box,
  Divider,
  IconButton,
  Snackbar,
  Alert,
  CircularProgress,
  Paper,
  List,
  ListItem,
  ListItemText,
  Accordion,
  AccordionSummary,
  AccordionDetails,
} from '@mui/material'
import {
  Close as CloseIcon,
  Save as SaveIcon,
  Psychology as AiIcon,
  ExpandMore as ExpandMoreIcon,
  CheckCircle as CheckCircleIcon,
  Warning as WarningIcon,
  Info as InfoIcon,
  Timeline as TimelineIcon,
  Security as SecurityIcon,
  ThumbUp as ApproveIcon,
  EditNote as ModifyIcon,
  Flag as OverrideIcon,
  TrendingUp as EscalateIcon,
} from '@mui/icons-material'
import { findingsApi, timelineApi, aiDecisionsApi, DECISION_REASON_CODES } from '../../services/api'
import { useAuth } from '../../contexts/AuthContext'
import EventTimeline from '../timeline/EventTimeline'
import EventVisualizationDialog from '../timeline/EventVisualizationDialog'
import NetworkContextPanel from './NetworkContextPanel'
import { VStrikeEnrichment } from '../../types/vstrike'

type DecisionActionType = 'approve' | 'modify' | 'override' | 'escalate'

interface FindingDetailDialogProps {
  open: boolean
  onClose: () => void
  findingId: string | null
  onUpdate?: () => void
}

export default function FindingDetailDialog({
  open,
  onClose,
  findingId,
  onUpdate,
}: FindingDetailDialogProps) {
  const [loading, setLoading] = useState(false)
  const [editing, setEditing] = useState(false)
  const [finding, setFinding] = useState<any>(null)
  const [editedFinding, setEditedFinding] = useState<any>(null)
  const [enrichment, setEnrichment] = useState<any>(null)
  const [enrichmentLoading, setEnrichmentLoading] = useState(false)
  const [enrichmentError, setEnrichmentError] = useState<string | null>(null)
  const [timelineEvents, setTimelineEvents] = useState<any[]>([])
  const [timelineLoading, setTimelineLoading] = useState(false)
  const [eventVizDialogOpen, setEventVizDialogOpen] = useState(false)
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' }>({
    open: false,
    message: '',
    severity: 'success',
  })

  // Decision Panel (unified-schema foundation, Phase 2, 2026-08-20):
  // approve/modify/override/escalate on this finding's most recent AI
  // decision (typically the synergy pipeline's "zeus_pipeline" verdict).
  const { user } = useAuth()
  const [decisions, setDecisions] = useState<any[]>([])
  const [decisionsLoading, setDecisionsLoading] = useState(false)
  const [actionDialogOpen, setActionDialogOpen] = useState(false)
  const [pendingAction, setPendingAction] = useState<DecisionActionType | null>(null)
  const [reasonCode, setReasonCode] = useState('')
  const [actionComment, setActionComment] = useState('')
  const [escalateTo, setEscalateTo] = useState('')
  const [submittingAction, setSubmittingAction] = useState(false)

  useEffect(() => {
    if (open && findingId) {
      loadFinding()
      loadEnrichment()
      loadTimeline()
      loadDecisions()
    }
  }, [open, findingId])

  const loadDecisions = async () => {
    if (!findingId) return
    setDecisionsLoading(true)
    try {
      const response = await aiDecisionsApi.list({ finding_id: findingId, limit: 10 })
      setDecisions(response.data || [])
    } catch (error) {
      console.error('Failed to load AI decisions:', error)
    } finally {
      setDecisionsLoading(false)
    }
  }

  // Most recent decision for this finding -- the one the Decision Panel
  // acts on. Findings processed through capabilities/synergy.py will
  // have one logged under agent_id "zeus_pipeline".
  const latestDecision = decisions.length > 0
    ? [...decisions].sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())[0]
    : null

  const openActionDialog = (action: DecisionActionType) => {
    setPendingAction(action)
    setReasonCode('')
    setActionComment('')
    setEscalateTo('')
    setActionDialogOpen(true)
  }

  const handleApprove = async () => {
    if (!latestDecision) return
    setSubmittingAction(true)
    try {
      await aiDecisionsApi.submitAction(latestDecision.decision_id, {
        decision_action: 'approve',
        reviewer: user?.username || user?.full_name || 'analyst',
      })
      setSnackbar({ open: true, message: 'Decision approved', severity: 'success' })
      loadDecisions()
      if (onUpdate) onUpdate()
    } catch (error: any) {
      setSnackbar({
        open: true,
        message: error?.response?.data?.detail || 'Failed to approve decision',
        severity: 'error',
      })
    } finally {
      setSubmittingAction(false)
    }
  }

  const submitPendingAction = async () => {
    if (!latestDecision || !pendingAction) return
    if (pendingAction !== 'approve' && !reasonCode) return

    setSubmittingAction(true)
    try {
      let fieldsChanged: Record<string, { from: any; to: any }> | undefined
      if (pendingAction === 'modify' && editedFinding && finding) {
        fieldsChanged = {}
        for (const key of ['severity', 'status', 'description']) {
          if (editedFinding[key] !== finding[key]) {
            fieldsChanged[key] = { from: finding[key], to: editedFinding[key] }
          }
        }
        if (Object.keys(fieldsChanged).length === 0) fieldsChanged = undefined
      }

      await aiDecisionsApi.submitAction(latestDecision.decision_id, {
        decision_action: pendingAction,
        reviewer: user?.username || user?.full_name || 'analyst',
        reason_code: reasonCode || undefined,
        fields_changed: fieldsChanged,
        comment: actionComment || undefined,
        escalate_to: pendingAction === 'escalate' ? (escalateTo || undefined) : undefined,
      })

      setSnackbar({
        open: true,
        message: pendingAction === 'escalate' ? 'Escalated -- case created' : `Decision ${pendingAction}d`,
        severity: 'success',
      })
      setActionDialogOpen(false)
      setEditing(false)
      loadDecisions()
      loadFinding()
      if (onUpdate) onUpdate()
    } catch (error: any) {
      setSnackbar({
        open: true,
        message: error?.response?.data?.detail || `Failed to ${pendingAction} decision`,
        severity: 'error',
      })
    } finally {
      setSubmittingAction(false)
    }
  }

  const loadFinding = async () => {
    if (!findingId) return
    
    setLoading(true)
    try {
      const response = await findingsApi.getById(findingId)
      setFinding(response.data)
      setEditedFinding(response.data)
    } catch (error) {
      console.error('Failed to load finding:', error)
    } finally {
      setLoading(false)
    }
  }

  const loadEnrichment = async () => {
    if (!findingId) return
    
    setEnrichmentLoading(true)
    setEnrichmentError(null)
    try {
      const response = await findingsApi.getEnrichment(findingId)
      setEnrichment(response.data.enrichment)
      if (!response.data.cached) {
        setSnackbar({ 
          open: true, 
          message: 'AI enrichment generated successfully', 
          severity: 'success' 
        })
        if (onUpdate) onUpdate()
      }
    } catch (error: any) {
      console.error('Failed to load enrichment:', error)
      if (error?.response?.status === 503) {
        setEnrichmentError('not_configured')
      } else {
        setEnrichmentError('failed')
        setSnackbar({ 
          open: true, 
          message: 'Failed to generate AI enrichment', 
          severity: 'error' 
        })
      }
    } finally {
      setEnrichmentLoading(false)
    }
  }

  const loadTimeline = async () => {
    if (!findingId) return
    
    setTimelineLoading(true)
    try {
      const response = await timelineApi.getFindingEvents(findingId)
      setTimelineEvents(response.data.events || [])
    } catch (error: any) {
      console.error('Failed to load timeline:', error)
    } finally {
      setTimelineLoading(false)
    }
  }

  const handleEventClick = (event: any) => {
    setSelectedEventId(event.id)
    setEventVizDialogOpen(true)
  }

  const handleSave = async () => {
    if (!findingId || !editedFinding) return
    
    setLoading(true)
    try {
      await findingsApi.update(findingId, editedFinding)
      setFinding(editedFinding)
      setEditing(false)
      setSnackbar({ open: true, message: 'Finding updated successfully', severity: 'success' })
      if (onUpdate) onUpdate()
    } catch (error) {
      console.error('Failed to update finding:', error)
      setSnackbar({ open: true, message: 'Failed to update finding', severity: 'error' })
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async () => {
    if (!findingId) return
    
    if (!confirm('Are you sure you want to delete this finding?')) return
    
    setLoading(true)
    try {
      await findingsApi.delete(findingId)
      setSnackbar({ open: true, message: 'Finding deleted successfully', severity: 'success' })
      if (onUpdate) onUpdate()
      setTimeout(() => onClose(), 1000) // Close after showing success message
    } catch (error) {
      console.error('Failed to delete finding:', error)
      setSnackbar({ open: true, message: 'Failed to delete finding', severity: 'error' })
    } finally {
      setLoading(false)
    }
  }

  const getSeverityColor = (severity: string) => {
    const colors: any = {
      critical: 'error',
      high: 'error',
      medium: 'warning',
      low: 'success',
    }
    return colors[severity?.toLowerCase()] || 'default'
  }

  if (!finding && !loading) {
    return null
  }

  const displayFinding = editing ? editedFinding : finding

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>
        <Box display="flex" justifyContent="space-between" alignItems="center">
          <Typography variant="h6">Finding Details</Typography>
          <IconButton onClick={onClose} size="small">
            <CloseIcon />
          </IconButton>
        </Box>
      </DialogTitle>
      
      <DialogContent dividers>
        {loading && !finding ? (
          <Typography>Loading...</Typography>
        ) : displayFinding ? (
          <Grid container spacing={2}>
            <Grid item xs={12}>
              <Typography variant="subtitle2" color="textSecondary">
                Finding ID
              </Typography>
              <Typography variant="body1">{displayFinding.finding_id}</Typography>
            </Grid>

            <Grid item xs={12} sm={6}>
              <Typography variant="subtitle2" color="textSecondary">
                Severity
              </Typography>
              {editing ? (
                <FormControl fullWidth size="small" sx={{ mt: 1 }}>
                  <Select
                    value={editedFinding.severity || ''}
                    onChange={(e) =>
                      setEditedFinding({ ...editedFinding, severity: e.target.value })
                    }
                  >
                    <MenuItem value="low">Low</MenuItem>
                    <MenuItem value="medium">Medium</MenuItem>
                    <MenuItem value="high">High</MenuItem>
                    <MenuItem value="critical">Critical</MenuItem>
                  </Select>
                </FormControl>
              ) : (
                <Box mt={1}>
                  <Chip
                    label={displayFinding.severity || 'Unknown'}
                    color={getSeverityColor(displayFinding.severity)}
                    size="small"
                  />
                </Box>
              )}
            </Grid>

            <Grid item xs={12} sm={6}>
              <Typography variant="subtitle2" color="textSecondary">
                Data Source
              </Typography>
              {editing ? (
                <TextField
                  fullWidth
                  size="small"
                  value={editedFinding.data_source || ''}
                  onChange={(e) =>
                    setEditedFinding({ ...editedFinding, data_source: e.target.value })
                  }
                  sx={{ mt: 1 }}
                />
              ) : (
                <Typography variant="body1">
                  {displayFinding.data_source || 'N/A'}
                </Typography>
              )}
            </Grid>

            <Grid item xs={12} sm={6}>
              <Typography variant="subtitle2" color="textSecondary">
                Timestamp
              </Typography>
              <Typography variant="body1">
                {displayFinding.timestamp
                  ? new Date(displayFinding.timestamp).toLocaleString()
                  : 'N/A'}
              </Typography>
            </Grid>

            <Grid item xs={12} sm={6}>
              <Typography variant="subtitle2" color="textSecondary">
                Anomaly Score
              </Typography>
              {editing ? (
                <TextField
                  fullWidth
                  size="small"
                  type="number"
                  value={editedFinding.anomaly_score || ''}
                  onChange={(e) =>
                    setEditedFinding({
                      ...editedFinding,
                      anomaly_score: parseFloat(e.target.value),
                    })
                  }
                  sx={{ mt: 1 }}
                />
              ) : (
                <Typography variant="body1">
                  {displayFinding.anomaly_score
                    ? displayFinding.anomaly_score.toFixed(2)
                    : 'N/A'}
                </Typography>
              )}
            </Grid>

            <Grid item xs={12}>
              <Divider sx={{ my: 2 }} />
            </Grid>

            <Grid item xs={12}>
              <Typography variant="subtitle2" color="textSecondary">
                Description
              </Typography>
              {editing ? (
                <TextField
                  fullWidth
                  multiline
                  rows={4}
                  value={editedFinding.description || ''}
                  onChange={(e) =>
                    setEditedFinding({ ...editedFinding, description: e.target.value })
                  }
                  sx={{ mt: 1 }}
                />
              ) : (
                <Typography variant="body1">
                  {displayFinding.description || 'No description available'}
                </Typography>
              )}
            </Grid>

            {displayFinding.details && (
              <Grid item xs={12}>
                <Typography variant="subtitle2" color="textSecondary">
                  Additional Details
                </Typography>
                <Box
                  sx={{
                    mt: 1,
                    p: 2,
                    bgcolor: 'background.default',
                    borderRadius: 1,
                    fontFamily: 'monospace',
                    fontSize: '0.875rem',
                    overflow: 'auto',
                    maxHeight: 200,
                  }}
                >
                  <pre>{JSON.stringify(displayFinding.details, null, 2)}</pre>
                </Box>
              </Grid>
            )}

            {displayFinding.related_entities && displayFinding.related_entities.length > 0 && (
              <Grid item xs={12}>
                <Typography variant="subtitle2" color="textSecondary">
                  Related Entities
                </Typography>
                <Box mt={1}>
                  {displayFinding.related_entities.map((entity: string, index: number) => (
                    <Chip key={index} label={entity} size="small" sx={{ mr: 1, mb: 1 }} />
                  ))}
                </Box>
              </Grid>
            )}

            {/* Timeline Section */}
            <Grid item xs={12}>
              <Divider sx={{ my: 2 }} />
              <Box display="flex" alignItems="center" mb={2}>
                <TimelineIcon sx={{ mr: 1, color: 'primary.main' }} />
                <Typography variant="h6" color="primary">
                  Related Events
                </Typography>
                {timelineEvents.length > 0 && (
                  <Chip 
                    label={`${timelineEvents.length} events`}
                    size="small"
                    sx={{ ml: 1 }}
                  />
                )}
              </Box>
              
              {timelineLoading ? (
                <Box display="flex" justifyContent="center" alignItems="center" py={4}>
                  <CircularProgress size={30} />
                  <Typography variant="body2" sx={{ ml: 2 }}>
                    Loading timeline...
                  </Typography>
                </Box>
              ) : timelineEvents.length > 0 ? (
                <Paper elevation={2} sx={{ p: 2, bgcolor: 'background.default' }}>
                  <Typography variant="body2" color="textSecondary" gutterBottom>
                    Click on any event to view detailed incident visualization
                  </Typography>
                  <EventTimeline
                    events={timelineEvents.map((e: any) => ({
                      ...e,
                      start: new Date(e.start),
                    }))}
                    onEventClick={handleEventClick}
                    height={300}
                    showControls={false}
                  />
                </Paper>
              ) : (
                <Alert severity="info">
                  No related timeline events found for this finding.
                </Alert>
              )}
            </Grid>

            {/* MITRE Predictions from Model */}
            {displayFinding.mitre_predictions && Object.keys(displayFinding.mitre_predictions).length > 0 && (
              <Grid item xs={12}>
                <Divider sx={{ my: 2 }} />
                <Box display="flex" alignItems="center" mb={2}>
                  <SecurityIcon sx={{ mr: 1, color: 'warning.main' }} />
                  <Typography variant="h6" color="primary">
                    MITRE ATT&CK Predictions
                  </Typography>
                  <Chip
                    label="Model"
                    size="small"
                    variant="outlined"
                    sx={{ ml: 1 }}
                  />
                </Box>
                <Paper elevation={2} sx={{ p: 2, bgcolor: 'background.default' }}>
                  <Box display="flex" flexWrap="wrap" gap={1}>
                    {Object.entries(displayFinding.mitre_predictions).map(([tactic, confidence]: [string, any]) => (
                      <Chip
                        key={tactic}
                        label={`${tactic} (${(Number(confidence) * 100).toFixed(0)}%)`}
                        color="warning"
                        variant="outlined"
                        sx={{ fontWeight: 'bold' }}
                      />
                    ))}
                  </Box>
                  <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                    Predicted by Sentry Agentic LogLM model during ingestion
                  </Typography>
                </Paper>
              </Grid>
            )}

            {/* VStrike Network Context (only renders when enrichment present) */}
            {displayFinding.entity_context?.vstrike && (
              <Grid item xs={12}>
                <Divider sx={{ my: 2 }} />
                <NetworkContextPanel
                  context={
                    displayFinding.entity_context.vstrike as VStrikeEnrichment
                  }
                />
              </Grid>
            )}

            {/* AI Enrichment Section */}
            <Grid item xs={12}>
              <Divider sx={{ my: 2 }} />
              <Box display="flex" alignItems="center" mb={2}>
                <AiIcon sx={{ mr: 1, color: 'primary.main' }} />
                <Typography variant="h6" color="primary">
                  AI-Generated Analysis
                </Typography>
              </Box>
              
              {enrichmentLoading ? (
                <Box display="flex" justifyContent="center" alignItems="center" py={4}>
                  <CircularProgress size={30} />
                  <Typography variant="body2" sx={{ ml: 2 }}>
                    Generating AI analysis...
                  </Typography>
                </Box>
              ) : enrichment ? (
                <Box>
                  {/* Threat Summary */}
                  <Paper elevation={2} sx={{ p: 2, mb: 2, bgcolor: 'background.default' }}>
                    <Box display="flex" alignItems="center" mb={1}>
                      <InfoIcon sx={{ mr: 1, color: 'info.main' }} />
                      <Typography variant="subtitle1" fontWeight="bold">
                        Threat Summary
                      </Typography>
                    </Box>
                    <Typography variant="body2">
                      {enrichment.threat_summary}
                    </Typography>
                    
                    {enrichment.threat_type && (
                      <Box mt={1}>
                        <Chip 
                          label={enrichment.threat_type} 
                          color="error" 
                          size="small" 
                          variant="outlined"
                        />
                      </Box>
                    )}
                  </Paper>

                  {/* Risk Level & Impact */}
                  <Grid container spacing={2} mb={2}>
                    <Grid item xs={12} md={6}>
                      <Paper elevation={1} sx={{ p: 2, height: '100%' }}>
                        <Typography variant="subtitle2" fontWeight="bold" gutterBottom>
                          Risk Level
                        </Typography>
                        <Chip 
                          label={enrichment.risk_level || 'Unknown'}
                          color={
                            enrichment.risk_level === 'Critical' ? 'error' :
                            enrichment.risk_level === 'High' ? 'error' :
                            enrichment.risk_level === 'Medium' ? 'warning' : 'success'
                          }
                          sx={{ mt: 1 }}
                        />
                      </Paper>
                    </Grid>
                    <Grid item xs={12} md={6}>
                      <Paper elevation={1} sx={{ p: 2, height: '100%' }}>
                        <Typography variant="subtitle2" fontWeight="bold" gutterBottom>
                          Confidence Score
                        </Typography>
                        <Typography variant="h5" color="primary">
                          {enrichment.confidence_score ? 
                            `${(enrichment.confidence_score * 100).toFixed(0)}%` : 
                            'N/A'}
                        </Typography>
                      </Paper>
                    </Grid>
                  </Grid>

                  {/* Potential Impact */}
                  {enrichment.potential_impact && (
                    <Accordion defaultExpanded>
                      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                        <Box display="flex" alignItems="center">
                          <WarningIcon sx={{ mr: 1, color: 'warning.main' }} />
                          <Typography fontWeight="bold">Potential Impact</Typography>
                        </Box>
                      </AccordionSummary>
                      <AccordionDetails>
                        <Typography variant="body2">
                          {enrichment.potential_impact}
                        </Typography>
                      </AccordionDetails>
                    </Accordion>
                  )}

                  {/* Recommended Actions */}
                  {enrichment.recommended_actions && enrichment.recommended_actions.length > 0 && (
                    <Accordion defaultExpanded>
                      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                        <Box display="flex" alignItems="center">
                          <CheckCircleIcon sx={{ mr: 1, color: 'success.main' }} />
                          <Typography fontWeight="bold">Recommended Actions</Typography>
                        </Box>
                      </AccordionSummary>
                      <AccordionDetails>
                        <List dense>
                          {enrichment.recommended_actions.map((action: string, index: number) => (
                            <ListItem key={index}>
                              <ListItemText 
                                primary={action}
                                primaryTypographyProps={{ variant: 'body2' }}
                              />
                            </ListItem>
                          ))}
                        </List>
                      </AccordionDetails>
                    </Accordion>
                  )}

                  {/* Investigation Questions */}
                  {enrichment.investigation_questions && enrichment.investigation_questions.length > 0 && (
                    <Accordion>
                      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                        <Typography fontWeight="bold">Investigation Questions</Typography>
                      </AccordionSummary>
                      <AccordionDetails>
                        <List dense>
                          {enrichment.investigation_questions.map((question: string, index: number) => (
                            <ListItem key={index}>
                              <ListItemText 
                                primary={question}
                                primaryTypographyProps={{ variant: 'body2' }}
                              />
                            </ListItem>
                          ))}
                        </List>
                      </AccordionDetails>
                    </Accordion>
                  )}

                  {/* Related MITRE Techniques */}
                  {enrichment.related_techniques && enrichment.related_techniques.length > 0 && (
                    <Accordion>
                      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                        <Typography fontWeight="bold">Related MITRE ATT&CK Techniques</Typography>
                      </AccordionSummary>
                      <AccordionDetails>
                        <List dense>
                          {enrichment.related_techniques.map((tech: any, index: number) => (
                            <ListItem key={index}>
                              <ListItemText 
                                primary={`${tech.technique_id} - ${tech.technique_name}`}
                                secondary={tech.relevance}
                                primaryTypographyProps={{ variant: 'body2', fontWeight: 'bold' }}
                                secondaryTypographyProps={{ variant: 'body2' }}
                              />
                            </ListItem>
                          ))}
                        </List>
                      </AccordionDetails>
                    </Accordion>
                  )}

                  {/* Timeline & Business Context */}
                  {(enrichment.timeline_context || enrichment.business_context) && (
                    <Accordion>
                      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                        <Typography fontWeight="bold">Additional Context</Typography>
                      </AccordionSummary>
                      <AccordionDetails>
                        {enrichment.timeline_context && (
                          <Box mb={2}>
                            <Typography variant="subtitle2" fontWeight="bold" gutterBottom>
                              Timeline Context
                            </Typography>
                            <Typography variant="body2">
                              {enrichment.timeline_context}
                            </Typography>
                          </Box>
                        )}
                        {enrichment.business_context && (
                          <Box>
                            <Typography variant="subtitle2" fontWeight="bold" gutterBottom>
                              Business Context
                            </Typography>
                            <Typography variant="body2">
                              {enrichment.business_context}
                            </Typography>
                          </Box>
                        )}
                      </AccordionDetails>
                    </Accordion>
                  )}

                  {/* Indicators */}
                  {enrichment.indicators && Object.keys(enrichment.indicators).length > 0 && (
                    <Accordion>
                      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                        <Typography fontWeight="bold">Indicators of Compromise</Typography>
                      </AccordionSummary>
                      <AccordionDetails>
                        <Grid container spacing={2}>
                          {enrichment.indicators.malicious_ips && enrichment.indicators.malicious_ips.length > 0 && (
                            <Grid item xs={12}>
                              <Typography variant="subtitle2" fontWeight="bold">Malicious IPs</Typography>
                              <Box mt={1}>
                                {enrichment.indicators.malicious_ips.map((ip: string, i: number) => (
                                  <Chip key={i} label={ip} size="small" sx={{ mr: 1, mb: 1 }} />
                                ))}
                              </Box>
                            </Grid>
                          )}
                          {enrichment.indicators.suspicious_domains && enrichment.indicators.suspicious_domains.length > 0 && (
                            <Grid item xs={12}>
                              <Typography variant="subtitle2" fontWeight="bold">Suspicious Domains</Typography>
                              <Box mt={1}>
                                {enrichment.indicators.suspicious_domains.map((domain: string, i: number) => (
                                  <Chip key={i} label={domain} size="small" sx={{ mr: 1, mb: 1 }} />
                                ))}
                              </Box>
                            </Grid>
                          )}
                        </Grid>
                      </AccordionDetails>
                    </Accordion>
                  )}

                  {/* Analysis Notes */}
                  {enrichment.analysis_notes && (
                    <Box mt={2} p={2} bgcolor="background.paper" borderRadius={1}>
                      <Typography variant="caption" color="textSecondary">
                        <strong>Analyst Notes:</strong> {enrichment.analysis_notes}
                      </Typography>
                    </Box>
                  )}
                </Box>
              ) : (
                <Alert 
                  severity={enrichmentError === 'failed' ? 'warning' : 'info'}
                  sx={enrichmentError === 'failed' ? { cursor: 'pointer' } : undefined}
                  onClick={enrichmentError === 'failed' ? loadEnrichment : undefined}
                >
                  {enrichmentError === 'not_configured'
                    ? 'AI enrichment is not available. Please configure your Claude API key in Settings.'
                    : enrichmentError === 'failed'
                    ? 'AI enrichment failed for this finding. Click to retry.'
                    : 'AI enrichment is not available.'}
                </Alert>
              )}
            </Grid>

            {/* Decision Panel (unified-schema foundation, Phase 2,
                2026-08-20): approve/modify/override/escalate this
                finding's most recent AI decision. */}
            <Grid item xs={12}>
              <Divider sx={{ my: 2 }} />
              <Box display="flex" alignItems="center" mb={1}>
                <CheckCircleIcon sx={{ mr: 1, color: 'primary.main' }} />
                <Typography variant="h6" color="primary">
                  Decision Panel
                </Typography>
              </Box>
              {decisionsLoading ? (
                <CircularProgress size={20} />
              ) : !latestDecision ? (
                <Alert severity="info">
                  No AI decision recorded for this finding yet -- nothing to act on.
                </Alert>
              ) : (
                <Box>
                  <Paper elevation={2} sx={{ p: 2, mb: 2, bgcolor: 'background.default' }}>
                    <Typography variant="caption" color="textSecondary">
                      {latestDecision.agent_id} &middot; confidence {Math.round((latestDecision.confidence_score || 0) * 100)}%
                      {latestDecision.decision_action && (
                        <> &middot; already <strong>{latestDecision.decision_action}d</strong> by {latestDecision.human_reviewer}</>
                      )}
                    </Typography>
                    <Typography variant="body2" sx={{ mt: 1 }}>{latestDecision.reasoning}</Typography>
                    <Typography variant="body2" sx={{ mt: 1 }}>
                      <strong>Recommended:</strong> {latestDecision.recommended_action}
                    </Typography>
                  </Paper>
                  <Box display="flex" gap={1} flexWrap="wrap">
                    <Button
                      size="small"
                      variant="outlined"
                      color="success"
                      startIcon={<ApproveIcon />}
                      disabled={submittingAction}
                      onClick={handleApprove}
                    >
                      Approve
                    </Button>
                    <Button
                      size="small"
                      variant="outlined"
                      startIcon={<ModifyIcon />}
                      disabled={submittingAction}
                      onClick={() => {
                        if (!editing) setEditing(true)
                        openActionDialog('modify')
                      }}
                    >
                      Modify
                    </Button>
                    <Button
                      size="small"
                      variant="outlined"
                      color="warning"
                      startIcon={<OverrideIcon />}
                      disabled={submittingAction}
                      onClick={() => openActionDialog('override')}
                    >
                      Override
                    </Button>
                    <Button
                      size="small"
                      variant="outlined"
                      color="error"
                      startIcon={<EscalateIcon />}
                      disabled={submittingAction}
                      onClick={() => openActionDialog('escalate')}
                    >
                      Escalate
                    </Button>
                  </Box>
                  {pendingAction === 'modify' && actionDialogOpen === false && editing && (
                    <Typography variant="caption" color="textSecondary" sx={{ display: 'block', mt: 1 }}>
                      Edit the fields above, then click Modify again to confirm with a reason.
                    </Typography>
                  )}
                </Box>
              )}
            </Grid>
          </Grid>
        ) : null}
      </DialogContent>

      {/* Decision action dialog -- reason code (required for
          modify/override), optional comment, assignee for escalate.
          Mirrors AIDecisions.tsx's existing Pending-Approvals reject
          dialog pattern (required reason, disabled-until-valid submit). */}
      <Dialog open={actionDialogOpen} onClose={() => setActionDialogOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle sx={{ textTransform: 'capitalize' }}>{pendingAction} Decision</DialogTitle>
        <DialogContent>
          {pendingAction === 'modify' && (!editedFinding || !finding || JSON.stringify(editedFinding) === JSON.stringify(finding)) && (
            <Alert severity="warning" sx={{ mb: 2 }}>
              No changes detected yet. Edit a field (severity, status, description) above first.
            </Alert>
          )}
          <FormControl fullWidth size="small" sx={{ mt: 1, mb: 2 }}>
            <Typography variant="caption" color="textSecondary" sx={{ mb: 0.5 }}>
              Reason {pendingAction !== 'approve' && '(required)'}
            </Typography>
            <Select value={reasonCode} onChange={(e) => setReasonCode(e.target.value)} displayEmpty>
              <MenuItem value=""><em>Select a reason</em></MenuItem>
              {DECISION_REASON_CODES.map((code) => (
                <MenuItem key={code} value={code}>{code.replace(/_/g, ' ')}</MenuItem>
              ))}
            </Select>
          </FormControl>
          {pendingAction === 'escalate' && (
            <TextField
              fullWidth
              size="small"
              label="Assign to (optional)"
              value={escalateTo}
              onChange={(e) => setEscalateTo(e.target.value)}
              sx={{ mb: 2 }}
            />
          )}
          <TextField
            fullWidth
            multiline
            minRows={2}
            size="small"
            label="Comment (optional)"
            value={actionComment}
            onChange={(e) => setActionComment(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setActionDialogOpen(false)} disabled={submittingAction}>Cancel</Button>
          <Button
            variant="contained"
            disabled={submittingAction || !reasonCode}
            onClick={submitPendingAction}
          >
            {submittingAction ? <CircularProgress size={18} /> : 'Confirm'}
          </Button>
        </DialogActions>
      </Dialog>

      <DialogActions>
        <Box display="flex" justifyContent="space-between" width="100%">
          <Box>
            {!editing && (
              <Button onClick={handleDelete} color="error" disabled={loading}>
                Delete
              </Button>
            )}
          </Box>
          <Box>
            {editing ? (
              <>
                <Button onClick={() => setEditing(false)} disabled={loading}>
                  Cancel
                </Button>
                <Button
                  onClick={handleSave}
                  variant="contained"
                  color="error"
                  startIcon={<SaveIcon />}
                  disabled={loading}
                >
                  Save
                </Button>
              </>
            ) : (
              <>
                <Button onClick={onClose}>Close</Button>
                <Button onClick={() => setEditing(true)} variant="contained" color="error">
                  Edit
                </Button>
              </>
            )}
          </Box>
        </Box>
      </DialogActions>

      {/* Snackbar for notifications */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={3000}
        onClose={() => setSnackbar({ ...snackbar, open: false })}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert
          onClose={() => setSnackbar({ ...snackbar, open: false })}
          severity={snackbar.severity}
          variant="filled"
        >
          {snackbar.message}
        </Alert>
      </Snackbar>

      {/* Event Visualization Dialog */}
      <EventVisualizationDialog
        open={eventVizDialogOpen}
        onClose={() => setEventVizDialogOpen(false)}
        eventId={selectedEventId}
      />
    </Dialog>
  )
}

