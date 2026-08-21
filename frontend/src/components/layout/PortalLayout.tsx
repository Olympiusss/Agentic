/**
 * PortalLayout — Client-facing Security Insights Platform shell.
 *
 * Deliberately separate from MainLayout (the internal admin app): a
 * role-client login has no business reason to see the admin nav rail
 * (Clients registry, Workbench, Settings, ...), so this is its own,
 * much smaller shell with just Home / Agentic Operations.
 */

import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Box, Tabs, Tab, Typography } from '@mui/material'
import UserMenu from '../auth/UserMenu'

const NAV_ITEMS = [
  { label: 'Home', path: '/portal' },
  { label: 'Agentic Operations', path: '/portal/operations' },
]

export default function PortalLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const activeIndex = NAV_ITEMS.findIndex((item) =>
    item.path === '/portal' ? location.pathname === '/portal' : location.pathname.startsWith(item.path)
  )

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', width: '100%', height: '100vh' }}>
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          px: 3,
          py: 1.5,
          borderBottom: 1,
          borderColor: 'divider',
        }}
      >
        <Box display="flex" alignItems="center" gap={4}>
          <Typography variant="h6" fontWeight={700}>Sentry Agentic</Typography>
          <Tabs value={activeIndex === -1 ? 0 : activeIndex} onChange={(_, i) => navigate(NAV_ITEMS[i].path)}>
            {NAV_ITEMS.map((item) => (
              <Tab key={item.path} label={item.label} />
            ))}
          </Tabs>
        </Box>
        <UserMenu />
      </Box>
      <Box sx={{ flex: 1, overflow: 'auto', p: 3 }}>
        <Outlet />
      </Box>
    </Box>
  )
}
