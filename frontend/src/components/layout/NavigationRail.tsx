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
  Menu,
  MenuItem,
  ListItemIcon as MenuItemIcon,
  Tooltip,
  Typography,
} from '@mui/material'
import {
  DashboardOutlined as DashboardIcon,
  SettingsOutlined as SettingsIcon,
  HistoryOutlined as HistoryIcon,
  AutoAwesomeOutlined as PromptsIcon,
  BusinessOutlined as ClientsIcon,
  ChevronLeft,
  ChevronRight,
  LightModeOutlined as LightModeIcon,
  DarkModeOutlined as DarkModeIcon,
  Brightness4Outlined as SystemModeIcon,
  Check as CheckIcon,
} from '@mui/icons-material'
import { useThemePreference, type ThemePreference } from '../../contexts/ThemeContext'

const COLLAPSED_WIDTH = 60
const EXPANDED_WIDTH = 220

// Brand palette
const NAV_BG    = '#0a1628'       // deep navy
const ACCENT    = '#1A6AFF'       // sentry blue
const WHITE     = '#ffffff'
const WHITE_DIM = 'rgba(255,255,255,0.55)'
const HOVER_BG  = 'rgba(26,106,255,0.14)'
const ACTIVE_BG = 'rgba(26,106,255,0.22)'

// Sentry Agentic Logo - corrected to match the reference design: a
// symmetric shield with three EQUAL-height vertical bars (the previous
// version had an asymmetric, center-bar-taller layout that drifted from
// spec -- this is the "design tampered with" fix). Shared markup with
// ClaudeDrawer's header logo so there's one canonical logo, not two.
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
      <clipPath id="navsg-clip">
        <path d="M50 4 L90 20 L90 60 Q90 90 50 106 Q10 90 10 60 L10 20 Z" />
      </clipPath>
    </defs>
    {/* Shield body -- symmetric outline */}
    <path d="M50 4 L90 20 L90 60 Q90 90 50 106 Q10 90 10 60 L10 20 Z" fill="url(#navsg-grad)" />
    {/* Inner edge */}
    <path d="M50 8 L86 22.5 L86 59 Q86 85 50 100 Q14 85 14 59 L14 22.5 Z"
      fill="none" stroke="rgba(120,170,255,0.3)" strokeWidth="1.5" />
    {/* Three equal-height bars, evenly spaced and centered */}
    <rect x="21" y="34" width="14" height="46" rx="7" fill="rgba(255,255,255,0.16)" />
    <rect x="21" y="34" width="14" height="46" rx="7" fill="none" stroke="rgba(255,255,255,0.7)" strokeWidth="1.2" />
    <rect x="43" y="34" width="14" height="46" rx="7" fill="rgba(255,255,255,0.16)" />
    <rect x="43" y="34" width="14" height="46" rx="7" fill="none" stroke="rgba(255,255,255,0.7)" strokeWidth="1.2" />
    <rect x="65" y="34" width="14" height="46" rx="7" fill="rgba(255,255,255,0.16)" />
    <rect x="65" y="34" width="14" height="46" rx="7" fill="none" stroke="rgba(255,255,255,0.7)" strokeWidth="1.2" />
    {/* Gloss highlight */}
    <path d="M50 8 L86 22.5 L86 40 C65 33 35 33 14 40 L14 22.5 Z"
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
  { id: 'dashboard', label: 'Dashboard',     icon: <DashboardIcon sx={{ fontSize: 20 }} />, path: '/' },
  { id: 'clients',   label: 'Clients',       icon: <ClientsIcon   sx={{ fontSize: 20 }} />, path: '/clients' },
  { id: 'chats',     label: 'Chats History', icon: <HistoryIcon   sx={{ fontSize: 20 }} />, path: '/chats' },
  { id: 'prompts',   label: 'Prompts Repo',  icon: <PromptsIcon   sx={{ fontSize: 20 }} />, path: '/prompts' },
  { id: 'settings',  label: 'Settings',      icon: <SettingsIcon  sx={{ fontSize: 20 }} />, path: '/settings' },
]

interface ThemeOption {
  value: ThemePreference
  label: string
  icon: React.ReactNode
}

const themeOptions: ThemeOption[] = [
  { value: 'light',  label: 'Light',   icon: <LightModeIcon sx={{ fontSize: 18 }} /> },
  { value: 'dark',   label: 'Dark',    icon: <DarkModeIcon sx={{ fontSize: 18 }} /> },
  { value: 'system', label: 'System',  icon: <SystemModeIcon sx={{ fontSize: 18 }} /> },
]

function ThemeSwitcher({ expanded }: { expanded: boolean }) {
  const { preference, setPreference } = useThemePreference()
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null)
  const open = Boolean(anchorEl)
  const current = themeOptions.find((o) => o.value === preference) || themeOptions[1]

  const handleSelect = (value: ThemePreference) => {
    setPreference(value)
    setAnchorEl(null)
  }

  const button = (
    <ListItemButton
      onClick={(e) => setAnchorEl(e.currentTarget)}
      sx={{
        minHeight: 40,
        justifyContent: expanded ? 'flex-start' : 'center',
        px: expanded ? 1.5 : 0,
        mx: 1,
        borderRadius: 2,
        '&:hover': { bgcolor: HOVER_BG },
      }}
    >
      <ListItemIcon sx={{ minWidth: expanded ? 32 : 'auto', color: WHITE_DIM }}>
        {current.icon}
      </ListItemIcon>
      {expanded && (
        <ListItemText
          primary={`Theme: ${current.label}`}
          primaryTypographyProps={{ fontSize: '0.82rem', fontWeight: 400, color: WHITE_DIM }}
        />
      )}
    </ListItemButton>
  )

  return (
    <>
      {expanded ? button : (
        <Tooltip title={`Theme: ${current.label}`} placement="right" arrow>
          {button}
        </Tooltip>
      )}
      <Menu
        anchorEl={anchorEl}
        open={open}
        onClose={() => setAnchorEl(null)}
        anchorOrigin={{ vertical: 'top', horizontal: 'right' }}
        transformOrigin={{ vertical: 'bottom', horizontal: 'left' }}
      >
        {themeOptions.map((opt) => (
          <MenuItem key={opt.value} selected={opt.value === preference} onClick={() => handleSelect(opt.value)}>
            <MenuItemIcon sx={{ minWidth: 32 }}>{opt.icon}</MenuItemIcon>
            <ListItemText primary={opt.label} />
            {opt.value === preference && <CheckIcon sx={{ fontSize: 16, ml: 1, color: ACCENT }} />}
          </MenuItem>
        ))}
      </Menu>
    </>
  )
}

export default function NavigationRail() {
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

      {/* --- Theme switcher --- */}
      <Box sx={{ py: 0.5, borderTop: '1px solid rgba(255,255,255,0.08)' }}>
        <ThemeSwitcher expanded={expanded} />
      </Box>

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
