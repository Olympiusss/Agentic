import { useState, useEffect } from 'react'
import { Box, Typography, Paper, Grid, Chip, CircularProgress, Alert, Stack } from '@mui/material'
import { portalApi } from '../../services/api'

interface HomeData {
  client_id: string | null
  client_display_name: string
  headline: string
  coverage: { endpoint_count: number; agents_offline: number; agents_online: number } | null
  top_findings: Array<{
    finding_id: string
    title: string
    verdict: string
    reasoning: string[]
    hosts: string[]
  }>
  findings_analyzed: number
  estimated_hours_saved: number
  window_hours: number
}

export default function PortalHome() {
  const [data, setData] = useState<HomeData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    portalApi.getHome()
      .then((res) => setData(res.data))
      .catch((err) => setError(err.response?.data?.detail || 'Failed to load your overview'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" py={6}>
        <CircularProgress />
      </Box>
    )
  }

  if (error) {
    return <Alert severity="error">{error}</Alert>
  }

  if (!data) return null

  return (
    <Box>
      <Typography variant="h5" fontWeight={700}>{data.client_display_name}</Typography>

      {/* Posture headline -- one agent-written sentence, not a chart */}
      <Paper variant="outlined" sx={{ p: 2.5, my: 2, bgcolor: 'action.hover' }}>
        <Typography variant="body1">{data.headline}</Typography>
      </Paper>

      {/* Coverage strip -- honest, always visible */}
      <Stack direction="row" spacing={3} sx={{ mb: 3, flexWrap: 'wrap' }}>
        {data.coverage ? (
          <>
            <Typography variant="body2" color="text.secondary">
              <strong>{data.coverage.agents_online}</strong> of <strong>{data.coverage.endpoint_count}</strong> endpoints online
            </Typography>
            {data.coverage.agents_offline > 0 && (
              <Typography variant="body2" color="warning.main">
                {data.coverage.agents_offline} endpoint(s) offline
              </Typography>
            )}
          </>
        ) : (
          <Typography variant="body2" color="text.secondary">Endpoint coverage not available</Typography>
        )}
        <Typography variant="body2" color="text.secondary">
          {data.findings_analyzed} finding(s) analyzed this week &middot; ~{data.estimated_hours_saved}h analyst time saved (estimate)
        </Typography>
      </Stack>

      {/* Top findings as written cards, not a table */}
      <Typography variant="h6" sx={{ mb: 1.5 }}>Priority Findings</Typography>
      {data.top_findings.length === 0 ? (
        <Alert severity="success">No priority findings this week.</Alert>
      ) : (
        <Grid container spacing={2}>
          {data.top_findings.map((f) => (
            <Grid item xs={12} key={f.finding_id}>
              <Paper variant="outlined" sx={{ p: 2 }}>
                <Box display="flex" alignItems="center" gap={1} mb={1}>
                  <Chip
                    label={f.verdict}
                    size="small"
                    color={f.verdict === 'malicious' ? 'error' : 'warning'}
                  />
                  {f.hosts.map((h) => (
                    <Chip key={h} label={h} size="small" variant="outlined" />
                  ))}
                </Box>
                <Typography variant="body2" fontWeight={600} sx={{ mb: 0.5 }}>{f.title}</Typography>
                {f.reasoning.map((line, i) => (
                  <Typography key={i} variant="body2" color="text.secondary">{line}</Typography>
                ))}
              </Paper>
            </Grid>
          ))}
        </Grid>
      )}
    </Box>
  )
}
