import { useState, useRef, useEffect, useMemo } from 'react'
import {
  Drawer,
  Box,
  Typography,
  TextField,
  Button,
  IconButton,
  CircularProgress,
  Tabs,
  Tab,
  Collapse,
  FormControl,
  Select,
  MenuItem,
  Menu,
  Chip,
  LinearProgress,
  List,
  ListItem,
  ListItemText,
  ListItemSecondaryAction,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Tooltip,
  ClickAwayListener,
  Switch,
  alpha,
  useTheme,
} from '@mui/material'
import {
  Send as SendIcon,
  Add as AddIcon,
  Close as CloseIcon,
  Settings as SettingsIcon,
  AttachFile as AttachFileIcon,
  Image as ImageIcon,
  Delete as DeleteIcon,
  CheckCircle as CheckCircleIcon,
  Error as ErrorIcon,
  Info as InfoIcon,
  Refresh as RefreshIcon,
  Compress as CompressIcon,
  Warning as WarningIcon,
  ExpandMore as ExpandMoreIcon,
  ExpandLess as ExpandLessIcon,
  Save as SaveIcon,
  Edit as EditIcon,
  Check as CheckIcon,
} from '@mui/icons-material'
import {
  claudeApi,
  agentsApi,
  mcpApi,
  reasoningApi,
  analyticsApi,
  type CostEstimate,
} from '../../services/api'
import { notificationService } from '../../services/notifications'
import { createLogger } from '../../services/logger'
import { useAuth } from '../../contexts/AuthContext'

const logger = createLogger('ClaudeDrawer')

export interface ContentBlock {
  type: 'text' | 'image' | 'thinking'
  text?: string
  source?: { type: 'base64'; media_type: string; data: string }
}

export interface Message {
  role: 'user' | 'assistant'
  content: string | ContentBlock[]
  // Per-message token usage (post-Phase-2): only assistant messages that
  // actually called the model carry this -- deterministic SentinelOne
  // recipe answers spend zero LLM tokens and legitimately have none.
  usage?: { input_tokens: number; output_tokens: number }
}

export interface ChatTab {
  id: string
  title: string
  messages: Message[]
  investigationKey?: string
  // Chats History (post-Phase-2): stamped whenever this tab's messages
  // change. Drives both the History page's "recent" ordering and the
  // 10-tab cap's LRU eviction.
  lastUpdated?: number
  // Chats History (post-Phase-2): pinned conversations are exempt from the
  // 10-tab LRU cap and sort first in the History list.
  isPinned?: boolean
}

interface ClaudeDrawerProps {
  open: boolean
  onClose: () => void
  onCollapse?: () => void   // minimise to floating tab
  initialMessages?: Message[]
  initialAgentId?: string
  initialTitle?: string
  // Prompts Repo (post-Phase-2): pre-fills a new tab's input without
  // sending. initialDraftKey must change (parent increments a counter) for
  // the same text to trigger a fresh tab on repeated clicks.
  initialDraftText?: string
  initialDraftKey?: number
  // Chats History (post-Phase-2): open directly to this existing tab id.
  initialActiveTabId?: string
  fullScreen?: boolean
  panelMode?: boolean       // right-side panel (not fullscreen overlay)
}

const MAX_HISTORY_TABS = 10

interface Agent {
  id: string
  name: string
  description: string
  icon?: string
  color?: string
  specialization?: string
}

interface AttachedFile {
  name: string
  type: 'image' | 'text' | 'file'
  data: string
  media_type?: string
}

export default function ClaudeDrawer({ open, onClose, onCollapse, initialMessages, initialAgentId, initialTitle, initialDraftText, initialDraftKey, initialActiveTabId, fullScreen = false, panelMode = false }: ClaudeDrawerProps) {
  const theme = useTheme()
  const { user } = useAuth()

  const stripThinkingBlocks = (messages: Message[]): Message[] => {
    return messages.map(msg => {
      if (msg.role === 'assistant' && Array.isArray(msg.content)) {
        const filtered = msg.content.filter((b: any) => b.type !== 'thinking')
        if (filtered.length === 0) return { ...msg, content: '' }
        return { ...msg, content: filtered }
      }
      return msg
    }).filter(msg => !(msg.role === 'assistant' && msg.content === ''))
  }

  const loadPersistedData = () => {
    // Chats History (post-Phase-2): if asked to open a specific saved tab,
    // jump straight to it -- the one deliberate way to bring a previous
    // conversation back into the tab bar.
    if (initialActiveTabId) {
      try {
        const savedTabs = localStorage.getItem('claudeDrawerTabs')
        if (savedTabs) {
          const parsed = JSON.parse(savedTabs)
          if (Array.isArray(parsed) && parsed.length > 0) {
            const idx = parsed.findIndex((t: ChatTab) => t.id === initialActiveTabId)
            if (idx !== -1) return { tabs: parsed, currentTab: idx }
          }
        }
      } catch { /* Ignore localStorage errors, fall through to a fresh tab */ }
    }
    // Every other open -- fresh login, reopening the drawer, a normal page
    // reload -- always starts on exactly one new, empty tab (confirmed
    // behavior: "It should only display a new tab and not previous chats.
    // Previous chats can be accessed via chat history"). Previously-saved
    // conversations are never auto-restored into the tab bar; they live
    // untouched in claudeDrawerTabs and stay reachable only via Chats
    // History (the branch above). The persist effect below merges into
    // that archive rather than overwriting it wholesale, so starting fresh
    // here never loses history.
    return { tabs: [{ id: `${Date.now()}`, title: 'New Chat', messages: [] }], currentTab: 0 }
  }

  const loadPersistedSettings = () => {
    try {
      const saved = localStorage.getItem('claudeDrawerSettings')
      if (saved) {
        const parsed = JSON.parse(saved)
        logger.debug('Settings loaded', parsed)
        return parsed
      }
    } catch (e) {
      logger.error('Failed to load settings', e)
    }
    return {
      model: 'claude-haiku-4-5-20251001', 
      maxTokens: 4096, 
      systemPrompt: '', 
      selectedAgent: '',
      enableThinking: false,
      thinkingBudget: 10000
    }
  }

  const persisted = loadPersistedData()
  const settings = loadPersistedSettings()
  
  const [tabs, setTabs] = useState<ChatTab[]>(persisted.tabs)
  const [currentTab, setCurrentTab] = useState(persisted.currentTab)
  const [lastInvestigationId, setLastInvestigationId] = useState<string | null>(null)
  const [lastDraftKey, setLastDraftKey] = useState<number | null>(null)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [model, setModel] = useState(settings.model)
  const [maxTokens, setMaxTokens] = useState(settings.maxTokens)
  const [enableThinking, setEnableThinking] = useState<boolean>(settings.enableThinking ?? false)
  const [thinkingBudget, setThinkingBudget] = useState<number>(settings.thinkingBudget ?? 10000)
  const [systemPrompt, setSystemPrompt] = useState(settings.systemPrompt)
  const [agents, setAgents] = useState<Agent[]>([])
  const [selectedAgent, setSelectedAgent] = useState<string>(settings.selectedAgent)
  const [agentInfoDialogOpen, setAgentInfoDialogOpen] = useState(false)
  const [models, setModels] = useState<any[]>([])
  const [attachedFiles, setAttachedFiles] = useState<AttachedFile[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [mcpStatus, setMcpStatus] = useState<{ available: number; total: number } | null>(null)
  const [estimatedTokens, setEstimatedTokens] = useState(0)
  // #184 Phase 2: pre-call USD estimate from /api/analytics/estimate-cost.
  // Replaces the old client-side length/4 heuristic — that gave us tokens
  // but no cost band, and undercounted multimodal/tool-call payloads.
  const [costEstimate, setCostEstimate] = useState<CostEstimate | null>(null)
  const [streamingThinking, setStreamingThinking] = useState<string>('')
  const [isThinking, setIsThinking] = useState(false)
  const [streamingText, setStreamingText] = useState<string>('')
  const [summarizing, setSummarizing] = useState(false)
  // GH #79 — Reasoning trace state
  const [sessionSummary, setSessionSummary] = useState<{
    total_interactions: number
    total_cost_usd: number
    total_input_tokens: number
    total_output_tokens: number
  } | null>(null)
  const [collapsedThinking, setCollapsedThinking] = useState<Record<string, boolean>>({})
  const messagesEndRef = useRef<HTMLDivElement>(null)
  // Edit-and-resend (post-Phase-2): editing a sent message discards
  // everything after it and re-sends the edited text as a fresh turn.
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [editingText, setEditingText] = useState('')
  // Save Chat format picker (post-Phase-2): replaces the old separate
  // "Export chat" (.txt) button and "Generate PDF report" icon with one
  // menu offering both.
  const [saveMenuAnchor, setSaveMenuAnchor] = useState<HTMLElement | null>(null)

  // Personalized greeting for an empty chat tab (post-Phase-2), same
  // pattern already used on the Dashboard (frontend/src/pages/Dashboard.tsx).
  const greeting = useMemo(() => {
    const firstName = user?.full_name ? user.full_name.split(' ')[0] : (user?.username || 'there')
    return `Hi ${firstName}, how may I assist you today?`
  }, [user])

  const scrollToBottom = () => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })

  useEffect(() => { scrollToBottom() }, [tabs, currentTab])
  // Only persist tabs that actually hold a conversation -- an untouched
  // "New Chat" is not a real chat, it's an open tab, and shouldn't survive
  // a reload/re-login or show up in Chats History (confirmed behavior,
  // post-Phase-3 fix). Since loadPersistedData() above now always starts a
  // normal open on a single fresh tab (never the restored archive), this
  // MERGES this session's open tabs into whatever is already archived in
  // localStorage rather than overwriting it outright -- overwriting would
  // wipe every previously-saved conversation the instant the drawer
  // mounts, since a brand-new tab has zero messages. Archived tabs that
  // aren't currently open this session survive untouched; any tab
  // (archived or open) with zero messages is dropped, same rule as before.
  // currentTab is re-derived against the merged list (by tab id, not raw
  // index) so the persisted pointer never drifts.
  useEffect(() => {
    try {
      const nonEmptyOpenTabs = tabs.filter(t => t.messages.length > 0)
      const openIds = new Set(nonEmptyOpenTabs.map(t => t.id))
      const savedRaw = localStorage.getItem('claudeDrawerTabs')
      const archive: ChatTab[] = savedRaw ? JSON.parse(savedRaw) : []
      const untouchedArchive = archive.filter(t => !openIds.has(t.id) && t.messages.length > 0)
      const merged = [...untouchedArchive, ...nonEmptyOpenTabs]
      localStorage.setItem('claudeDrawerTabs', JSON.stringify(merged))
      const activeTab = tabs[currentTab]
      const idxInPersisted = activeTab ? merged.findIndex(t => t.id === activeTab.id) : -1
      const persistedCurrentTab = idxInPersisted >= 0 ? idxInPersisted : Math.max(0, merged.length - 1)
      localStorage.setItem('claudeDrawerCurrentTab', String(persistedCurrentTab))
    } catch { /* ignore */ }
  }, [tabs, currentTab])

  // Debug logging for messages (only in development)
  useEffect(() => {
    if (tabs[currentTab] && import.meta.env.DEV) {
      logger.debug('Messages updated', {
        tabId: tabs[currentTab].id,
        messageCount: tabs[currentTab].messages.length
      })
    }
  }, [tabs, currentTab])

  // GH #79 — load reasoning-trace summary when switching tabs
  useEffect(() => {
    const sid = tabs[currentTab]?.id
    if (!sid) { setSessionSummary(null); return }
    reasoningApi.getSessionSummary(sid)
      .then(s => setSessionSummary({
        total_interactions: s.total_interactions,
        total_cost_usd: s.total_cost_usd,
        total_input_tokens: s.total_input_tokens,
        total_output_tokens: s.total_output_tokens,
      }))
      .catch(() => setSessionSummary(null))
  }, [currentTab, tabs])

  const toggleThinking = (key: string) => {
    setCollapsedThinking(prev => ({ ...prev, [key]: !prev[key] }))
  }

  useEffect(() => {
    try {
      const settingsToSave = {
        model, 
        maxTokens,
        enableThinking,
        thinkingBudget,
        systemPrompt, 
        selectedAgent
      }
      localStorage.setItem('claudeDrawerSettings', JSON.stringify(settingsToSave))
      logger.debug('Settings saved', settingsToSave)
    } catch (e) {
      logger.error('Failed to save settings', e)
    }
  }, [model, maxTokens, enableThinking, thinkingBudget, systemPrompt, selectedAgent])

  useEffect(() => {
    if (open) {
      agentsApi.listAgents().then(res => setAgents(res.data.agents || [])).catch(() => {})
      claudeApi.getModels().then(res => setModels(res.data.models || [])).catch(() => {})
      mcpApi.getStatuses().then(res => {
        const statuses = res.data.statuses || []
        const available = statuses.filter((s: any) => s.status && s.status !== 'error' && s.status !== 'not found').length
        setMcpStatus({ available, total: statuses.length })
      }).catch(() => {})
    }
  }, [open])

  useEffect(() => {
    const investigationId = initialMessages && initialAgentId ? `${initialAgentId}-${JSON.stringify(initialMessages)}` : null
    if (open && initialMessages?.length && initialAgentId && investigationId !== lastInvestigationId) {
      setLastInvestigationId(investigationId)
      let findingId = ''
      const content = typeof initialMessages[0]?.content === 'string' ? initialMessages[0].content : ''
      const match = content.match(/f-\d{8}-[a-f0-9]{8}/i)
      if (match) findingId = match[0]
      const key = findingId ? `${findingId}-${initialAgentId}` : null
      const existingIdx = key ? tabs.findIndex(t => t.investigationKey === key) : -1
      if (existingIdx !== -1) {
        setCurrentTab(existingIdx)
        setSelectedAgent(initialAgentId)
        return
      }
      const newTab: ChatTab = { id: `inv-${Date.now()}`, title: initialTitle || 'Investigation', messages: initialMessages, investigationKey: key || undefined }
      setTabs(prev => [...prev, newTab])
      setCurrentTab(tabs.length)
      setSelectedAgent(initialAgentId)
      setLoading(true)
      setStreamingThinking('')
      setStreamingText('')
      setIsThinking(false)
      setTimeout(async () => {
        try {
          logger.investigate('Starting auto-investigation (streaming)', {
            agentId: initialAgentId,
            messageCount: initialMessages.length
          })

          const response = await fetch('/api/claude/chat/stream', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Accept': 'text/event-stream',
            },
            body: JSON.stringify({
              messages: initialMessages,
              model: model || 'claude-haiku-4-5-20251001',
              max_tokens: maxTokens,
              enable_thinking: enableThinking,
              thinking_budget: enableThinking ? thinkingBudget : undefined,
              agent_id: initialAgentId,
            }),
          })

          if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`)

          const reader = response.body?.getReader()
          const decoder = new TextDecoder()
          const thinkingContent: ContentBlock[] = []
          const textContent: ContentBlock[] = []
          let currentThinking = ''
          let currentText = ''

          if (reader) {
            try {
              while (true) {
                const { done, value } = await reader.read()
                if (done) break
                const chunk = decoder.decode(value)
                for (const line of chunk.split('\n')) {
                  if (!line.startsWith('data: ')) continue
                  const data = line.slice(6).trim()
                  if (!data) continue
                  let event: any
                  try { event = JSON.parse(data) } catch { continue }
                  if (event.error) {
                    throw new Error(event.error)
                  } else if (event.type === 'thinking_start') {
                    setIsThinking(true)
                    currentThinking = ''
                  } else if (event.type === 'thinking') {
                    currentThinking += event.content
                    setStreamingThinking(currentThinking)
                  } else if (event.type === 'thinking_end') {
                    setIsThinking(false)
                    if (currentThinking) thinkingContent.push({ type: 'thinking', text: currentThinking })
                  } else if (event.type === 'text') {
                    currentText += event.content
                    setStreamingText(currentText)
                  }
                }
              }
            } finally {
              reader.releaseLock()
            }
          }

          if (currentText) textContent.push({ type: 'text', text: currentText })
          const responseContent: ContentBlock[] = [...thinkingContent, ...textContent]

          setTabs(prev => prev.map(t =>
            t.id === newTab.id
              ? { ...t, messages: [...initialMessages, { role: 'assistant' as const, content: responseContent }] }
              : t
          ))
          setStreamingThinking('')
          setStreamingText('')
          setIsThinking(false)
          notificationService.notifyInvestigationComplete({ title: initialTitle || 'Investigation', summary: 'Analysis complete' })
        } catch (e: any) {
          logger.error('Investigation streaming error', e)
          setTabs(prev => prev.map(t =>
            t.id === newTab.id
              ? { ...t, messages: [...initialMessages, { role: 'assistant', content: `Error: ${e?.message || 'Failed'}` }] }
              : t
          ))
          setStreamingThinking('')
          setStreamingText('')
          setIsThinking(false)
        } finally { setLoading(false) }
      }, 300)
    }
  }, [open, initialMessages, initialAgentId, initialTitle, lastInvestigationId])

  useEffect(() => { if (!open) setLastInvestigationId(null) }, [open])

  // Prompts Repo (post-Phase-2): open a new tab with the clicked prompt
  // sitting in the input, unsent -- confirmed behavior, deliberately not
  // the auto-investigation effect above's auto-send pattern. Guarded by
  // initialDraftKey (not just initialDraftText) so clicking the identical
  // prompt twice still opens a fresh tab rather than being treated as a
  // no-op repeat.
  useEffect(() => {
    if (open && initialDraftText && initialDraftKey !== undefined && initialDraftKey !== lastDraftKey) {
      setLastDraftKey(initialDraftKey)
      const newTab: ChatTab = {
        id: `draft-${Date.now()}`,
        title: initialDraftText.length > 40 ? `${initialDraftText.slice(0, 40)}…` : initialDraftText,
        messages: [],
      }
      const capped = capTabsAt10([...tabs, newTab], newTab.id)
      setTabs(capped)
      setCurrentTab(capped.findIndex(t => t.id === newTab.id))
      setInput(initialDraftText)
    }
  }, [open, initialDraftText, initialDraftKey, lastDraftKey, tabs])

  // #184 Phase 2: ask the backend for an exact token count + USD estimate
  // instead of doing the math client-side. The backend uses Anthropic's
  // free count_tokens API for Anthropic models (so the number is exact,
  // including system prompt + tools), and tiktoken for OpenAI. Debounced
  // 400ms so we don't hammer the endpoint on every keystroke. The fetch
  // is best-effort — on failure we keep the last good estimate rather
  // than zeroing out the warning bar (which would mislead the user).
  useEffect(() => {
    const ctrl = new AbortController()
    const debounce = setTimeout(async () => {
      const msgs = tabs[currentTab]?.messages || []
      const messagesPayload = [
        ...msgs.map(m => ({ role: m.role, content: m.content })),
        ...(input.trim() ? [{ role: 'user', content: input }] : []),
      ]
      // Nothing to estimate yet → reset so the warning bar disappears.
      if (messagesPayload.length === 0 && !systemPrompt) {
        setCostEstimate(null)
        setEstimatedTokens(0)
        return
      }
      try {
        const res = await analyticsApi.estimateCost({
          provider_type: 'anthropic',
          model_id: model || 'claude-sonnet-4-5-20250929',
          messages: messagesPayload,
          system_prompt: systemPrompt || undefined,
          max_tokens: maxTokens,
        })
        if (ctrl.signal.aborted) return
        setCostEstimate(res.data)
        setEstimatedTokens(res.data.input_tokens)
      } catch {
        // Keep previous estimate on failure — no point flashing $0 when
        // the network blip resolves. Logged at debug elsewhere.
      }
    }, 400)
    return () => {
      clearTimeout(debounce)
      ctrl.abort()
    }
  }, [tabs, currentTab, input, systemPrompt, model, maxTokens])

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files) return
    for (let i = 0; i < files.length; i++) {
      try {
        const res = await claudeApi.uploadFile(files[i])
        const d = res.data
        if (d.type === 'image') setAttachedFiles(prev => [...prev, { name: d.filename, type: 'image', data: d.data, media_type: d.media_type }])
        else if (d.type === 'text') setInput(prev => prev + '\n\n' + d.content)
      } catch { /* ignore file upload errors */ }
    }
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  // Core "append this user message to baseMessages and stream a response"
  // logic, factored out of the old handleSend (post-Phase-2) so both a
  // normal send and an edit-and-resend can share it instead of duplicating
  // ~200 lines of streaming/error-handling logic. baseMessages is passed
  // explicitly (not read from tabs state) so an edit-resend can pass an
  // already-truncated history without a React state-timing race.
  const sendUserMessage = async (content: string | ContentBlock[], baseMessages: Message[]) => {
    const sessionId = `${Date.now()}-${Math.random().toString(36).substring(7)}`

    logger.send('=== OUTGOING MESSAGE ===', {
      sessionId,
      model,
      selectedAgent,
      timestamp: new Date().toISOString()
    })

    const userMsg: Message = { role: 'user', content }

    const newTabs = [...tabs]
    newTabs[currentTab] = {
      ...newTabs[currentTab],
      messages: [...baseMessages, userMsg],
      lastUpdated: Date.now(),
    }

    // Strip thinking blocks from history before sending - backend/agent controls thinking
    const toSend = stripThinkingBlocks(newTabs[currentTab].messages)

    setTabs(newTabs)
    setLoading(true)
    setStreamingThinking('')
    setStreamingText('')
    setIsThinking(false)

    try {
      logger.request('📤 === API REQUEST ===', {
        sessionId,
        messageCount: toSend.length,
        maxTokens,
        model,
        selectedAgent,
        timestamp: new Date().toISOString()
      })
      
      const response = await fetch('/api/claude/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
        },
        body: JSON.stringify({
          messages: toSend,
          model,
          max_tokens: maxTokens,
          enable_thinking: enableThinking,
          thinking_budget: enableThinking ? thinkingBudget : undefined,
          agent_id: selectedAgent || undefined,
          system_prompt: systemPrompt || undefined,
          session_id: tabs[currentTab]?.id,
        }),
      })
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }
      
      const reader = response.body?.getReader()
      const decoder = new TextDecoder()
      
      const thinkingContent: ContentBlock[] = []
      const textContent: ContentBlock[] = []
      let currentThinking = ''
      let currentText = ''
      let capturedUsage: { input_tokens: number; output_tokens: number } | null = null

      if (reader) {
        try {
          while (true) {
            const { done, value } = await reader.read()
            if (done) break

            const chunk = decoder.decode(value)
            const lines = chunk.split('\n')

            for (const line of lines) {
              if (line.startsWith('data: ')) {
                const data = line.slice(6)
                if (data.trim()) {
                  let event: any
                  try {
                    event = JSON.parse(data)
                  } catch (parseError) {
                    logger.error('Failed to parse SSE event JSON', { data, error: parseError })
                    continue
                  }

                  if (event.error) {
                    throw new Error(event.error)
                  } else if (event.type === 'usage') {
                    capturedUsage = { input_tokens: event.input_tokens, output_tokens: event.output_tokens }
                  } else if (event.type === 'context_summarized') {
                    logger.info(`Context auto-summarized: ${event.summarized_messages} older messages condensed, ${event.remaining_messages} recent messages kept`)
                    currentText += `[Context auto-summarized: ${event.summarized_messages} older messages were condensed to preserve context within the model's limits. Recent messages and all key details are preserved.]\n\n`
                    setStreamingText(currentText)
                  } else if (event.type === 'thinking_start') {
                    setIsThinking(true)
                    currentThinking = ''
                    logger.receive('💭 Thinking started')
                  } else if (event.type === 'thinking') {
                    currentThinking += event.content
                    setStreamingThinking(currentThinking)
                  } else if (event.type === 'thinking_end') {
                    setIsThinking(false)
                    if (currentThinking) {
                      thinkingContent.push({ type: 'thinking', text: currentThinking })
                    }
                    logger.receive('💭 Thinking ended', { totalLength: currentThinking.length })
                  } else if (event.type === 'text') {
                    currentText += event.content
                    setStreamingText(currentText)
                  }
                }
              }
            }
          }
        } finally {
          reader.releaseLock()
        }
      }
      
      if (currentText) {
        textContent.push({ type: 'text', text: currentText })
      }
      
      const responseContent: ContentBlock[] = [...thinkingContent, ...textContent]
      
      logger.receive('📥 === RESPONSE COMPLETE ===', {
        sessionId,
        thinkingBlocks: thinkingContent.length,
        textBlocks: textContent.length,
        timestamp: new Date().toISOString()
      })
      
      setTabs(prevTabs => {
        const updatedTabs = [...prevTabs]
        updatedTabs[currentTab] = {
          ...updatedTabs[currentTab],
          messages: [
            ...updatedTabs[currentTab].messages,
            { role: 'assistant', content: responseContent, usage: capturedUsage || undefined },
          ],
          lastUpdated: Date.now(),
        }
        return updatedTabs
      })

      setStreamingThinking('')
      setStreamingText('')
      setIsThinking(false)

      // GH #79 — refresh reasoning-trace summary for this session
      const sid = tabs[currentTab]?.id
      if (sid) {
        reasoningApi.getSessionSummary(sid)
          .then(s => setSessionSummary({
            total_interactions: s.total_interactions,
            total_cost_usd: s.total_cost_usd,
            total_input_tokens: s.total_input_tokens,
            total_output_tokens: s.total_output_tokens,
          }))
          .catch(() => { /* silent — trace persistence is best-effort */ })
      }
    } catch (e: any) {
      logger.error('❌ === API ERROR ===', {
        sessionId,
        error: e?.message || 'Unknown error',
        detail: e?.response?.data?.detail,
        status: e?.response?.status,
        timestamp: new Date().toISOString(),
        fullError: e
      })
      // #186: render a typed inline message for budget-exceeded responses
      // (HTTP 402, body.detail.code == 'budget_exceeded') so the user
      // sees "budget exceeded — tier: virtual_key" instead of a generic
      // error toast. Backend builds this body in backend/api/claude.py's
      // chat handler.
      //
      // #292: same pattern for "no LLM provider configured" — backend
      // returns 503 with detail.code == 'no_llm_provider_configured'
      // and a settings_path. We render an actionable line that points
      // users at Settings → AI / LLM Providers instead of a bare
      // "Error: ..." bubble.
      const detail = e?.response?.data?.detail
      const isBudgetBlock =
        e?.response?.status === 402 &&
        detail &&
        typeof detail === 'object' &&
        detail.code === 'budget_exceeded'
      const isMissingProvider =
        e?.response?.status === 503 &&
        detail &&
        typeof detail === 'object' &&
        detail.code === 'no_llm_provider_configured'
      let userMessage: string
      if (isBudgetBlock) {
        userMessage = `⚠️ LLM budget exceeded (tier: **${detail.tier || 'unknown'}**). ${
          detail.message ||
          'Bifrost rejected the call upstream of the model. Update the budget in Settings → LLM Providers → Budgets, or set DEV_MODE / LLM_BUDGET_UNLIMITED to bypass.'
        }`
      } else if (isMissingProvider) {
        userMessage = `🔌 ${detail.message || 'No LLM provider configured.'} Open **Settings → AI / LLM Providers** to add one.`
      } else {
        userMessage = `Error: ${typeof detail === 'string' ? detail : detail?.message || e?.message || 'Failed'}`
      }
      setTabs(prevTabs => {
        const updatedTabs = [...prevTabs]
        updatedTabs[currentTab] = {
          ...updatedTabs[currentTab],
          messages: [...updatedTabs[currentTab].messages, { role: 'assistant', content: userMessage }]
        }
        return updatedTabs
      })
    } finally { setLoading(false) }
  }

  const handleSend = async () => {
    if ((!input.trim() && !attachedFiles.length) || loading) return

    // Defensive guard, not the primary fix (that's loadPersistedData()
    // rejecting an empty persisted array) -- if tabs is ever empty for any
    // other reason, open a fresh tab rather than silently throwing on
    // tabs[currentTab].messages, which previously killed handleSend before
    // it could clear the input or send the request (looked exactly like a
    // dead Send button, no visible error).
    if (!tabs[currentTab]) {
      setTabs([{ id: Date.now().toString(), title: 'Chat 1', messages: [] }])
      setCurrentTab(0)
      return
    }

    let content: string | ContentBlock[]
    if (attachedFiles.length) {
      const blocks: ContentBlock[] = []
      if (input.trim()) blocks.push({ type: 'text', text: input.trim() })
      attachedFiles.forEach(f => { if (f.type === 'image' && f.media_type) blocks.push({ type: 'image', source: { type: 'base64', media_type: f.media_type, data: f.data } }) })
      content = blocks
    } else content = input.trim()

    const baseMessages = tabs[currentTab].messages
    setInput('')
    setAttachedFiles([])
    await sendUserMessage(content, baseMessages)
  }

  // Edit-and-resend (post-Phase-2, confirmed behavior): editing a sent
  // message discards it and everything after it, then re-sends the edited
  // text as a fresh turn -- same convention as ChatGPT/Claude.ai. Only
  // offered for plain-text messages; a multimodal (image-attached) message
  // isn't editable through this simple text field.
  const handleEditStart = (index: number, msg: Message) => {
    if (typeof msg.content !== 'string' || loading) return
    setEditingIndex(index)
    setEditingText(msg.content)
  }

  const handleEditCancel = () => {
    setEditingIndex(null)
    setEditingText('')
  }

  const handleEditSave = async (index: number) => {
    const text = editingText.trim()
    if (!text) return
    const baseMessages = tabs[currentTab].messages.slice(0, index)
    setEditingIndex(null)
    setEditingText('')
    await sendUserMessage(text, baseMessages)
  }

  const handleKeyPress = (e: React.KeyboardEvent) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }
  // Chats History cap (post-Phase-2, confirmed design): keep at most the 10
  // most-recently-active conversations. Never evicts `keepId` (the tab
  // that's about to become active) even if it's technically the oldest by
  // timestamp (a brand-new tab has no lastUpdated yet).
  const capTabsAt10 = (list: ChatTab[], keepId: string): ChatTab[] => {
    if (list.length <= MAX_HISTORY_TABS) return list
    // Pinned conversations are exempt from eviction, same as the active tab.
    const evictable = list
      .filter(t => t.id !== keepId && !t.isPinned)
      .sort((a, b) => (a.lastUpdated ?? 0) - (b.lastUpdated ?? 0))
    const toDrop = new Set(evictable.slice(0, list.length - MAX_HISTORY_TABS).map(t => t.id))
    return list.filter(t => !toDrop.has(t.id))
  }

  const handleNewTab = () => {
    const newTab: ChatTab = { id: `${Date.now()}`, title: `Chat ${tabs.length + 1}`, messages: [] }
    const capped = capTabsAt10([...tabs, newTab], newTab.id)
    setTabs(capped)
    setCurrentTab(capped.findIndex(t => t.id === newTab.id))
  }
  const handleCloseTab = (idx: number) => {
    // If closing the last tab, create a new empty tab first to keep drawer open
    if (tabs.length === 1) {
      logger.info('Closing last tab - creating new empty tab')
      setTabs([{ id: `${Date.now()}`, title: 'Chat 1', messages: [] }])
      setCurrentTab(0)
      return
    }
    
    logger.info('Closing tab', { idx, totalTabs: tabs.length, currentTab })
    
    // Remove the tab
    const newTabs = tabs.filter((_, i) => i !== idx)
    setTabs(newTabs)
    
    // Adjust current tab if needed
    if (currentTab >= newTabs.length) {
      setCurrentTab(newTabs.length - 1)
    } else if (currentTab > idx) {
      setCurrentTab(currentTab - 1)
    }
  }

  const handleClearChat = () => {
    logger.info('Clearing current chat', { currentTab, tabId: tabs[currentTab].id })
    setTabs(prevTabs => {
      const newTabs = [...prevTabs]
      newTabs[currentTab] = {
        ...newTabs[currentTab],
        messages: []
      }
      return newTabs
    })
  }

  const handleSummarize = async () => {
    const currentMessages = tabs[currentTab]?.messages || []
    if (currentMessages.length < 4 || summarizing) return
    
    setSummarizing(true)
    logger.info('Summarizing conversation', { messageCount: currentMessages.length, estimatedTokens })
    
    try {
      const res = await claudeApi.summarizeConversation({
        messages: currentMessages,
        model
      })
      
      const summary = res.data.summary
      const savedTokens = res.data.estimated_tokens_saved
      const originalCount = res.data.original_message_count
      
      logger.success('Conversation summarized', { savedTokens, originalCount })
      
      // Replace conversation with a summary context message + note
      setTabs(prevTabs => {
        const newTabs = [...prevTabs]
        newTabs[currentTab] = {
          ...newTabs[currentTab],
          messages: [
            { role: 'user' as const, content: `[Previous conversation summarized - ${originalCount} messages condensed]\n\nPlease use the following context from our previous conversation to continue helping me:\n\n${summary}` },
            { role: 'assistant' as const, content: `I've reviewed the summary of our previous conversation (${originalCount} messages). I have full context of what we discussed, including all findings, cases, and analysis. How would you like to continue?` }
          ]
        }
        return newTabs
      })
      
      notificationService.notifyInvestigationComplete({
        title: 'Conversation Summarized',
        summary: `${originalCount} messages condensed, ~${Math.round(savedTokens / 1000)}k tokens freed`
      })
    } catch (e: any) {
      logger.error('Summarization failed', e)
      // Add error as a message so user sees it
      setTabs(prevTabs => {
        const newTabs = [...prevTabs]
        newTabs[currentTab] = {
          ...newTabs[currentTab],
          messages: [...newTabs[currentTab].messages, { role: 'assistant' as const, content: `Failed to summarize conversation: ${e?.response?.data?.detail || e?.message || 'Unknown error'}. You can try clearing the chat and starting fresh.` }]
        }
        return newTabs
      })
    } finally {
      setSummarizing(false)
    }
  }

  const renderContent = (content: string | ContentBlock[], messageIndex?: number) => {
    if (typeof content === 'string') {
      logger.render(`Rendering string content: ${content.length} chars`, { preview: content.substring(0, 100) })
      return <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>{content}</Typography>
    }

    if (!Array.isArray(content)) {
      logger.error('Content is not string or array', { content, type: typeof content })
      return <Typography variant="body2" color="error">Invalid content type</Typography>
    }

    logger.render(`Rendering content blocks: ${content.length} blocks`)
    content.forEach((b, i) => {
      logger.debug(`Block ${i}: ${b.type}, ${b.text?.length || 0} chars`)
    })

    return <>{content.map((b, i) => {
      const thinkingKey = `${messageIndex ?? 'x'}-${i}`
      const collapsed = collapsedThinking[thinkingKey] ?? false
      return (
        <Box key={i} sx={{ mb: 1 }}>
          {b.type === 'text' && b.text && <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>{b.text}</Typography>}
          {b.type === 'image' && b.source && <img src={`data:${b.source.media_type};base64,${b.source.data}`} alt="" style={{ maxWidth: '100%', borderRadius: 8, marginTop: 8 }} />}
          {b.type === 'thinking' && b.text && (
            <Box sx={{
              p: 1.5,
              borderRadius: 1,
              bgcolor: alpha(theme.palette.info.main, 0.05),
              borderLeft: 2,
              borderColor: 'info.main',
              mb: 1.5,
              mt: 0.5
            }}>
              <Box
                sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: collapsed ? 0 : 0.5, cursor: 'pointer' }}
                onClick={() => toggleThinking(thinkingKey)}
              >
                <Typography variant="caption" sx={{ fontWeight: 600, color: 'info.main', fontSize: '0.7rem', flex: 1 }}>
                  💭 THINKING ({b.text.length} chars)
                </Typography>
                {collapsed ? <ExpandMoreIcon sx={{ fontSize: 14, color: 'info.main' }} /> : <ExpandLessIcon sx={{ fontSize: 14, color: 'info.main' }} />}
              </Box>
              <Collapse in={!collapsed}>
                <Typography
                  variant="body2"
                  sx={{
                    whiteSpace: 'pre-wrap',
                    fontStyle: 'italic',
                    color: 'text.secondary',
                    fontSize: '0.85rem',
                    lineHeight: 1.5,
                    opacity: 0.9
                  }}
                >
                  {b.text}
                </Typography>
              </Collapse>
            </Box>
          )}
        </Box>
      )
    })}</>
  }

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      sx={{
        '& .MuiDrawer-paper': {
          width: fullScreen ? '100vw' : { xs: '100%', sm: 420, md: 480 },
          maxWidth: fullScreen ? '100vw' : undefined,
          bgcolor: 'background.default',
        },
        '& .MuiBackdrop-root': {
          backgroundColor: fullScreen ? 'rgba(0,0,0,0.7)' : 'rgba(0,0,0,0.5)',
        },
      }}
    >
      <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        {/* Header */}
        <Box sx={{
          px: 2, py: 1.5,
          borderBottom: 1, borderColor: 'divider',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          bgcolor: 'background.paper',
          background: (t) => t.palette.mode === 'dark'
            ? 'linear-gradient(135deg, #060D1F 0%, #0D1A36 100%)'
            : 'linear-gradient(135deg, #ffffff 0%, #F0F4FF 100%)',
        }}>
          {/* Logo + Title */}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.2 }}>
            {/* Same canonical logo as NavigationRail's SentryLogoSmall
                (post-Phase-2 fix: one shared symmetric design, not two
                drifted ones) -- equal-height bars, symmetric shield. */}
            <svg width="22" height="24" viewBox="0 0 100 110" fill="none" xmlns="http://www.w3.org/2000/svg">
              <defs>
                <linearGradient id="cdlg-grad" x1="15" y1="0" x2="85" y2="110" gradientUnits="userSpaceOnUse">
                  <stop offset="0%" stopColor="#2D6FFF" />
                  <stop offset="45%" stopColor="#1A4FE8" />
                  <stop offset="100%" stopColor="#0A1E7A" />
                </linearGradient>
                <linearGradient id="cdlg-gloss" x1="10" y1="0" x2="60" y2="50" gradientUnits="userSpaceOnUse">
                  <stop offset="0%" stopColor="rgba(255,255,255,0.38)" />
                  <stop offset="100%" stopColor="rgba(255,255,255,0)" />
                </linearGradient>
                <clipPath id="cdlg-clip">
                  <path d="M50 4 L90 20 L90 60 Q90 90 50 106 Q10 90 10 60 L10 20 Z" />
                </clipPath>
              </defs>
              <path d="M50 4 L90 20 L90 60 Q90 90 50 106 Q10 90 10 60 L10 20 Z" fill="url(#cdlg-grad)" />
              <path d="M50 8 L86 22.5 L86 59 Q86 85 50 100 Q14 85 14 59 L14 22.5 Z"
                fill="none" stroke="rgba(120,170,255,0.3)" strokeWidth="1.5" />
              <rect x="21" y="34" width="14" height="46" rx="7" fill="rgba(255,255,255,0.16)" />
              <rect x="21" y="34" width="14" height="46" rx="7" fill="none" stroke="rgba(255,255,255,0.7)" strokeWidth="1.2" />
              <rect x="43" y="34" width="14" height="46" rx="7" fill="rgba(255,255,255,0.16)" />
              <rect x="43" y="34" width="14" height="46" rx="7" fill="none" stroke="rgba(255,255,255,0.7)" strokeWidth="1.2" />
              <rect x="65" y="34" width="14" height="46" rx="7" fill="rgba(255,255,255,0.16)" />
              <rect x="65" y="34" width="14" height="46" rx="7" fill="none" stroke="rgba(255,255,255,0.7)" strokeWidth="1.2" />
              <path d="M50 8 L86 22.5 L86 40 C65 33 35 33 14 40 L14 22.5 Z"
                fill="url(#cdlg-gloss)" clipPath="url(#cdlg-clip)" />
            </svg>
            <Box>
              <Typography variant="subtitle2" sx={{ fontWeight: 800, color: 'text.primary', lineHeight: 1.1, letterSpacing: '-0.01em' }}>
                Sentry Chat
              </Typography>
              <Typography sx={{ fontSize: '9px', fontWeight: 700, color: 'primary.main', letterSpacing: '2px', textTransform: 'uppercase' }}>
                AI Assistant
              </Typography>
            </Box>
            {sessionSummary && sessionSummary.total_interactions > 0 && (
              <Tooltip title={`${sessionSummary.total_interactions} LLM calls · in ${sessionSummary.total_input_tokens.toLocaleString()} tok · out ${sessionSummary.total_output_tokens.toLocaleString()} tok`}>
                <Chip
                  size="small"
                  label={`$${sessionSummary.total_cost_usd.toFixed(4)}`}
                  sx={{ height: 20, fontSize: '0.7rem' }}
                />
              </Tooltip>
            )}
          </Box>

          {/* Action buttons */}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            {/* Save chat (post-Phase-2: renamed from "Export chat", now a
                format picker consolidating the old .txt export and the
                separate "Generate PDF report" icon into one menu) */}
            <Tooltip title="Save chat">
              <span>
                <IconButton
                  size="small"
                  disabled={!tabs[currentTab]?.messages.length}
                  onClick={(e) => setSaveMenuAnchor(e.currentTarget)}
                  sx={{ color: 'primary.main', '&:hover': { bgcolor: (t) => alpha(t.palette.primary.main, 0.1) } }}
                >
                  <SaveIcon sx={{ fontSize: 18 }} />
                </IconButton>
              </span>
            </Tooltip>
            <Menu anchorEl={saveMenuAnchor} open={!!saveMenuAnchor} onClose={() => setSaveMenuAnchor(null)}>
              <MenuItem
                onClick={() => {
                  setSaveMenuAnchor(null)
                  const tab = tabs[currentTab]
                  if (!tab) return
                  const text = tab.messages.map(m =>
                    `${m.role === 'user' ? 'You' : 'Sentry AI'}: ${typeof m.content === 'string' ? m.content : JSON.stringify(m.content)}`
                  ).join('\n\n')
                  const blob = new Blob([text], { type: 'text/plain' })
                  const a = document.createElement('a')
                  a.href = URL.createObjectURL(blob)
                  a.download = `sentry-chat-${Date.now()}.txt`
                  a.click()
                }}
              >
                Save as .txt
              </MenuItem>
              <MenuItem
                onClick={async () => {
                  setSaveMenuAnchor(null)
                  const tab = tabs[currentTab]
                  if (!tab) return
                  try {
                    setLoading(true)
                    const res = await claudeApi.generateChatReport({ tab_title: tab.title, messages: tab.messages })
                    alert(`Report saved: ${res.data.filename}`)
                  } catch { /* ignore */ } finally { setLoading(false) }
                }}
              >
                Save as PDF
              </MenuItem>
            </Menu>
            <IconButton
              size="small"
              onClick={(e) => {
                e.stopPropagation()
                const newValue = !showSettings
                setShowSettings(newValue)
                logger.info('Settings button clicked', {
                  previousState: showSettings,
                  newState: newValue
                })
              }}
              sx={{
                bgcolor: showSettings ? alpha(theme.palette.primary.main, 0.15) : 'transparent',
                color: showSettings ? 'primary.main' : 'text.secondary',
                '&:hover': {
                  bgcolor: showSettings
                    ? alpha(theme.palette.primary.main, 0.25)
                    : alpha(theme.palette.text.primary, 0.05)
                }
              }}
            >
              <SettingsIcon sx={{ fontSize: 18 }} />
            </IconButton>
            <IconButton size="small" onClick={panelMode && onCollapse ? onCollapse : onClose}
              title={panelMode ? 'Minimise chat' : 'Close'}
              sx={{ color: 'text.secondary', '&:hover': { color: 'primary.main' } }}
            >
              {/* Chevron-right collapses in panel mode; X closes in full mode */}
              {panelMode
                ? <span style={{ fontSize: 18, lineHeight: 1, display: 'flex', alignItems: 'center' }}>&#8250;</span>
                : <CloseIcon sx={{ fontSize: 18 }} />
              }
            </IconButton>
            {panelMode && (
              <IconButton size="small" onClick={onClose} title="Close chat"
                sx={{ color: 'text.secondary', '&:hover': { color: 'error.main' } }}
              >
                <CloseIcon sx={{ fontSize: 18 }} />
              </IconButton>
            )}

          </Box>
        </Box>

        <Collapse in={showSettings}>
          <ClickAwayListener 
            onClickAway={() => {
              // Don't close if clicking on the settings button itself
              setShowSettings(false)
              logger.debug('Click away detected, closing settings')
            }}
          >
            <Box sx={{ p: 2, bgcolor: alpha(theme.palette.background.paper, 0.5), borderBottom: 1, borderColor: 'divider', maxHeight: '70vh', overflowY: 'auto' }}>
              
              {/* Status Section */}
              <Typography variant="caption" sx={{ fontWeight: 700, display: 'block', mb: 1, color: 'primary.main' }}>Status</Typography>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                <Typography variant="caption" sx={{ fontWeight: 600 }}>MCP Tools:</Typography>
                {mcpStatus ? <Chip icon={mcpStatus.available > 0 ? <CheckCircleIcon /> : <ErrorIcon />} label={`${mcpStatus.available}/${mcpStatus.total}`} size="small" color={mcpStatus.available > 0 ? 'success' : 'error'} /> : <CircularProgress size={14} />}
              </Box>
              <Box sx={{ mb: 2 }}>
                <Typography variant="caption" color={estimatedTokens > 150000 ? 'error.main' : estimatedTokens > 100000 ? 'warning.main' : 'text.secondary'}>
                  Context: ~{estimatedTokens.toLocaleString()} / 200,000 tokens
                  {estimatedTokens > 150000 && ' ⚠️ Auto-summarize on next send'}
                </Typography>
                <LinearProgress variant="determinate" value={Math.min((estimatedTokens / 200000) * 100, 100)} sx={{ height: 4, borderRadius: 2, mt: 0.5 }} color={estimatedTokens > 150000 ? 'error' : estimatedTokens > 100000 ? 'warning' : 'primary'} />
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.25 }}>
                  Output max: {maxTokens.toLocaleString()} tokens
                </Typography>
                {costEstimate && (
                  <Tooltip
                    title={
                      // The band's bounds: low = no output (immediate stop),
                      // high = max_tokens of output. Real cost lands in
                      // between, and is typically much closer to low_usd
                      // when prompt caching is hot.
                      `${costEstimate.token_count_method === 'anthropic_count_tokens'
                        ? 'Exact token count via Anthropic count_tokens API.'
                        : costEstimate.token_count_method === 'tiktoken'
                        ? 'Token count via tiktoken (OpenAI encoder).'
                        : 'Approximate token count (chars ÷ 4 fallback).'} ` +
                      `Pricing: ${costEstimate.pricing_source}.`
                    }
                  >
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      sx={{ display: 'block', mt: 0.25, fontFamily: 'monospace' }}
                    >
                      Est. cost: ${costEstimate.low_usd.toFixed(4)} – ${costEstimate.high_usd.toFixed(4)}
                      {costEstimate.pricing_source !== 'exact' && ` · ${costEstimate.pricing_source}`}
                    </Typography>
                  </Tooltip>
                )}
              </Box>

              {/* Model Settings Section */}
              <Typography variant="caption" sx={{ fontWeight: 700, display: 'block', mb: 1, color: 'primary.main' }}>Model Settings</Typography>
              <FormControl fullWidth size="small" sx={{ mb: 1.5 }}>
                <Select value={model} onChange={(e) => setModel(e.target.value)} displayEmpty>
                  {models.map(m => <MenuItem key={m.id} value={m.id}>{m.name}</MenuItem>)}
                  {models.length === 0 && <MenuItem value="claude-haiku-4-5-20251001">Claude Haiku 4.5</MenuItem>}
                </Select>
              </FormControl>
              <TextField 
                fullWidth 
                size="small" 
                type="number" 
                label="Max Tokens" 
                value={maxTokens} 
                onChange={(e) => setMaxTokens(parseInt(e.target.value) || 4096)} 
                sx={{ mb: 1.5 }} 
              />

              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                <Typography variant="caption" sx={{ fontWeight: 600 }}>Extended Thinking</Typography>
                <Switch
                  size="small"
                  checked={enableThinking}
                  onChange={(e) => setEnableThinking(e.target.checked)}
                />
              </Box>
              {enableThinking && (
                <TextField
                  fullWidth
                  size="small"
                  type="number"
                  label="Thinking Budget (tokens)"
                  value={thinkingBudget}
                  onChange={(e) => setThinkingBudget(parseInt(e.target.value) || 10000)}
                  sx={{ mb: 1.5 }}
                  helperText="Max tokens Claude can use for reasoning"
                />
              )}

              {/* Agent Selection */}
              <FormControl fullWidth size="small" sx={{ mb: 2 }}>
                <Select
                  value={selectedAgent}
                  onChange={(e) => setSelectedAgent(e.target.value)}
                  displayEmpty
                  size="small"
                >
                  <MenuItem value="">No Agent (General Chat)</MenuItem>
                  {agents.map(agent => (
                    <MenuItem key={agent.id} value={agent.id}>
                      {agent.icon && `${agent.icon} `}{agent.name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>

              {/* System Prompt Section */}
              <Typography variant="caption" sx={{ fontWeight: 700, display: 'block', mb: 1, mt: 2, color: 'primary.main' }}>Advanced</Typography>
              <TextField 
                fullWidth 
                size="small" 
                label="System Prompt (Optional)" 
                value={systemPrompt} 
                onChange={(e) => setSystemPrompt(e.target.value)} 
                multiline 
                rows={3} 
                placeholder="Override default system prompt..."
                sx={{ mb: 1 }} 
                helperText="Leave empty to use default prompt"
              />

              {/* Info Text */}
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 2, fontStyle: 'italic' }}>
                Settings are automatically saved
              </Typography>
            </Box>
          </ClickAwayListener>
        </Collapse>

        <Box sx={{ borderBottom: 1, borderColor: 'divider', display: 'flex', alignItems: 'center', bgcolor: 'background.paper' }}>
          <Tabs value={currentTab} onChange={(_, v) => setCurrentTab(v)} variant="scrollable" scrollButtons="auto" sx={{ flex: 1, minHeight: 40 }}>
            {tabs.map((tab, i) => (
              <Tab 
                key={tab.id} 
                sx={{ minHeight: 40, py: 0 }} 
                label={
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    <Typography variant="caption">{tab.title}</Typography>
                    <Box
                      component="span"
                      onClick={(e) => { e.stopPropagation(); handleCloseTab(i) }}
                      sx={{ 
                        display: 'inline-flex', 
                        alignItems: 'center',
                        justifyContent: 'center',
                        p: 0.25,
                        borderRadius: '50%',
                        cursor: 'pointer',
                        '&:hover': { bgcolor: 'action.hover' }
                      }}
                    >
                      <CloseIcon sx={{ fontSize: 14 }} />
                    </Box>
                  </Box>
                } 
              />
            ))}
          </Tabs>
          <Tooltip title="Summarize & compress conversation">
            <span>
              <IconButton 
                size="small" 
                onClick={handleSummarize} 
                disabled={summarizing || loading || (tabs[currentTab]?.messages.length || 0) < 4}
                sx={{ mr: 0.5, color: estimatedTokens > 100000 ? 'warning.main' : 'text.secondary' }}
              >
                {summarizing ? <CircularProgress size={16} /> : <CompressIcon sx={{ fontSize: 18 }} />}
              </IconButton>
            </span>
          </Tooltip>
          <Tooltip title="Clear current chat">
            <IconButton size="small" onClick={handleClearChat} sx={{ mr: 0.5 }}><RefreshIcon sx={{ fontSize: 18 }} /></IconButton>
          </Tooltip>
          <Tooltip title="New chat tab">
            <IconButton size="small" onClick={handleNewTab} sx={{ mr: 1 }}><AddIcon sx={{ fontSize: 18 }} /></IconButton>
          </Tooltip>
        </Box>

        <Box sx={{ flex: 1, overflow: 'auto', p: 2 }}>
          {/* Context window warning banner */}
          {estimatedTokens > 100000 && tabs[currentTab]?.messages.length > 0 && (
            <Box sx={{
              p: 1.5, mb: 2, borderRadius: 2,
              bgcolor: estimatedTokens > 150000 
                ? alpha(theme.palette.error.main, 0.08) 
                : alpha(theme.palette.warning.main, 0.08),
              border: 1,
              borderColor: estimatedTokens > 150000 ? 'error.main' : 'warning.main',
              display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap'
            }}>
              <WarningIcon sx={{ fontSize: 18, color: estimatedTokens > 150000 ? 'error.main' : 'warning.main' }} />
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography variant="caption" sx={{ fontWeight: 600, color: estimatedTokens > 150000 ? 'error.main' : 'warning.main' }}>
                  {estimatedTokens > 150000 
                    ? 'Context nearly full - older messages will be auto-summarized on next send' 
                    : 'Long conversation - summarize now to keep things fast'}
                </Typography>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                  ~{Math.round(estimatedTokens / 1000)}k / 200k tokens used ({tabs[currentTab]?.messages.length} messages)
                </Typography>
              </Box>
              <Button
                size="small"
                variant="outlined"
                startIcon={summarizing ? <CircularProgress size={12} /> : <CompressIcon sx={{ fontSize: 14 }} />}
                onClick={handleSummarize}
                disabled={summarizing || loading || tabs[currentTab]?.messages.length < 4}
                sx={{ 
                  textTransform: 'none', fontSize: '0.7rem', py: 0.25, px: 1,
                  borderColor: estimatedTokens > 150000 ? 'error.main' : 'warning.main',
                  color: estimatedTokens > 150000 ? 'error.main' : 'warning.main',
                  '&:hover': {
                    borderColor: estimatedTokens > 150000 ? 'error.dark' : 'warning.dark',
                    bgcolor: estimatedTokens > 150000 
                      ? alpha(theme.palette.error.main, 0.08)
                      : alpha(theme.palette.warning.main, 0.08),
                  }
                }}
              >
                {summarizing ? 'Summarizing...' : 'Summarize & Continue'}
              </Button>
            </Box>
          )}
          
          {tabs[currentTab]?.messages.length === 0 && (
            <Box sx={{ textAlign: 'center', mt: 4 }}>
              <Typography variant="body2" color="text.secondary">{greeting}</Typography>
              {selectedAgent && <Chip size="small" label={agents.find(a => a.id === selectedAgent)?.name} sx={{ mt: 1 }} />}
            </Box>
          )}
          {tabs[currentTab]?.messages.map((msg, i) => (
            <Box key={i} sx={{
                p: 1.5, mb: 1.5, borderRadius: 2,
                bgcolor: msg.role === 'user' ? alpha(theme.palette.primary.main, 0.1) : 'background.paper',
                ml: msg.role === 'user' ? 4 : 0, mr: msg.role === 'user' ? 0 : 4,
                border: 1, borderColor: msg.role === 'user' ? alpha(theme.palette.primary.main, 0.2) : 'divider',
              }}>
                <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
                  <Typography variant="caption" sx={{ fontWeight: 600, color: msg.role === 'user' ? 'primary.main' : 'text.secondary' }}>
                    {msg.role === 'user' ? 'You' : 'Sentry Agentic'}
                  </Typography>
                  {msg.role === 'user' && typeof msg.content === 'string' && editingIndex !== i && (
                    <Tooltip title="Edit & resend">
                      <span>
                        <IconButton size="small" disabled={loading} onClick={() => handleEditStart(i, msg)} sx={{ p: 0.25 }}>
                          <EditIcon sx={{ fontSize: 14 }} />
                        </IconButton>
                      </span>
                    </Tooltip>
                  )}
                </Box>
                {editingIndex === i ? (
                  <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'flex-end' }}>
                    <TextField
                      fullWidth
                      multiline
                      maxRows={6}
                      size="small"
                      autoFocus
                      value={editingText}
                      onChange={(e) => setEditingText(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleEditSave(i) }
                        if (e.key === 'Escape') handleEditCancel()
                      }}
                    />
                    <Tooltip title="Save & resend">
                      <IconButton size="small" onClick={() => handleEditSave(i)}><CheckIcon sx={{ fontSize: 18 }} /></IconButton>
                    </Tooltip>
                    <Tooltip title="Cancel">
                      <IconButton size="small" onClick={handleEditCancel}><CloseIcon sx={{ fontSize: 18 }} /></IconButton>
                    </Tooltip>
                  </Box>
                ) : (
                  <>
                    {renderContent(msg.content, i)}
                    {msg.role === 'assistant' && msg.usage && (
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5, opacity: 0.7 }}>
                        {msg.usage.input_tokens.toLocaleString()} in · {msg.usage.output_tokens.toLocaleString()} out tok
                      </Typography>
                    )}
                  </>
                )}
              </Box>
            ))}
          
          {/* Show streaming thinking in real-time */}
          {isThinking && streamingThinking && (
            <Box sx={{
              p: 1.5, mb: 1.5, borderRadius: 2,
              bgcolor: 'background.paper',
              mr: 4,
              border: 1, borderColor: 'divider',
            }}>
              <Typography variant="caption" sx={{ fontWeight: 600, color: 'text.secondary', mb: 0.5, display: 'block' }}>
                Sentry Agentic
              </Typography>
              <Box sx={{ 
                p: 1.5, 
                borderRadius: 1, 
                bgcolor: alpha(theme.palette.info.main, 0.05),
                borderLeft: 2,
                borderColor: 'info.main',
                mb: 0.5,
              }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.5 }}>
                  <Typography variant="caption" sx={{ fontWeight: 600, color: 'info.main', fontSize: '0.7rem' }}>
                    💭 THINKING...
                  </Typography>
                  <CircularProgress size={10} sx={{ ml: 1 }} />
                </Box>
                <Typography 
                  variant="body2" 
                  sx={{ 
                    whiteSpace: 'pre-wrap', 
                    fontStyle: 'italic', 
                    color: 'text.secondary',
                    fontSize: '0.85rem',
                    lineHeight: 1.5,
                    opacity: 0.9
                  }}
                >
                  {streamingThinking}
                </Typography>
              </Box>
            </Box>
          )}
          
          {/* Show streaming text in real-time */}
          {loading && streamingText && (
            <Box sx={{
              p: 1.5, mb: 1.5, borderRadius: 2,
              bgcolor: 'background.paper',
              mr: 4,
              border: 1, borderColor: 'divider',
            }}>
              <Typography variant="caption" sx={{ fontWeight: 600, color: 'text.secondary', mb: 0.5, display: 'block' }}>
                Sentry Agentic
              </Typography>
              <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>{streamingText}</Typography>
            </Box>
          )}
          
          {loading && !streamingText && !isThinking && <Box display="flex" justifyContent="center" my={2}><CircularProgress size={20} /></Box>}
          <div ref={messagesEndRef} />
        </Box>

        {attachedFiles.length > 0 && (
          <Box sx={{ px: 2, pb: 1 }}>
            <List dense>
              {attachedFiles.map((f, i) => (
                <ListItem key={i} sx={{ bgcolor: 'background.paper', borderRadius: 1, mb: 0.5, py: 0.5 }}>
                  <ImageIcon sx={{ fontSize: 16, mr: 1 }} />
                  <ListItemText primary={f.name} primaryTypographyProps={{ variant: 'caption' }} />
                  <ListItemSecondaryAction><IconButton size="small" onClick={() => setAttachedFiles(prev => prev.filter((_, j) => j !== i))}><DeleteIcon sx={{ fontSize: 16 }} /></IconButton></ListItemSecondaryAction>
                </ListItem>
              ))}
            </List>
          </Box>
        )}

        <Box sx={{ p: 2, borderTop: 1, borderColor: 'divider', bgcolor: 'background.paper' }}>
          <Box sx={{ display: 'flex', gap: 1, mb: 1, alignItems: 'center' }}>
            <input type="file" ref={fileInputRef} onChange={handleFileSelect} accept="image/*,.txt,.json,.csv,.md" multiple style={{ display: 'none' }} />
            <IconButton size="small" onClick={() => fileInputRef.current?.click()} disabled={loading}><AttachFileIcon sx={{ fontSize: 18 }} /></IconButton>
            <FormControl size="small" sx={{ minWidth: 140 }}>
              <Select 
                value={agents.find(a => a.id === selectedAgent) ? selectedAgent : ''} 
                onChange={(e) => setSelectedAgent(e.target.value)} 
                displayEmpty
              >
                <MenuItem value=""><em>No Agent</em></MenuItem>
                {agents.map(a => <MenuItem key={a.id} value={a.id}>{a.icon} {a.name}</MenuItem>)}
              </Select>
            </FormControl>
            <Tooltip title="View agents"><IconButton size="small" onClick={() => setAgentInfoDialogOpen(true)}><InfoIcon sx={{ fontSize: 18 }} /></IconButton></Tooltip>
            <Box sx={{ flex: 1 }} />
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <TextField fullWidth multiline maxRows={3} value={input} onChange={(e) => setInput(e.target.value)} onKeyPress={handleKeyPress} placeholder="Message..." disabled={loading} size="small" />
            <Button variant="contained" onClick={handleSend} disabled={(!input.trim() && !attachedFiles.length) || loading} sx={{ minWidth: 44 }}><SendIcon sx={{ fontSize: 18 }} /></Button>
          </Box>
        </Box>
      </Box>

      <Dialog open={agentInfoDialogOpen} onClose={() => setAgentInfoDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>SOC Agents</DialogTitle>
        <DialogContent dividers>
          {agents.map(a => (
            <Box key={a.id} sx={{ mb: 2, p: 1.5, borderRadius: 2, bgcolor: 'background.default', borderLeft: 3, borderColor: a.color || 'primary.main' }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Typography sx={{ fontSize: '1.25rem' }}>{a.icon}</Typography>
                <Box>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>{a.name}</Typography>
                  {a.specialization && <Chip label={a.specialization} size="small" sx={{ height: 18, fontSize: '0.65rem' }} />}
                </Box>
              </Box>
              <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>{a.description}</Typography>
            </Box>
          ))}
        </DialogContent>
        <DialogActions><Button onClick={() => setAgentInfoDialogOpen(false)}>Close</Button></DialogActions>
      </Dialog>

    </Drawer>
  )
}
