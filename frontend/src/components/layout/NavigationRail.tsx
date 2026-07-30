/**
 * NavigationRail - Sentry Agentic SOC
 * Brand: Deep navy sidebar, white text/icons, blue accents.
 * Icons: outlined (lighter weight).
 * Nav: Dashboard (renamed Sentry Agentic) + Settings only.
 */

import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  Box,
  IconButton,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Tooltip,
  Typography,
  alpha,
} from '@mui/material'
import {
  DashboardOutlined as DashboardIcon,
  SettingsOutlined as SettingsIcon,
  ChatOutlined as ChatIcon,
  ChevronLeft,
  ChevronRight,
} from '@mui/icons-material'
import UserMenu from '../auth/UserMenu'

const COLLAPSED_WIDTH = 60
const EXPANDED_WIDTH = 220

// Brand palette
const NAV_BG    = '#0a1628'       // deep navy
const ACCENT    = '#1A6AFF'       // sentry blue
const WHITE     = '#ffffff'
const WHITE_DIM = 'rgba(255,255,255,0.55)'
const HOVER_BG  = 'rgba(26,106,255,0.14)'
const ACTIVE_BG = 'rgba(26,106,255,0.22)'

// Sentry Agentic Logo - 3D glassmorphic shield
const SentryLogoSmall = () => (
  <svg width="26" height="29" viewBox="0 0 100 110" fill="none" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <linearGradient id="navsg-grad" x1="15" y1="0" x2="85" y2="110" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stopColor="#2D6FFF" />
        <stop offset="45%" stopColor="#1A4FE8" />
        <stop offset="100%" stopColor="#0A1E7A" />
      </linearGradient>
      <linearGradient id="navsg-gloss" x1="10" y1="0" x2="60" y2="50" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stopColor="rgba(255,255,255,0.38)" />
        <stop offset="100%" stopColor="rgba(255,255,255,0)" />
      </linearGradient>
      <filter id="navsg-glow" x="-20%" y="-15%" width="140%" height="140%">
        <feGaussianBlur stdDeviation="2.5" result="g" />
        <feMerge><feMergeNode in="g" /><feMergeNode in="SourceGraphic" /></feMerge>
      </filter>
      <clipPath id="navsg-clip">
        <path d="M50 3 L95 20 L95 62 C95 88 50 107 50 107 C50 107 5 88 5 62 L5 20 Z" />
      </clipPath>
    </defs>
    {/* Glow halo */}
    <path d="M50 3 L95 20 L95 62 C95 88 50 107 50 107 C50 107 5 88 5 62 L5 20 Z"
      fill="rgba(26,106,255,0.28)" filter="url(#navsg-glow)" />
    {/* Shield body */}
    <path d="M50 3 L95 20 L95 62 C95 88 50 107 50 107 C50 107 5 88 5 62 L5 20 Z"
      fill="url(#navsg-grad)" />
    {/* Inner edge */}
    <path d="M50 7 L91 23 L91 62 C91 85 50 103 50 103 C50 103 9 85 9 62 L9 23 Z"
      fill="none" stroke="rgba(120,170,255,0.3)" strokeWidth="1.5" />
    {/* Left bar */}
    <rect x="21" y="42" width="14" height="42" rx="7" fill="rgba(255,255,255,0.14)" />
    <rect x="21" y="42" width="14" height="42" rx="7" fill="none" stroke="rgba(255,255,255,0.68)" strokeWidth="1.2" />
    <rect x="23" y="44" width="6" height="12" rx="3" fill="rgba(255,255,255,0.42)" />
    {/* Center bar */}
    <rect x="43" y="32" width="14" height="52" rx="7" fill="rgba(255,255,255,0.14)" />
    <rect x="43" y="32" width="14" height="52" rx="7" fill="none" stroke="rgba(255,255,255,0.72)" strokeWidth="1.2" />
    <rect x="45" y="34" width="6" height="14" rx="3" fill="rgba(255,255,255,0.48)" />
    {/* Right bar */}
    <rect x="65" y="42" width="14" height="42" rx="7" fill="rgba(255,255,255,0.14)" />
    <rect x="65" y="42" width="14" height="42" rx="7" fill="none" stroke="rgba(255,255,255,0.68)" strokeWidth="1.2" />
    <rect x="67" y="44" width="6" height="12" rx="3" fill="rgba(255,255,255,0.42)" />
    {/* Gloss highlight */}
    <path d="M50 7 L91 23 L91 44 C70 37 30 37 9 44 L9 23 Z"
      fill="url(#navsg-gloss)" clipPath="url(#navsg-clip)" />
  </svg>
)

interface NavItem {
  id: string
  label: string
  icon: React.ReactNode
  path: string
}

const navItems: NavItem[] = [
  { id: 'dashboard', label: 'Dashboard', icon: <DashboardIcon sx={{ fontSize: 20 }} />, path: '/' },
  { id: 'settings',  label: 'Settings',        icon: <SettingsIcon  sx={{ fontSize: 20 }} />, path: '/settings' },
]

interface NavigationRailProps {
  enabledIntegrations?: string[]
  onOpenChat?: () => void
  chatOpen?: boolean
}

export default function NavigationRail({ onOpenChat, chatOpen = false }: NavigationRailProps) {
  const [expanded, setExpanded] = useState(false)
  const navigate  = useNavigate()
  const location  = useLocation()
  const width     = expanded ? EXPANDED_WIDTH : COLLAPSED_WIDTH

  return (
    <Box
      sx={{
        width,
        minWidth: width,
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        bgcolor: NAV_BG,
        transition: 'width 0.25s ease',
        overflow: 'hidden',
        position: 'fixed',
        left: 0,
        top: 0,
        zIndex: 1200,
        boxShadow: '2px 0 24px rgba(0,0,0,0.35)',
      }}
    >
      {/* --- Logo + brand --- */}
      <Box sx={{ px: 1.5, py: 2, display: 'flex', alignItems: 'center', justifyContent: expanded ? 'space-between' : 'center', minHeight: 64 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.2 }}>
          <Box sx={{ flexShrink: 0, display: 'flex', alignItems: 'center' }}>
            <SentryLogoSmall />
          </Box>
          {expanded && (
            <Box>
              <Typography sx={{ fontWeight: 700, fontSize: '13px', color: WHITE, whiteSpace: 'nowrap', letterSpacing: '-0.01em', lineHeight: 1.1 }}>
                Sentry Agentic
              </Typography>
              <Typography sx={{ fontSize: '9px', fontWeight: 700, color: ACCENT, letterSpacing: '2.5px', mt: '1px' }}>
                SOC
              </Typography>
            </Box>
          )}
        </Box>
        {expanded && <UserMenu />}
      </Box>

      {/* --- Chat button --- */}
      <Box sx={{ px: 1, pb: 0.5 }}>
        {expanded ? (
          <ListItemButton
            onClick={onOpenChat}
            sx={{
              minHeight: 40, px: 1.5, borderRadius: 2,
              bgcolor: chatOpen ? ACTIVE_BG : HOVER_BG,
              '&:hover': { bgcolor: ACTIVE_BG },
            }}
          >
            <ListItemIcon sx={{ minWidth: 34, color: ACCENT }}>
              <ChatIcon sx={{ fontSize: 20 }} />
            </ListItemIcon>
            <ListItemText
              primary="Sentry Chat"
              primaryTypographyProps={{ fontSize: '0.82rem', fontWeight: 600, color: ACCENT }}
            />
          </ListItemButton>
        ) : (
          <Tooltip title="Sentry Chat" placement="right" arrow>
            <IconButton
              onClick={onOpenChat}
              sx={{
                width: '100%', borderRadius: 2, py: 1,
                color: ACCENT,
                bgcolor: chatOpen ? ACTIVE_BG : 'transparent',
                '&:hover': { bgcolor: HOVER_BG },
              }}
            >
              <ChatIcon sx={{ fontSize: 20 }} />
            </IconButton>
          </Tooltip>
        )}
      </Box>

      {/* Thin separator */}
      <Box sx={{ mx: 1.5, my: 0.5, height: '1px', bgcolor: 'rgba(255,255,255,0.08)' }} />

      {/* --- Nav items --- */}
      <List sx={{ flex: 1, py: 0.5 }}>
        {navItems.map((item) => {
          const isActive = location.pathname === item.path
          const btn = (
            <ListItemButton
              key={item.id}
              selected={isActive}
              onClick={() => navigate(item.path)}
              sx={{
                minHeight: 40,
                justifyContent: expanded ? 'flex-start' : 'center',
                px: expanded ? 1.5 : 0,
                mx: 1,
                borderRadius: 2,
                '&.Mui-selected': {
                  bgcolor: ACTIVE_BG,
                  '& .MuiListItemIcon-root': { color: ACCENT },
                  '& .MuiListItemText-primary': { color: WHITE, fontWeight: 600 },
                },
                '&:hover': { bgcolor: HOVER_BG },
              }}
            >
              <ListItemIcon sx={{ minWidth: expanded ? 32 : 'auto', color: isActive ? ACCENT : WHITE_DIM }}>
                {item.icon}
              </ListItemIcon>
              {expanded && (
                <ListItemText
                  primary={item.label}
                  primaryTypographyProps={{ fontSize: '0.82rem', fontWeight: isActive ? 600 : 400, color: isActive ? WHITE : WHITE_DIM }}
                />
              )}
            </ListItemButton>
          )

          return expanded ? btn : (
            <Tooltip key={item.id} title={item.label} placement="right" arrow>
              {btn}
            </Tooltip>
          )
        })}
      </List>

      {/* --- Collapse toggle --- */}
      <Box sx={{ px: 1, py: 1, borderTop: '1px solid rgba(255,255,255,0.08)' }}>
        <IconButton
          onClick={() => setExpanded(!expanded)}
          sx={{
            width: '100%', borderRadius: 2, py: 0.75,
            color: WHITE_DIM,
            '&:hover': { bgcolor: HOVER_BG, color: WHITE },
          }}
        >
          {expanded ? <ChevronLeft sx={{ fontSize: 18 }} /> : <ChevronRight sx={{ fontSize: 18 }} />}
        </IconButton>
      </Box>
    </Box>
  )
}

export { COLLAPSED_WIDTH, EXPANDED_WIDTH }
