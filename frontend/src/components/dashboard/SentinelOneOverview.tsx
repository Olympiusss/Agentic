/**
 * SentinelOneOverview - real-time environment snapshot for the dashboard
 * (dashboard rebuild request, 2026-08-03: "own visual identity ... bar and
 * pie charts ... populated in realtime, sync 24/7").
 *
 * Reads services/sentinelone_dashboard_service.py's background-refreshed
 * cache (server refreshes every 5 minutes regardless of viewers) via
 * GET /api/dashboard/sentinelone-overview -- this component additionally
 * polls that cached endpoint every 60s so an open dashboard tab reflects
 * the next server-side refresh promptly, without ever triggering a live
 * SentinelOne round-trip itself.
 */
import { useEffect, useState, useCallback } from 'react'
import { Box, Grid, Typography, Paper, CircularProgress, IconButton, Tooltip, useTheme } from '@mui/material'
import { Refresh as RefreshIcon, Dns as EndpointsIcon, AccountTree as GroupsIcon, ReportProblem as IncidentsIcon, BugReport as VulnIcon, GppMaybe as ThreatIcon } from '@mui/icons-material'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend, LabelList } from 'recharts'
import { StatCard } from '../ui'
import { severityColors } from '../../theme'
import { dashboardApi } from '../../services/api'

interface Snapshot {
  generated_at: string
  tenant: string
  sentinelone_active: boolean
  endpoint_count: number
  endpoint_count_is_lower_bound: boolean
  groups: string[]
  groups_may_be_incomplete: boolean
  groups_without_current_endpoint: string[]
  accounts: string[]
  sites: string[]
  alerts_new: number
  alerts_in_progress: number
  alerts_resolved: number
  alerts_window_hours: number
  vulnerabilities_critical: number
  vulnerabilities_high: number
  vulnerabilities_medium: number
  vulnerabilities_low: number
  vulnerabilities_critical_new_24h: number
  vulnerabilities_critical_top_driver: { name: string; critical_count: number; pct_of_total: number } | null
  agents_offline: number
  top_applications: { name: string; count: number }[]
  endpoints_infected: number
  endpoints_healthy: number
  threats_malware: number
  threats_ransomware: number
  threats_manual: number
  detection_sources: { name: string; count: number }[]
  detection_sources_is_sample: boolean
  error?: string | null
}

const POLL_INTERVAL_MS = 60_000

function relativeTime(iso?: string): string {
  if (!iso) return ''
  const diffMs = Date.now() - new Date(iso).getTime()
  const mins = Math.round(diffMs / 60000)
  if (mins < 1) return 'moments ago'
  if (mins === 1) return '1 minute ago'
  if (mins < 60) return `${mins} minutes ago`
  const hours = Math.round(mins / 60)
  return `${hours}h ago`
}

const INCIDENT_COLORS = { new: '#1A6AFF', in_progress: '#F97316', resolved: '#22C55E' }
const INFECTION_COLORS = { infected: '#DC2626', healthy: '#22C55E' }
const CLASSIFICATION_COLORS = { ransomware: '#7F1D1D', malware: '#DC2626', manual: '#F59E0B' }
const DETECTION_SOURCE_COLORS = ['#1A6AFF', '#8B5CF6', '#22C55E', '#F97316']

export default function SentinelOneOverview() {
  const theme = useTheme()
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const res = await dashboardApi.getSentinelOneOverview()
      setSnapshot(res.data)
    } catch {
      // Keep showing whatever we already have rather than blank the
      // section on a transient network hiccup.
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [load])

  if (loading && !snapshot) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" py={6}>
        <CircularProgress size={28} />
      </Box>
    )
  }

  if (!snapshot || !snapshot.sentinelone_active) {
    return (
      <Paper variant="outlined" sx={{ p: 3, textAlign: 'center', borderRadius: 3, mb: 3 }}>
        <Typography variant="body2" color="text.secondary">
          SentinelOne is not connected -- environment overview unavailable.
        </Typography>
      </Paper>
    )
  }

  const alertStatusData = [
    { name: 'New', value: snapshot.alerts_new, color: INCIDENT_COLORS.new },
    { name: 'In Progress', value: snapshot.alerts_in_progress, color: INCIDENT_COLORS.in_progress },
    { name: 'Resolved', value: snapshot.alerts_resolved, color: INCIDENT_COLORS.resolved },
  ].filter(d => d.value > 0)

  const vulnData = [
    { name: 'Critical', value: snapshot.vulnerabilities_critical, color: severityColors.critical },
    { name: 'High', value: snapshot.vulnerabilities_high, color: severityColors.high },
    { name: 'Medium', value: snapshot.vulnerabilities_medium, color: severityColors.medium },
    { name: 'Low', value: snapshot.vulnerabilities_low, color: severityColors.low },
  ]

  const activeAlerts = snapshot.alerts_new + snapshot.alerts_in_progress

  const infectionData = [
    { name: 'Infected', value: snapshot.endpoints_infected, color: INFECTION_COLORS.infected },
    { name: 'Healthy', value: snapshot.endpoints_healthy, color: INFECTION_COLORS.healthy },
  ].filter(d => d.value > 0)

  const threatTypeData = [
    { name: 'Ransomware', value: snapshot.threats_ransomware, color: CLASSIFICATION_COLORS.ransomware },
    { name: 'Malware', value: snapshot.threats_malware, color: CLASSIFICATION_COLORS.malware },
    { name: 'Manual', value: snapshot.threats_manual, color: CLASSIFICATION_COLORS.manual },
  ].filter(d => d.value > 0)

  return (
    <Box sx={{ mb: 3 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', mb: 2, flexWrap: 'wrap', gap: 1 }}>
        <Typography
          variant="h6"
          fontWeight={800}
          sx={{
            background: 'linear-gradient(135deg, #5BA4FF 0%, #1A6AFF 100%)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
          }}
        >
          Live Environment Overview -- {snapshot.tenant}
        </Typography>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Typography variant="caption" color="text.secondary">
            Synced {relativeTime(snapshot.generated_at)}
          </Typography>
          <Tooltip title="Refresh now">
            <IconButton size="small" onClick={load}>
              <RefreshIcon sx={{ fontSize: 16 }} />
            </IconButton>
          </Tooltip>
        </Box>
      </Box>

      <Grid container spacing={2} sx={{ mb: 2 }}>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard
            title="Endpoints"
            value={`${snapshot.endpoint_count_is_lower_bound ? 'at least ' : ''}${snapshot.endpoint_count}`}
            subtitle={`${snapshot.agents_offline} agent(s) offline from SentinelOne cloud`}
            icon={<EndpointsIcon />}
            color={theme.palette.primary.main}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard
            title="Groups"
            value={snapshot.groups.length}
            subtitle={
              snapshot.groups_without_current_endpoint.length > 0
                ? `${snapshot.groups_without_current_endpoint.length} without a current endpoint: ${snapshot.groups_without_current_endpoint.join(', ')}`
                : `${snapshot.accounts.length} account(s), ${snapshot.sites.length} site(s) -- a group with neither an endpoint nor a vulnerability record isn't visible via this integration`
            }
            icon={<GroupsIcon />}
            color="#8B5CF6"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard
            title={`Active Alerts (last ${snapshot.alerts_window_hours}h)`}
            value={activeAlerts}
            subtitle={`${snapshot.alerts_resolved} resolved in window -- SentinelOne's own Incidents view (grouped/correlated alerts) isn't accessible via this integration`}
            icon={<IncidentsIcon />}
            color={activeAlerts > 0 ? severityColors.high : theme.palette.success.main}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <Tooltip title="Raw count of (endpoint x CVE) findings across the whole fleet, not distinct CVEs or distinct apps -- one outdated, widely-installed application repeats its full CVE list on every endpoint that has it, which is usually most of this total. Won't match SentinelOne's own per-endpoint Application Vulnerability view (that's one machine's distinct apps, a different scope entirely).">
            <Box sx={{ height: '100%', cursor: 'help' }}>
              <StatCard
                title="Critical Vulnerabilities"
                value={snapshot.vulnerabilities_critical}
                subtitle={
                  snapshot.vulnerabilities_critical_top_driver
                    ? `${snapshot.vulnerabilities_critical_top_driver.pct_of_total}% from ${snapshot.vulnerabilities_critical_top_driver.name} alone -- patch it fleet-wide to clear most of this`
                    : `Standing total -- ${snapshot.vulnerabilities_critical_new_24h} new in last 24h`
                }
                icon={<VulnIcon />}
                color={severityColors.critical}
              />
            </Box>
          </Tooltip>
        </Grid>
      </Grid>

      <Grid container spacing={2}>
        <Grid item xs={12} md={4}>
          <Paper variant="outlined" sx={{ p: 2, borderRadius: 3, height: 280 }}>
            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
              Alert Status
            </Typography>
            <ResponsiveContainer width="100%" height="85%">
              <PieChart>
                <Pie
                  data={alertStatusData}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={45}
                  outerRadius={75}
                  paddingAngle={2}
                  label={({ value }) => value}
                  labelLine={false}
                >
                  {alertStatusData.map((d, i) => <Cell key={i} fill={d.color} />)}
                </Pie>
                <RechartsTooltip />
                <Legend verticalAlign="bottom" height={24} />
              </PieChart>
            </ResponsiveContainer>
          </Paper>
        </Grid>

        <Grid item xs={12} md={4}>
          <Paper variant="outlined" sx={{ p: 2, borderRadius: 3, height: 280 }}>
            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
              Vulnerability Severity
            </Typography>
            <ResponsiveContainer width="100%" height="85%">
              <BarChart data={vulnData}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <RechartsTooltip />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {vulnData.map((d, i) => <Cell key={i} fill={d.color} />)}
                  <LabelList dataKey="value" position="top" style={{ fontSize: 11, fill: theme.palette.text.primary }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </Paper>
        </Grid>

        <Grid item xs={12} md={4}>
          <Paper variant="outlined" sx={{ p: 2, borderRadius: 3, height: 280 }}>
            <Tooltip title="Exact vulnerability-record count per application (real total_count query, not a sample estimate). Won't exactly match SentinelOne's own Application Management view -- that aggregates by unique app version with its own date filter, a different computation this integration has no API access to.">
              <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1, cursor: 'help', width: 'fit-content' }}>
                Application Risk (vulnerability count)
              </Typography>
            </Tooltip>
            {snapshot.top_applications.length === 0 ? (
              <Typography variant="caption" color="text.secondary">No application data in the current sample.</Typography>
            ) : (
              <ResponsiveContainer width="100%" height="85%">
                <BarChart data={snapshot.top_applications} layout="vertical" margin={{ left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                  <XAxis type="number" tick={{ fontSize: 11 }} />
                  <YAxis type="category" dataKey="name" tick={{ fontSize: 10 }} width={90} />
                  <RechartsTooltip />
                  <Bar dataKey="count" fill="#1A6AFF" radius={[0, 4, 4, 0]}>
                    <LabelList dataKey="count" position="right" style={{ fontSize: 11, fill: theme.palette.text.primary }} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </Paper>
        </Grid>
      </Grid>

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 3, mb: 2 }}>
        <ThreatIcon sx={{ color: '#DC2626', fontSize: 22 }} />
        <Typography variant="h6" fontWeight={800}>
          Threat Landscape
        </Typography>
      </Box>

      <Grid container spacing={2}>
        <Grid item xs={12} md={4}>
          <Paper variant="outlined" sx={{ p: 2, borderRadius: 3, height: 280 }}>
            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
              Infected Endpoints
            </Typography>
            {infectionData.length === 0 ? (
              <Typography variant="caption" color="text.secondary">No endpoint infection data available.</Typography>
            ) : (
              <ResponsiveContainer width="100%" height="85%">
                <PieChart>
                  <Pie
                    data={infectionData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={45}
                    outerRadius={75}
                    paddingAngle={2}
                    label={({ value }) => value}
                    labelLine={false}
                  >
                    {infectionData.map((d, i) => <Cell key={i} fill={d.color} />)}
                  </Pie>
                  <RechartsTooltip />
                  <Legend verticalAlign="bottom" height={24} />
                </PieChart>
              </ResponsiveContainer>
            )}
          </Paper>
        </Grid>

        <Grid item xs={12} md={4}>
          <Paper variant="outlined" sx={{ p: 2, borderRadius: 3, height: 280 }}>
            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
              Threats by Type
            </Typography>
            {threatTypeData.length === 0 ? (
              <Typography variant="caption" color="text.secondary">No threat classification data available.</Typography>
            ) : (
              <ResponsiveContainer width="100%" height="85%">
                <PieChart>
                  <Pie
                    data={threatTypeData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={45}
                    outerRadius={75}
                    paddingAngle={2}
                    label={({ value }) => value}
                    labelLine={false}
                  >
                    {threatTypeData.map((d, i) => <Cell key={i} fill={d.color} />)}
                  </Pie>
                  <RechartsTooltip />
                  <Legend verticalAlign="bottom" height={24} />
                </PieChart>
              </ResponsiveContainer>
            )}
          </Paper>
        </Grid>

        <Grid item xs={12} md={4}>
          <Paper variant="outlined" sx={{ p: 2, borderRadius: 3, height: 280 }}>
            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>
              Threats by Detection Engine{snapshot.detection_sources_is_sample ? ' (sample)' : ''}
            </Typography>
            {snapshot.detection_sources.length === 0 ? (
              <Typography variant="caption" color="text.secondary">No detection source data in the current sample.</Typography>
            ) : (
              <ResponsiveContainer width="100%" height="85%">
                <BarChart data={snapshot.detection_sources}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <RechartsTooltip />
                  <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                    {snapshot.detection_sources.map((_, i) => <Cell key={i} fill={DETECTION_SOURCE_COLORS[i % DETECTION_SOURCE_COLORS.length]} />)}
                    <LabelList dataKey="count" position="top" style={{ fontSize: 11, fill: theme.palette.text.primary }} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </Paper>
        </Grid>
      </Grid>
    </Box>
  )
}
