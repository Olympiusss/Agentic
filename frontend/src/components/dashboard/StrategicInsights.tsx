/**
 * StrategicInsights - "what would take an analyst hours or days to work
 * out by hand" (explicit user request, 2026-08-04: the dashboard
 * shouldn't just mirror what's already visible in the SentinelOne
 * console). Reads Sentry Agentic's OWN internal analysis -- Zeus's synergy
 * pipeline (Venus/Athena/Orion/Ariadne, reviewed by Themis) -- via
 * GET /api/dashboard/strategic-insights, distinct from
 * SentinelOneOverview.tsx's live-environment mirror.
 */
import { useEffect, useState, useCallback } from 'react'
import { Box, Grid, Typography, Paper, CircularProgress, Chip, Stack, useTheme } from '@mui/material'
import { AutoAwesome as InsightIcon, TrendingUp as SavedIcon, Groups as CampaignIcon, PriorityHigh as PriorityIcon, Hub as BlastRadiusIcon, VerifiedUser as HealthIcon } from '@mui/icons-material'
import { StatCard } from '../ui'
import { severityColors } from '../../theme'
import { dashboardApi } from '../../services/api'

interface VerdictBreakdown {
  malicious: number
  suspicious: number
  clean: number
  unknown: number
}

interface CampaignCluster {
  kind: string
  key: string
  alert_count: number
  hosts: string[]
}

interface PriorityFinding {
  finding_id: string
  title: string
  verdict: string
  reasoning: string[]
  hosts: string[]
  originating_process: string | null
  file_hash: string | null
  threat_family: string | null
}

interface BlastRadiusEntry {
  indicator: string
  indicator_kind: 'hash' | 'ip'
  verdict: string
  origin_host: string
  origin_finding_id: string
  also_seen_on_hosts: string[]
}

interface SystemHealth {
  swept_at: string
  findings_reviewed: number
  findings_never_analyzed: number
  agent_run_counts: Record<string, number>
  agent_error_counts: Record<string, number>
  reputation_providers_configured: string[]
  systemic_issues: string[]
}

interface Insights {
  generated_at: string
  findings_analyzed: number
  verdict_breakdown: VerdictBreakdown
  campaign_clusters: CampaignCluster[]
  top_priority_findings: PriorityFinding[]
  blast_radius: BlastRadiusEntry[]
  system_health: SystemHealth | null
  estimated_hours_saved: number
  reputation_providers_active: string[]
  error?: string | null
}

const POLL_INTERVAL_MS = 60_000

const VERDICT_COLOR: Record<string, string> = {
  malicious: severityColors.critical,
  suspicious: severityColors.high,
  clean: '#22C55E',
}

export default function StrategicInsights() {
  const theme = useTheme()
  const [insights, setInsights] = useState<Insights | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const res = await dashboardApi.getStrategicInsights()
      setInsights(res.data)
    } catch {
      // keep showing whatever we already have
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [load])

  if (loading && !insights) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" py={6}>
        <CircularProgress size={28} />
      </Box>
    )
  }

  if (!insights) return null

  const noDataYet = insights.findings_analyzed === 0 && insights.campaign_clusters.length === 0

  return (
    <Box sx={{ mb: 3 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2, flexWrap: 'wrap', gap: 1 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <InsightIcon sx={{ color: '#8B5CF6', fontSize: 22 }} />
          <Typography
            variant="h6"
            fontWeight={800}
            sx={{
              background: 'linear-gradient(135deg, #8B5CF6 0%, #C084FC 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
            }}
          >
            Strategic Insights -- from our own multi-agent analysis
          </Typography>
        </Box>
        {insights.system_health && (
          <Chip
            size="small"
            icon={<HealthIcon sx={{ fontSize: 16 }} />}
            label={
              insights.system_health.systemic_issues.some((n) => !n.startsWith('no systemic issues'))
                ? `Themis: ${insights.system_health.systemic_issues.length} issue(s)`
                : 'Themis: all agents healthy'
            }
            color={insights.system_health.systemic_issues.some((n) => !n.startsWith('no systemic issues')) ? 'warning' : 'success'}
            variant="outlined"
          />
        )}
      </Box>

      {noDataYet ? (
        <Paper variant="outlined" sx={{ p: 3, textAlign: 'center', borderRadius: 3 }}>
          <Typography variant="body2" color="text.secondary">
            The multi-agent pipeline (Venus, Athena, Orion, Ariadne, reviewed by Themis) hasn't analyzed a
            SentinelOne finding yet -- insights populate here automatically as new threats are ingested.
          </Typography>
        </Paper>
      ) : (
        <>
          <Grid container spacing={2} sx={{ mb: 2 }}>
            <Grid item xs={12} sm={6} md={3}>
              <StatCard
                title="Findings Analyzed"
                value={insights.findings_analyzed}
                subtitle="hash + IP reputation checked"
                icon={<InsightIcon />}
                color="#8B5CF6"
              />
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <StatCard
                title="Est. Analyst Hours Saved"
                value={insights.estimated_hours_saved}
                subtitle="vs. manual artifact triage"
                icon={<SavedIcon />}
                color="#22C55E"
              />
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <StatCard
                title="Malicious / Suspicious"
                value={`${insights.verdict_breakdown.malicious} / ${insights.verdict_breakdown.suspicious}`}
                subtitle="confirmed via VirusTotal/AbuseIPDB"
                icon={<PriorityIcon />}
                color={severityColors.high}
              />
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <StatCard
                title="Campaign Clusters"
                value={insights.campaign_clusters.length}
                subtitle="cross-alert patterns detected"
                icon={<CampaignIcon />}
                color="#1A6AFF"
              />
            </Grid>
          </Grid>

          {insights.reputation_providers_active.length === 0 && (
            <Paper variant="outlined" sx={{ p: 1.5, mb: 2, borderRadius: 2, bgcolor: 'action.hover' }}>
              <Typography variant="caption" color="text.secondary">
                VirusTotal/AbuseIPDB API keys not yet configured -- artifact hashes and IPs are being extracted
                and stored, but reputation verdicts will show as "unknown" until keys are added.
              </Typography>
            </Paper>
          )}

          <Grid container spacing={2}>
            <Grid item xs={12} md={6}>
              <Paper variant="outlined" sx={{ p: 2, borderRadius: 3, minHeight: 220 }}>
                <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1.5 }}>
                  Cross-Alert Campaign Clusters
                </Typography>
                {insights.campaign_clusters.length === 0 ? (
                  <Typography variant="caption" color="text.secondary">No multi-host or multi-alert patterns detected in the current window.</Typography>
                ) : (
                  <Stack spacing={1.5}>
                    {insights.campaign_clusters.map((c) => (
                      <Box key={c.key} sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', p: 1, borderRadius: 2, bgcolor: 'action.hover' }}>
                        <Box>
                          <Typography variant="body2" fontWeight={600}>Storyline {c.key.slice(0, 12)}...</Typography>
                          <Typography variant="caption" color="text.secondary">{c.hosts.join(', ') || 'host unknown'}</Typography>
                        </Box>
                        <Chip size="small" label={`${c.alert_count} alerts`} color="primary" variant="outlined" />
                      </Box>
                    ))}
                  </Stack>
                )}
              </Paper>
            </Grid>

            <Grid item xs={12} md={6}>
              <Paper variant="outlined" sx={{ p: 2, borderRadius: 3, minHeight: 220 }}>
                <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1.5 }}>
                  Priority Findings (why, not just what)
                </Typography>
                {insights.top_priority_findings.length === 0 ? (
                  <Typography variant="caption" color="text.secondary">No findings currently carry a malicious/suspicious reputation verdict.</Typography>
                ) : (
                  <Stack spacing={1.5}>
                    {insights.top_priority_findings.map((f) => (
                      <Box key={f.finding_id} sx={{ p: 1, borderRadius: 2, bgcolor: 'action.hover' }}>
                        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <Typography variant="body2" fontWeight={600} noWrap sx={{ maxWidth: '70%' }}>{f.title}</Typography>
                          <Chip size="small" label={f.threat_family || f.verdict} sx={{ bgcolor: VERDICT_COLOR[f.verdict] || theme.palette.grey[500], color: '#fff' }} />
                        </Box>
                        {f.originating_process && (
                          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5, fontFamily: 'monospace', wordBreak: 'break-all' }}>
                            Process: {f.originating_process}
                          </Typography>
                        )}
                        {f.file_hash && (
                          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', fontFamily: 'monospace', wordBreak: 'break-all' }}>
                            Hash: {f.file_hash}
                          </Typography>
                        )}
                        {f.reasoning.slice(0, 1).map((r, i) => (
                          <Typography key={i} variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>{r}</Typography>
                        ))}
                      </Box>
                    ))}
                  </Stack>
                )}
              </Paper>
            </Grid>
          </Grid>

          <Paper variant="outlined" sx={{ p: 2, borderRadius: 3, mt: 2, minHeight: 160 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
              <BlastRadiusIcon sx={{ fontSize: 18, color: '#F97316' }} />
              <Typography variant="subtitle2" fontWeight={700}>
                Blast Radius -- has this indicator spread to other hosts?
              </Typography>
            </Box>
            {insights.blast_radius.length === 0 ? (
              <Typography variant="caption" color="text.secondary">
                No malicious/suspicious hash or IP has been seen on more than one host yet.
              </Typography>
            ) : (
              <Stack spacing={1.5}>
                {insights.blast_radius.map((b) => (
                  <Box key={`${b.indicator_kind}-${b.indicator}`} sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', p: 1, borderRadius: 2, bgcolor: 'action.hover' }}>
                    <Box>
                      <Typography variant="body2" fontWeight={600}>
                        {b.indicator_kind === 'hash' ? 'Hash' : 'IP'} {b.indicator} -- first seen on {b.origin_host}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {b.also_seen_on_hosts.length > 0
                          ? `Also seen on: ${b.also_seen_on_hosts.join(', ')}`
                          : 'Not seen on any other host yet'}
                      </Typography>
                    </Box>
                    <Chip
                      size="small"
                      label={b.also_seen_on_hosts.length > 0 ? `spread to ${b.also_seen_on_hosts.length}` : 'contained'}
                      sx={{ bgcolor: b.also_seen_on_hosts.length > 0 ? severityColors.critical : theme.palette.grey[500], color: '#fff' }}
                    />
                  </Box>
                ))}
              </Stack>
            )}
          </Paper>
        </>
      )}
    </Box>
  )
}
