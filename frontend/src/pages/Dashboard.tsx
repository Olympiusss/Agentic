import { useEffect, useState, useMemo } from 'react'
import { useOutletContext, useNavigate } from 'react-router-dom'
import {
  Box,
  Grid,
  Typography,
  Tabs,
  Tab,
  CircularProgress,
  Button,
  IconButton,
  Select,
  MenuItem,
  FormControl,
  Snackbar,
  Alert,
  Tooltip,
  Collapse,
  alpha,
  useTheme,
} from '@mui/material'
import {
  Warning as WarningIcon,
  Folder as FolderIcon,
  Refresh as RefreshIcon,
  Timeline as TimelineIcon,
  FilterList as FilterIcon,
  Shield as ShieldIcon,
} from '@mui/icons-material'
import { findingsApi, casesApi, configApi, timelineApi, graphApi } from '../services/api'
import { useSelectedClient } from '../contexts/SelectedClientContext'
import FindingsTable from '../components/findings/FindingsTable'
import AttackChart from '../components/attack/AttackChart'
import ExportToTimesketchDialog from '../components/timesketch/ExportToTimesketchDialog'
import EventTimeline from '../components/timeline/EventTimeline'
import EntityVisualization from '../components/graph/EntityVisualization'
import { StatCard, SearchInput } from '../components/ui'
import SentinelOneOverview from '../components/dashboard/SentinelOneOverview'
import StrategicInsights from '../components/dashboard/StrategicInsights'
import ClientDetail from '../components/dashboard/ClientDetail'
import { severityColors } from '../theme'
import { useAuth } from '../contexts/AuthContext'

interface LayoutContext {
  handleInvestigate: (findingId: string, agentId: string, prompt: string, title: string) => void
}

interface Stats {
  findings: any
  cases: any
}

export default function Dashboard() {
  const { handleInvestigate } = useOutletContext<LayoutContext>()
  const navigate = useNavigate()
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const [currentTab, setCurrentTab] = useState(0)
  const [filters, setFilters] = useState({ severity: '', data_source: '', min_anomaly_score: '' })
  const [findingsSearch, setFindingsSearch] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' }>({
    open: false, message: '', severity: 'success',
  })
  const [timesketchDialogOpen, setTimesketchDialogOpen] = useState(false)
  const [selectedFindingIds, setSelectedFindingIds] = useState<string[]>([])
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [refreshInterval, setRefreshInterval] = useState(30)
  const [timesketchEnabled, setTimesketchEnabled] = useState(false)
  const [showFilters, setShowFilters] = useState(false)
  const theme = useTheme()
  const { user } = useAuth()
  const { selectedClient } = useSelectedClient()
  const [timelineEvents, setTimelineEvents] = useState<any[]>([])

  // --- Dynamic greeting - auto-detects user + client from auth context ---
  const greeting = useMemo(() => {
    const h = new Date().getHours()
    const firstName = user?.full_name
      ? user.full_name.split(' ')[0]
      : (user?.username || 'Operator')
    const client = (user as any)?.organisation || 'Cybervergent'
    const timeGreet = h >= 5 && h < 12  ? 'Good morning'
                    : h >= 12 && h < 17 ? 'Good afternoon'
                    : h >= 17 && h < 21 ? 'Good evening'
                    : 'Good night'
    return `${timeGreet} ${firstName}, ${client}`
  }, [user])

  // --- Sub-label: current date ---
  const dateLabel = useMemo(() => {
    return new Date().toLocaleDateString('en-GB', {
      weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
    })
  }, [])

  const [graphData, setGraphData] = useState<{ nodes: any[]; links: any[] }>({ nodes: [], links: [] })
  const [loadingTimeline, setLoadingTimeline] = useState(false)
  const [loadingGraph, setLoadingGraph] = useState(false)

  useEffect(() => {
    loadStats()
    checkTimesketchStatus()
  }, [])

  useEffect(() => {
    if (currentTab === 2) {
      loadTimelineData()
    } else if (currentTab === 3) {
      loadGraphData()
    }
  }, [currentTab])

  const checkTimesketchStatus = async () => {
    try {
      const response = await configApi.getIntegrations()
      setTimesketchEnabled(response.data?.enabled_integrations?.includes('timesketch') || false)
    } catch { setTimesketchEnabled(false) }
  }

  useEffect(() => {
    if (!autoRefresh) return
    const intervalId = setInterval(() => handleRefresh(), refreshInterval * 1000)
    return () => clearInterval(intervalId)
  }, [autoRefresh, refreshInterval])

  const loadStats = async () => {
    try {
      const [findingsRes, casesRes] = await Promise.all([
        findingsApi.getSummary(),
        casesApi.getSummary(),
      ])
      setStats({ findings: findingsRes.data, cases: casesRes.data })
    } catch (error) {
      console.error('Failed to load stats:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleRefresh = () => {
    setRefreshKey(prev => prev + 1)
    loadStats()
  }

  const handleExportToTimesketch = async () => {
    try {
      const params: any = { ...filters }
      if (selectedClient?.client_id) params.client_id = selectedClient.client_id
      Object.keys(params).forEach(key => {
        if (!params[key]) delete params[key]
      })
      const response = await findingsApi.getAll(params)
      setSelectedFindingIds(response.data.findings?.map((f: any) => f.finding_id) || [])
      setTimesketchDialogOpen(true)
    } catch {
      setSnackbar({ open: true, message: 'Failed to prepare export', severity: 'error' })
    }
  }

  const loadTimelineData = async () => {
    setLoadingTimeline(true)
    try {
      const response = await timelineApi.getTimelineRange({ limit: 500 })
      setTimelineEvents(response.data.events || [])
    } catch (error) {
      console.error('Failed to load timeline data:', error)
      setSnackbar({ open: true, message: 'Failed to load timeline', severity: 'error' })
    } finally {
      setLoadingTimeline(false)
    }
  }

  const loadGraphData = async () => {
    setLoadingGraph(true)
    try {
      const response = await graphApi.getEntityGraph({ limit: 100 })
      setGraphData({
        nodes: response.data.nodes || [],
        links: response.data.links || []
      })
    } catch (error) {
      console.error('Failed to load graph data:', error)
      setSnackbar({ open: true, message: 'Failed to load graph', severity: 'error' })
    } finally {
      setLoadingGraph(false)
    }
  }

  const handleTimelineEventClick = (event: any) => {
    if (event.metadata?.finding_id) {
      // Navigate to investigation with this finding
      navigate(`/investigation?finding_ids=${event.metadata.finding_id}`)
    }
  }

  const handleGraphNodeClick = (node: any) => {
    // Navigate to investigation with this entity's findings
    if (node.metadata?.findings && node.metadata.findings.length > 0) {
      navigate(`/investigation?finding_ids=${node.metadata.findings.join(',')}`)
    } else {
      // Show a snackbar for entities without linked findings
      setSnackbar({ open: true, message: `Entity: ${node.label} (${node.type})`, severity: 'success' })
    }
  }

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" height="80vh">
        <CircularProgress />
      </Box>
    )
  }

  const criticalCount = stats?.findings?.by_severity?.critical || 0
  const highCount = stats?.findings?.by_severity?.high || 0

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="flex-start" mb={3}>
        <Box>
          {/* Dynamic time-based greeting */}
          <Typography
            variant="h4"
            sx={{
              fontWeight: 800,
              mb: 0.3,
              background: 'linear-gradient(135deg, #ffffff 0%, #1A6AFF 60%, #5BA4FF 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
              textShadow: 'none',
              filter: 'drop-shadow(0 4px 16px rgba(26,106,255,0.45)) drop-shadow(0 1px 3px rgba(0,0,0,0.4))',
              letterSpacing: '-0.03em',
              lineHeight: 1.1,
              userSelect: 'none',
            }}
          >
            {greeting}
          </Typography>
          <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.4)', letterSpacing: '0.04em', fontSize: '0.72rem', fontWeight: 400, mt: 0.3 }}>
            {dateLabel}
          </Typography>
          <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.35)', letterSpacing: '0.08em', fontSize: '0.68rem', textTransform: 'uppercase', fontWeight: 500, mt: 0.2 }}>
            Security Operations Centre
          </Typography>
        </Box>
        <Box display="flex" alignItems="center" gap={1}>
          {autoRefresh && (
            <FormControl size="small" sx={{ minWidth: 70 }}>
              <Select
                value={refreshInterval}
                onChange={(e) => setRefreshInterval(Number(e.target.value))}
                sx={{ fontSize: '0.75rem' }}
              >
                <MenuItem value={10}>10s</MenuItem>
                <MenuItem value={30}>30s</MenuItem>
                <MenuItem value={60}>1m</MenuItem>
              </Select>
            </FormControl>
          )}
          <Tooltip title={autoRefresh ? 'Stop auto-refresh' : 'Start auto-refresh'}>
            <IconButton
              size="small"
              onClick={() => setAutoRefresh(!autoRefresh)}
              sx={{
                bgcolor: autoRefresh ? alpha(theme.palette.primary.main, 0.15) : 'transparent',
                color: autoRefresh ? 'primary.main' : 'text.secondary',
              }}
            >
              <RefreshIcon sx={{ fontSize: 20 }} />
            </IconButton>
          </Tooltip>
          {timesketchEnabled && (
            <Button size="small" startIcon={<TimelineIcon />} onClick={handleExportToTimesketch}>
              Timesketch
            </Button>
          )}
        </Box>
      </Box>

      <ClientDetail />
      <StrategicInsights />
      <SentinelOneOverview />

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard
            title="Total Findings"
            value={stats?.findings?.total || 0}
            subtitle={`${criticalCount} critical, ${highCount} high`}
            icon={<WarningIcon />}
            color={criticalCount > 0 ? severityColors.critical : severityColors.medium}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard
            title="Active Cases"
            value={stats?.cases?.total || 0}
            subtitle={`${stats?.cases?.by_status?.open || 0} open`}
            icon={<FolderIcon />}
            color={theme.palette.primary.main}
            onClick={() => navigate('/cases')}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard
            title="Critical Alerts"
            value={criticalCount}
            subtitle="Requires immediate attention"
            icon={<ShieldIcon />}
            color={severityColors.critical}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard
            title="High Priority"
            value={highCount}
            subtitle="Review within 24 hours"
            icon={<WarningIcon />}
            color={severityColors.high}
          />
        </Grid>
      </Grid>

      <Box sx={{ bgcolor: 'background.paper', borderRadius: 3, border: 1, borderColor: 'divider' }}>
        <Box sx={{ borderBottom: 1, borderColor: 'divider', px: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Tabs value={currentTab} onChange={(_, v) => setCurrentTab(v)}>
            <Tab label="Findings" sx={{ minHeight: 48 }} />
            <Tab label="ATT&CK" sx={{ minHeight: 48 }} />
            <Tab label="Timeline" sx={{ minHeight: 48 }} />
            <Tab label="Entity Graph" sx={{ minHeight: 48 }} />
          </Tabs>
          {currentTab === 0 && (
            <IconButton size="small" onClick={() => setShowFilters(!showFilters)}>
              <FilterIcon sx={{ fontSize: 20, color: showFilters ? 'primary.main' : 'text.secondary' }} />
            </IconButton>
          )}
        </Box>

        <Box sx={{ p: 2 }}>
          {currentTab === 0 && (
            <>
              <Box sx={{ mb: 2, display: 'flex', gap: 2, alignItems: 'center' }}>
                <Box sx={{ flex: 1, maxWidth: 400 }}>
                  <SearchInput
                    value={findingsSearch}
                    onChange={setFindingsSearch}
                    placeholder="Search findings..."
                  />
                </Box>
              </Box>
              <Collapse in={showFilters}>
                <Box sx={{ mb: 2, display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                  <FormControl size="small" sx={{ minWidth: 120 }}>
                    <Select
                      value={filters.severity}
                      onChange={(e) => setFilters({ ...filters, severity: e.target.value })}
                      displayEmpty
                    >
                      <MenuItem value="">All Severities</MenuItem>
                      <MenuItem value="critical">Critical</MenuItem>
                      <MenuItem value="high">High</MenuItem>
                      <MenuItem value="medium">Medium</MenuItem>
                      <MenuItem value="low">Low</MenuItem>
                    </Select>
                  </FormControl>
                </Box>
              </Collapse>
              <FindingsTable
                filters={filters}
                searchQuery={findingsSearch}
                refreshKey={refreshKey}
                onInvestigate={handleInvestigate}
              />
            </>
          )}
          {currentTab === 1 && <AttackChart />}
          {currentTab === 2 && (
            loadingTimeline ? (
              <Box display="flex" justifyContent="center" p={3}>
                <CircularProgress />
              </Box>
            ) : (
              <EventTimeline
                events={timelineEvents}
                onEventClick={handleTimelineEventClick}
                height={500}
                groupBy="type"
              />
            )
          )}
          {currentTab === 3 && (
            loadingGraph ? (
              <Box display="flex" justifyContent="center" p={3}>
                <CircularProgress />
              </Box>
            ) : (
              <Box sx={{ height: 500, overflow: 'hidden', position: 'relative' }}>
                <EntityVisualization
                  nodes={graphData.nodes}
                  links={graphData.links}
                  onNodeClick={handleGraphNodeClick}
                  height={500}
                />
              </Box>
            )
          )}
        </Box>
      </Box>

      <Snackbar
        open={snackbar.open}
        autoHideDuration={3000}
        onClose={() => setSnackbar({ ...snackbar, open: false })}
      >
        <Alert onClose={() => setSnackbar({ ...snackbar, open: false })} severity={snackbar.severity} variant="filled">
          {snackbar.message}
        </Alert>
      </Snackbar>

      <ExportToTimesketchDialog
        open={timesketchDialogOpen}
        onClose={() => setTimesketchDialogOpen(false)}
        findingIds={selectedFindingIds}
        defaultTimelineName={`Findings Export - ${new Date().toLocaleDateString()}`}
      />
    </Box>
  )
}
