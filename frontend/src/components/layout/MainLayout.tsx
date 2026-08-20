/**
 * MainLayout - Sentry Agentic SOC
 *
 * Layout architecture:
 *  [NAV 60px] [Main Content] [Chat Panel 0 or 390px] [Permanent Tab 36px]
 *
 * The blue tab is ALWAYS fixed to the right edge of the screen.
 * Clicking it toggles the chat panel open/closed.
 * Main content always fills the remaining space -- never hidden under chat.
 */

import { useState, useEffect } from 'react'
import { Outlet } from 'react-router-dom'
import { Box, Tooltip, Typography } from '@mui/material'
import { Chat as ChatIcon, ChevronLeft, ChevronRight } from '@mui/icons-material'
import NavigationRail, { COLLAPSED_WIDTH } from './NavigationRail'
import ClaudeDrawer from '../claude/ClaudeDrawer'
import UserMenu from '../auth/UserMenu'
import ClientSelector from './ClientSelector'
import { useSelectedClient } from '../../contexts/SelectedClientContext'

const CHAT_WIDTH = 390   // chat panel when open
const TAB_WIDTH  = 34    // permanent right-edge tab

export default function MainLayout() {
  const { isLocked } = useSelectedClient()
  // Chat starts closed -- user opens via the permanent tab
  const [chatOpen, setChatOpen] = useState(false)
  const [investigationData, setInvestigationData] = useState<{
    messages: Array<{ role: 'user' | 'assistant'; content: string }>
    agentId: string
    title: string
  } | null>(null)
  // Prompts Repo (post-Phase-2): pre-fills a new chat tab's input without
  // sending -- confirmed behavior, distinct from handleInvestigate's
  // auto-send. `key` increments per call so clicking the same prompt twice
  // in a row still opens a fresh tab (ClaudeDrawer keys its effect off it).
  const [pendingDraft, setPendingDraft] = useState<{ text: string; key: number } | null>(null)
  // Chats History (post-Phase-2): reopen an existing saved tab by id.
  const [pendingTabId, setPendingTabId] = useState<string | null>(null)

  // Auto-open chat on first login to announce it. Previously force-closed
  // itself again 3.5s later unconditionally -- confirmed bug (2026-08-05):
  // that unmounted ClaudeDrawer regardless of what the user was doing
  // (mid-typing, about to click Send), and the unmount's tabs-persist
  // effect wrote an empty tabs array to localStorage since the untouched
  // "Chat 1" tab had zero messages -- poisoning the NEXT chat open into a
  // permanently empty `tabs` state (see ClaudeDrawer.tsx's
  // loadPersistedData, and handleSend's silent throw on
  // tabs[currentTab].messages). The user closes it themselves via the
  // existing tab/close controls now.
  useEffect(() => {
    setChatOpen(true)
  }, [])

  const handleInvestigate = (_id: string, agentId: string, prompt: string, title: string) => {
    setInvestigationData({ messages: [{ role: 'user' as const, content: prompt }], agentId, title })
    setChatOpen(true)
  }

  const openChatWithDraft = (text: string) => {
    setPendingDraft(prev => ({ text, key: (prev?.key ?? 0) + 1 }))
    setChatOpen(true)
  }

  const openChatWithTab = (tabId: string) => {
    setPendingTabId(tabId)
    setChatOpen(true)
  }

  const toggleChat  = () => setChatOpen(v => !v)
  const handleClose = () => {
    setChatOpen(false)
    setInvestigationData(null)
    setPendingDraft(null)
    setPendingTabId(null)
  }
  const handleCollapse = () => setChatOpen(false)

  // Main content width = viewport - nav - tab - (chat if open)
  const chatPanelW = chatOpen ? CHAT_WIDTH : 0
  const mainWidth  = `calc(100vw - ${COLLAPSED_WIDTH}px - ${TAB_WIDTH}px - ${chatPanelW}px)`

  return (
    <Box sx={{
      display: 'flex', height: '100vh', overflow: 'hidden',
      bgcolor: 'background.default', position: 'relative',
    }}>
      {/* Left navigation rail */}
      <NavigationRail />

      {/* Account menu + client selector -- always visible top-right, not
          hidden inside the collapsible nav rail (post-Phase-2 fix). Offset
          left of the permanent chat tab so they never overlap in the
          closed state. The client selector deliberately stays visible even
          while chat is open (losing client context every time you open
          chat would be disruptive) -- only UserMenu hides then, since it
          would otherwise sit on top of/inside the chat panel's own header,
          the panel opening into this exact screen region. Client selector
          never renders for role-client users (locked to their own org --
          see SelectedClientContext's isLocked). */}
      <Box sx={{ position: 'fixed', top: 12, right: TAB_WIDTH + 12, zIndex: 1301, display: 'flex', gap: 1, alignItems: 'center' }}>
        {!isLocked && <ClientSelector />}
        {!chatOpen && <UserMenu />}
      </Box>

      {/* Main page content -- always sized to exactly fill remaining space */}
      <Box
        component="main"
        sx={{
          ml: `${COLLAPSED_WIDTH}px`,
          width: mainWidth,
          maxWidth: mainWidth,
          height: '100vh',
          display: 'flex',
          flexDirection: 'column',
          minWidth: 0,
          transition: 'width 0.3s cubic-bezier(0.4,0,0.2,1), max-width 0.3s cubic-bezier(0.4,0,0.2,1)',
          overflow: 'hidden',
        }}
      >
        <Box sx={{ flex: 1, p: 3, pt: 2, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'auto' }}>
          <Outlet context={{ handleInvestigate, openChatWithDraft, openChatWithTab }} />
        </Box>
      </Box>

      {/* Chat panel -- slides in from the right, sits LEFT of the permanent tab */}
      <Box sx={{
        position: 'fixed',
        top: 0,
        right: TAB_WIDTH,
        width: chatOpen ? CHAT_WIDTH : 0,
        height: '100vh',
        zIndex: 1200,
        overflow: 'hidden',
        transition: 'width 0.3s cubic-bezier(0.4,0,0.2,1)',
        boxShadow: chatOpen ? '-8px 0 32px rgba(0,0,0,0.5)' : 'none',
      }}>
        {chatOpen && (
          <ClaudeDrawer
            open={chatOpen}
            onClose={handleClose}
            onCollapse={handleCollapse}
            initialMessages={investigationData?.messages}
            initialAgentId={investigationData?.agentId}
            initialTitle={investigationData?.title}
            initialDraftText={pendingDraft?.text}
            initialDraftKey={pendingDraft?.key}
            initialActiveTabId={pendingTabId ?? undefined}
            fullScreen={false}
            panelMode
          />
        )}
      </Box>

      {/* PERMANENT tab -- always visible on the far right edge */}
      <Tooltip
        title={chatOpen ? 'Close Chat' : 'Sentry Chat'}
        placement="left"
        arrow
      >
        <Box
          onClick={toggleChat}
          sx={{
            position: 'fixed',
            top: 0,
            right: 0,
            width: TAB_WIDTH,
            height: '100vh',
            zIndex: 1300,
            cursor: 'pointer',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 1,
            background: chatOpen
              ? 'linear-gradient(180deg, #1133e8 0%, #0a1e8a 100%)'
              : 'linear-gradient(180deg, #1A6AFF 0%, #1133e8 100%)',
            boxShadow: '-3px 0 16px rgba(26,106,255,0.45)',
            borderLeft: '1px solid rgba(255,255,255,0.1)',
            '&:hover': {
              background: 'linear-gradient(180deg, #3D88FF 0%, #1A6AFF 100%)',
            },
            transition: 'background 0.2s ease',
            userSelect: 'none',
          }}
        >
          {/* Vertical "CHAT" label */}
          <Typography sx={{
            color: 'rgba(255,255,255,0.85)',
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: '2.5px',
            writingMode: 'vertical-rl',
            textOrientation: 'mixed',
            transform: 'rotate(180deg)',
            textTransform: 'uppercase',
            fontFamily: '"Inter", sans-serif',
          }}>
            Chat
          </Typography>

          <ChatIcon sx={{ color: '#fff', fontSize: 16 }} />

          {/* Arrow direction changes with state */}
          {chatOpen
            ? <ChevronRight sx={{ color: 'rgba(255,255,255,0.7)', fontSize: 14 }} />
            : <ChevronLeft sx={{ color: 'rgba(255,255,255,0.7)', fontSize: 14 }} />
          }
        </Box>
      </Tooltip>
    </Box>
  )
}
