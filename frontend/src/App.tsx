import { lazy, Suspense } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { Box, CircularProgress } from '@mui/material'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { SelectedClientProvider } from './contexts/SelectedClientContext'
import ProtectedRoute from './components/auth/ProtectedRoute'
import MainLayout from './components/layout/MainLayout'
import PortalLayout from './components/layout/PortalLayout'

// Lazy-load every page so a refresh on any route only pulls that page's
// module graph (plus shared deps). Previously every page was eagerly
// imported, forcing ~1 MB of JS + all its MUI/recharts/x-data-grid deps
// on every cold load.
const Login = lazy(() => import('./pages/Login'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Cases = lazy(() => import('./pages/Cases'))
const CaseMetrics = lazy(() => import('./pages/CaseMetrics'))
const Timesketch = lazy(() => import('./pages/Timesketch'))
const Settings = lazy(() => import('./pages/Settings'))
const AIDecisions = lazy(() => import('./pages/AIDecisions'))
const Investigation = lazy(() => import('./pages/Investigation'))
const Analytics = lazy(() => import('./pages/Analytics'))
const Skills = lazy(() => import('./pages/Skills'))
const Orchestrator = lazy(() => import('./pages/Orchestrator'))
const BuilderTool = lazy(() => import('./pages/BuilderTool'))
const PromptsRepo = lazy(() => import('./pages/PromptsRepo'))
const ChatsHistory = lazy(() => import('./pages/ChatsHistory'))
const Clients = lazy(() => import('./pages/Clients'))
const Workbench = lazy(() => import('./pages/Workbench'))
const PortalHome = lazy(() => import('./pages/portal/Home'))
const PortalOperations = lazy(() => import('./pages/portal/Operations'))

const PageFallback = () => (
  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1, minHeight: 200 }}>
    <CircularProgress size={24} />
  </Box>
)

// Client-facing portal (Security Insights Platform, 2026-08-21): the admin
// app (MainLayout + all its nav items -- Clients registry, Workbench,
// Settings, etc.) is internal-staff-only. A role-client login has no
// business reason to reach any of it, and most of those routes carry no
// per-route permission check today (only cases/ai-decisions/workbench/
// settings/users do) -- gating every individual route would be a much
// larger, more error-prone change than one guard at the admin tree's root.
function AdminAreaGate() {
  const { user } = useAuth()
  if (user?.role_id === 'role-client') {
    return <Navigate to="/portal" replace />
  }
  return <MainLayout />
}

function App() {
  return (
    <AuthProvider>
      <SelectedClientProvider>
      <Box sx={{ display: 'flex', height: '100vh' }}>
        <Suspense fallback={<PageFallback />}>
        <Routes>
          {/* Public routes */}
          <Route path="/login" element={<Login />} />
          
          {/* Client-facing portal (Security Insights Platform, 2026-08-21) --
              its own layout/nav, separate from the internal admin app.
              Open to any authenticated user (an admin can preview it), but
              data returned by /api/portal/* is scoped to the caller's own
              client_id claim server-side, so a non-client user just sees an
              empty/unscoped view rather than anything sensitive. */}
          <Route
            path="/portal"
            element={
              <ProtectedRoute>
                <PortalLayout />
              </ProtectedRoute>
            }
          >
            <Route index element={<PortalHome />} />
            <Route path="operations" element={<PortalOperations />} />
          </Route>

          {/* Protected routes (internal admin app) */}
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <AdminAreaGate />
              </ProtectedRoute>
            }
          >
            <Route index element={<Dashboard />} />
            <Route
              path="cases"
              element={
                <ProtectedRoute requiredPermission="cases.read">
                  <Cases />
                </ProtectedRoute>
              }
            />
            <Route path="case-metrics" element={<CaseMetrics />} />
            <Route path="investigation" element={<Investigation />} />
            <Route path="timesketch" element={<Timesketch />} />
            <Route path="analytics" element={<Analytics />} />
            <Route
              path="clients"
              element={
                <ProtectedRoute requiredPermission="users.read">
                  <Clients />
                </ProtectedRoute>
              }
            />
            <Route path="analytics/cost" element={<Navigate to="/settings?tab=general" replace />} />
            <Route path="skills" element={<Skills />} />
            <Route path="prompts" element={<PromptsRepo />} />
            <Route path="chats" element={<ChatsHistory />} />
            <Route path="builder" element={<BuilderTool />} />
            <Route path="workflow-builder" element={<Navigate to="/builder" replace />} />
            <Route path="orchestrator" element={<Orchestrator />} />
            <Route
              path="ai-decisions"
              element={
                <ProtectedRoute requiredPermission="ai_decisions.approve">
                  <AIDecisions />
                </ProtectedRoute>
              }
            />
            <Route
              path="workbench"
              element={
                <ProtectedRoute requiredPermission="ai_decisions.approve">
                  <Workbench />
                </ProtectedRoute>
              }
            />
            <Route
              path="settings"
              element={
                <ProtectedRoute requiredPermission="settings.read">
                  <Settings />
                </ProtectedRoute>
              }
            />
            <Route
              path="users"
              element={
                <ProtectedRoute requiredPermission="users.read">
                  <Navigate to="/settings?tab=users" replace />
                </ProtectedRoute>
              }
            />
          </Route>
        </Routes>
        </Suspense>
      </Box>
      </SelectedClientProvider>
    </AuthProvider>
  )
}

export default App

