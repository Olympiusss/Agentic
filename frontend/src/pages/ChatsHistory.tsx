/**
 * ChatsHistory - browse, rename, pin, share, and reopen recent chat
 * conversations.
 *
 * Reads and writes the same `claudeDrawerTabs` localStorage key
 * ClaudeDrawer already owns -- no separate storage system. Capped to the
 * 10 most recently active conversations (pinned ones are exempt from the
 * cap, enforced in ClaudeDrawer's own capTabsAt10).
 */
import { useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { Box, Typography, Paper, IconButton, Menu, MenuItem, ListItemIcon, ListItemText, TextField, Snackbar } from '@mui/material'
import {
  ChatBubbleOutline,
  ChevronRight,
  MoreVert,
  DriveFileRenameOutline,
  PushPin,
  PushPinOutlined,
  IosShare,
  DeleteOutline,
  Check,
  Close,
} from '@mui/icons-material'
import type { ChatTab, Message } from '../components/claude/ClaudeDrawer'

interface LayoutContext {
  openChatWithTab: (tabId: string) => void
}

const MAX_SHOWN = 10
const STORAGE_KEY = 'claudeDrawerTabs'

function sortForDisplay(list: ChatTab[]): ChatTab[] {
  return [...list].sort((a, b) => {
    if (!!a.isPinned !== !!b.isPinned) return a.isPinned ? -1 : 1
    return (b.lastUpdated ?? 0) - (a.lastUpdated ?? 0)
  })
}

function lastQuestionPreview(messages: Message[]): string {
  // The question asked, not the answer given -- shows the last thing the
  // user asked in this conversation, which is a far more useful "what was
  // this chat about" cue than the assistant's (often long) response text.
  const lastUserMsg = [...messages].reverse().find(m => m.role === 'user')
  if (!lastUserMsg) return 'No messages yet'
  if (typeof lastUserMsg.content === 'string') return lastUserMsg.content
  const textBlock = lastUserMsg.content.find(b => b.type === 'text' && b.text)
  return textBlock?.text || '[non-text content]'
}

function transcriptText(tab: ChatTab): string {
  return tab.messages.map(m => {
    const who = m.role === 'user' ? 'You' : 'Sentry Agentic'
    const body = typeof m.content === 'string'
      ? m.content
      : m.content.filter(b => b.type === 'text' && b.text).map(b => b.text).join('\n')
    return `${who}: ${body}`
  }).join('\n\n')
}

function relativeTime(ts?: number): string {
  if (!ts) return ''
  const diffMs = Date.now() - ts
  const mins = Math.round(diffMs / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  return `${days}d ago`
}

export default function ChatsHistory() {
  const { openChatWithTab } = useOutletContext<LayoutContext>()
  const [tabs, setTabs] = useState<ChatTab[]>([])
  const [menuAnchor, setMenuAnchor] = useState<{ el: HTMLElement; tabId: string } | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameText, setRenameText] = useState('')
  const [toast, setToast] = useState<string | null>(null)

  const loadFromStorage = () => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      if (saved) {
        const parsed: ChatTab[] = JSON.parse(saved)
        setTabs(sortForDisplay(parsed).slice(0, MAX_SHOWN))
      } else {
        setTabs([])
      }
    } catch { /* ignore malformed/missing localStorage data */ }
  }

  useEffect(() => { loadFromStorage() }, [])

  const mutateStorage = (updater: (all: ChatTab[]) => ChatTab[]) => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      const all: ChatTab[] = saved ? JSON.parse(saved) : []
      const updated = updater(all)
      localStorage.setItem(STORAGE_KEY, JSON.stringify(updated))
      setTabs(sortForDisplay(updated).slice(0, MAX_SHOWN))
    } catch { /* ignore storage errors */ }
  }

  const closeMenu = () => setMenuAnchor(null)

  const handlePinToggle = (tabId: string) => {
    mutateStorage(all => all.map(t => t.id === tabId ? { ...t, isPinned: !t.isPinned } : t))
    closeMenu()
  }

  const handleShare = (tab: ChatTab) => {
    closeMenu()
    navigator.clipboard.writeText(transcriptText(tab))
      .then(() => setToast('Conversation copied to clipboard'))
      .catch(() => setToast('Could not copy — clipboard access was blocked'))
  }

  const handleDelete = (tabId: string) => {
    closeMenu()
    if (!window.confirm('Delete this conversation? This cannot be undone.')) return
    mutateStorage(all => all.filter(t => t.id !== tabId))
  }

  const startRename = (tab: ChatTab) => {
    closeMenu()
    setRenamingId(tab.id)
    setRenameText(tab.title)
  }

  const saveRename = (tabId: string) => {
    const text = renameText.trim()
    setRenamingId(null)
    if (!text) return
    mutateStorage(all => all.map(t => t.id === tabId ? { ...t, title: text } : t))
  }

  return (
    <Box sx={{ width: '50%', minWidth: 480, maxWidth: 720 }}>
      {/* pr reserves room for the fixed top-right account avatar
          (MainLayout.tsx: top:12, right: TAB_WIDTH+12, ~48px wide) so the
          subtitle's right edge never sits under/behind it. */}
      <Box sx={{ mb: 3, display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', flexWrap: 'wrap', gap: 1, pr: '90px' }}>
        <Typography
          variant="h4"
          fontWeight={800}
          sx={{
            background: (t) => t.palette.mode === 'dark'
              ? 'linear-gradient(135deg, #5BA4FF 0%, #1A6AFF 100%)'
              : 'linear-gradient(135deg, #1A3FCC 0%, #1A6AFF 100%)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
          }}
        >
          Chats History
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Securely revisit your recent investigations, right where you left off.
        </Typography>
      </Box>

      {tabs.length === 0 ? (
        <Paper variant="outlined" sx={{ p: 4, textAlign: 'center', borderRadius: 2 }}>
          <ChatBubbleOutline sx={{ fontSize: 32, color: 'text.secondary', mb: 1 }} />
          <Typography variant="body2" color="text.secondary">
            No saved conversations yet -- start a chat and it'll show up here.
          </Typography>
        </Paper>
      ) : (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          {tabs.map((tab) => (
            <Paper
              key={tab.id}
              variant="outlined"
              sx={{
                p: 1.5,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                borderRadius: 2,
                borderColor: tab.isPinned ? 'primary.main' : undefined,
                transition: 'border-color 0.15s ease, background-color 0.15s ease',
                '&:hover': {
                  borderColor: 'primary.main',
                  bgcolor: (t) => t.palette.mode === 'dark' ? 'rgba(26,106,255,0.08)' : 'rgba(26,106,255,0.04)',
                },
              }}
            >
              {renamingId === tab.id ? (
                <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center', flex: 1 }}>
                  <TextField
                    size="small"
                    autoFocus
                    fullWidth
                    value={renameText}
                    onChange={(e) => setRenameText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') saveRename(tab.id)
                      if (e.key === 'Escape') setRenamingId(null)
                    }}
                  />
                  <IconButton size="small" onClick={() => saveRename(tab.id)}><Check sx={{ fontSize: 18 }} /></IconButton>
                  <IconButton size="small" onClick={() => setRenamingId(null)}><Close sx={{ fontSize: 18 }} /></IconButton>
                </Box>
              ) : (
                <>
                  <Box
                    sx={{ minWidth: 0, flex: 1, cursor: 'pointer' }}
                    onClick={() => openChatWithTab(tab.id)}
                  >
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      {tab.isPinned && <PushPin sx={{ fontSize: 14, color: 'primary.main' }} />}
                      <Typography variant="body2" fontWeight={600} noWrap sx={{ maxWidth: 300 }}>
                        {tab.title}
                      </Typography>
                    </Box>
                    <Typography variant="caption" color="text.secondary" noWrap sx={{ display: 'block', maxWidth: 500 }}>
                      {lastQuestionPreview(tab.messages)}
                    </Typography>
                  </Box>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flexShrink: 0, ml: 2 }}>
                    <Typography variant="caption" color="text.secondary">
                      {relativeTime(tab.lastUpdated)}
                    </Typography>
                    <IconButton size="small" onClick={(e) => { e.stopPropagation(); setMenuAnchor({ el: e.currentTarget, tabId: tab.id }) }}>
                      <MoreVert sx={{ fontSize: 18 }} />
                    </IconButton>
                    <ChevronRight sx={{ fontSize: 18, color: 'text.secondary', cursor: 'pointer' }} onClick={() => openChatWithTab(tab.id)} />
                  </Box>
                </>
              )}
            </Paper>
          ))}
        </Box>
      )}

      <Menu anchorEl={menuAnchor?.el} open={!!menuAnchor} onClose={closeMenu}>
        {menuAnchor && (() => {
          const tab = tabs.find(t => t.id === menuAnchor.tabId)
          if (!tab) return null
          return [
            <MenuItem key="rename" onClick={() => startRename(tab)}>
              <ListItemIcon><DriveFileRenameOutline fontSize="small" /></ListItemIcon>
              <ListItemText>Rename</ListItemText>
            </MenuItem>,
            <MenuItem key="pin" onClick={() => handlePinToggle(tab.id)}>
              <ListItemIcon>{tab.isPinned ? <PushPin fontSize="small" /> : <PushPinOutlined fontSize="small" />}</ListItemIcon>
              <ListItemText>{tab.isPinned ? 'Unpin' : 'Pin'}</ListItemText>
            </MenuItem>,
            <MenuItem key="share" onClick={() => handleShare(tab)}>
              <ListItemIcon><IosShare fontSize="small" /></ListItemIcon>
              <ListItemText>Share</ListItemText>
            </MenuItem>,
            <MenuItem key="delete" onClick={() => handleDelete(tab.id)} sx={{ color: 'error.main' }}>
              <ListItemIcon><DeleteOutline fontSize="small" color="error" /></ListItemIcon>
              <ListItemText>Delete</ListItemText>
            </MenuItem>,
          ]
        })()}
      </Menu>

      <Snackbar
        open={!!toast}
        autoHideDuration={2500}
        onClose={() => setToast(null)}
        message={toast}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      />
    </Box>
  )
}
