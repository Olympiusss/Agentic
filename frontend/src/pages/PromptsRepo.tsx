/**
 * PromptsRepo - sample prompts a user can click to load into a new chat.
 *
 * Content is transcribed from the SentinelOne coverage matrix's real
 * `example` questions (data/knowledge/sentinelone/coverage_matrix/
 * sentinelone_coverage_matrix.yaml) and the dv_cookbook's 11 validated
 * hunt templates -- every prompt here is already known to route correctly
 * (13/13 on the live coverage harness), not invented for this page.
 * Clicking a prompt pre-fills a new chat tab's input; it does not send.
 */
import { useOutletContext } from 'react-router-dom'
import { Box, Typography, Paper } from '@mui/material'
import { ChevronRight } from '@mui/icons-material'

interface LayoutContext {
  openChatWithDraft: (text: string) => void
}

interface PromptCategory {
  name: string
  description: string
  prompts: string[]
}

const CATEGORIES: PromptCategory[] = [
  {
    name: 'Threats & Endpoints',
    description: 'Quick counts and health checks -- answered instantly, no LLM call needed.',
    prompts: [
      'how many threats exist',
      'how many alerts this week',
      'how many endpoints do we have in total',
      'which agents are offline',
      'are there any outdated or unhealthy agents',
      'show me infected endpoints',
    ],
  },
  {
    name: 'Host & Investigation Lookups',
    description: 'Edit the placeholder (host name, storyline ID, alert ID) before sending.',
    prompts: [
      'what do we know about host <hostname>',
      'is this laptop online',
      'reconstruct the attack chain for storyline <id>',
      'tell me more about alert <id>',
    ],
  },
  {
    name: 'Vulnerabilities',
    description: 'CVE and vulnerability-management questions.',
    prompts: [
      'what are our critical vulnerabilities',
      'list unresolved vulnerabilities on production servers',
      'which endpoints are affected by CVE-2024-1234',
      'is this CVE present in our environment',
    ],
  },
  {
    name: 'Deep Visibility Hunts',
    description: 'Each runs a real, live-validated MITRE-tagged PowerQuery template -- a time range is included so it runs immediately instead of asking for one.',
    prompts: [
      'find living-off-the-land binaries spawned from Microsoft Word, in the last 24 hours',
      'show me PowerShell processes that connected to external IPs, in the last 24 hours',
      'find file modification events where the file was renamed to .locked or .encrypted, in the last 24 hours',
      'show me file downloads ending in .zip, .iso, or .html, in the last 24 hours',
      'find executions of whoami, nltest, or net commands, in the last 24 hours',
      'did anyone try to disable Windows Defender or kill security processes, in the last 24 hours',
      'find PowerShell or PsExec executions with an encoded command line, in the last 24 hours',
      'show me any references to lsass, procdump, or mimikatz, in the last 24 hours',
      'find registry modifications to Run or RunOnce autostart keys, in the last 24 hours',
      'show me rundll32 process executions, in the last 24 hours',
      'show me DNS requests that might indicate data exfiltration, in the last 24 hours',
    ],
  },
  {
    name: 'Sentry-Internal',
    description: "Sentry's own findings store, not SentinelOne -- the one case where that's the correct source.",
    prompts: [
      'what has Sentry flagged',
      'show me our own findings for this case',
    ],
  },
]

export default function PromptsRepo() {
  const { openChatWithDraft } = useOutletContext<LayoutContext>()

  return (
    <Box>
      <Box sx={{ mb: 3 }}>
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
          Prompts Repo
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          Click a prompt to start a guided investigation, instantly.
        </Typography>
      </Box>

      {CATEGORIES.map((cat) => (
        <Box key={cat.name} sx={{ mb: 4 }}>
          <Typography variant="h6" fontWeight={700} sx={{ mb: 0.25 }}>
            {cat.name}
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5 }}>
            {cat.description}
          </Typography>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            {cat.prompts.map((prompt) => (
              <Paper
                key={prompt}
                variant="outlined"
                onClick={() => openChatWithDraft(prompt)}
                sx={{
                  p: 1.5,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  cursor: 'pointer',
                  borderRadius: 2,
                  transition: 'border-color 0.15s ease, background-color 0.15s ease',
                  '&:hover': {
                    borderColor: 'primary.main',
                    bgcolor: (t) => t.palette.mode === 'dark' ? 'rgba(26,106,255,0.08)' : 'rgba(26,106,255,0.04)',
                  },
                }}
              >
                <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: '0.82rem' }}>
                  {prompt}
                </Typography>
                <ChevronRight sx={{ fontSize: 18, color: 'text.secondary', flexShrink: 0, ml: 1 }} />
              </Paper>
            ))}
          </Box>
        </Box>
      ))}
    </Box>
  )
}
