import { createTheme, alpha } from '@mui/material/styles'

/* ============================================================
   Sentry Agentic Brand Tokens
   Primary: #1A6AFF (Sentry Blue)
   Background light: #F0F4FF / white
   Background dark:  #060D1F (near-black navy)
   ============================================================ */

const brand = {
  blue:   '#1A6AFF',
  blue2:  '#3D83FF',
  blue3:  '#5BA4FF',
  navy:   '#060D1F',
  navy2:  '#0D1A36',
  navy3:  '#162040',
  navy4:  '#1E2D50',
  white:  '#FFFFFF',
  off:    '#F0F4FF',   // off-white with blue tint
  off2:   '#E4ECFF',
  slate:  '#7B93BB',   // muted text on dark
  slate2: '#A8BBDD',
  divDark: 'rgba(255,255,255,0.08)',
  divLight:'rgba(26,106,255,0.12)',
}

export const severityColors = {
  critical: '#DC2626',
  high:     '#EF4444',
  medium:   '#F97316',
  low:      '#FACC15',
}

export const statusColors = {
  open:        '#1A6AFF',
  'in-progress': '#F59E0B',
  'in_progress': '#F59E0B',
  resolved:    '#10B981',
  closed:      '#64748B',
  pending:     '#F59E0B',
  approved:    '#10B981',
  rejected:    '#F43F5E',
  executed:    '#1A6AFF',
}

export const createM3Theme = (mode: 'light' | 'dark') => {
  const isDark = mode === 'dark'

  return createTheme({
    palette: {
      mode,
      primary: {
        main:         brand.blue,
        light:        brand.blue2,
        dark:         '#1050CC',
        contrastText: '#ffffff',
      },
      secondary: {
        main:  isDark ? brand.slate2 : brand.navy4,
        light: brand.slate,
        dark:  brand.navy3,
      },
      error:   { main: '#EF4444', light: '#F87171' },
      warning: { main: '#F59E0B', light: '#FBBF24' },
      success: { main: '#10B981', light: '#34D399' },
      info:    { main: brand.blue, light: brand.blue2 },
      background: {
        default: isDark ? brand.navy  : brand.off,
        paper:   isDark ? brand.navy2 : brand.white,
      },
      text: {
        primary:   isDark ? '#E8EEFF' : brand.navy,
        secondary: isDark ? brand.slate2 : brand.navy4,
        disabled:  isDark ? brand.slate : '#94A3B8',
      },
      divider: isDark ? brand.divDark : brand.divLight,
    },

    typography: {
      fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      h1: { fontWeight: 700, letterSpacing: '-0.02em' },
      h2: { fontWeight: 700, letterSpacing: '-0.02em' },
      h3: { fontWeight: 600, letterSpacing: '-0.01em' },
      h4: { fontWeight: 600, letterSpacing: '-0.01em' },
      h5: { fontWeight: 600 },
      h6: { fontWeight: 600 },
      subtitle1: { fontWeight: 500 },
      subtitle2: { fontWeight: 500 },
      body1: { fontSize: '0.875rem' },
      body2: { fontSize: '0.8125rem' },
      caption: {
        fontSize: '0.75rem',
        color: isDark ? brand.slate2 : brand.navy4,
      },
      button: { textTransform: 'none', fontWeight: 600 },
    },

    shape: { borderRadius: 10 },

    components: {
      MuiCssBaseline: {
        styleOverrides: {
          body: {
            scrollbarColor: isDark
              ? `${brand.navy3} ${brand.navy}`
              : `${brand.off2} ${brand.off}`,
            '&::-webkit-scrollbar': { width: 6, height: 6 },
            '&::-webkit-scrollbar-thumb': {
              backgroundColor: isDark ? brand.navy4 : brand.off2,
              borderRadius: 3,
              '&:hover': { backgroundColor: brand.blue },
            },
            '&::-webkit-scrollbar-track': {
              backgroundColor: isDark ? brand.navy : brand.off,
            },
          },
        },
      },

      MuiButton: {
        styleOverrides: {
          root: { borderRadius: 8, padding: '6px 16px', fontWeight: 600 },
          contained: {
            boxShadow: 'none',
            '&:hover': {
              boxShadow: `0 4px 16px ${alpha(brand.blue, 0.35)}`,
              transform: 'translateY(-1px)',
            },
            transition: 'box-shadow 0.2s, transform 0.15s',
          },
          containedPrimary: {
            background: `linear-gradient(135deg, ${brand.blue} 0%, ${brand.blue2} 100%)`,
            '&:hover': {
              background: `linear-gradient(135deg, #1050CC 0%, ${brand.blue} 100%)`,
            },
          },
          outlined: {
            borderColor: isDark ? alpha(brand.blue, 0.4) : alpha(brand.blue, 0.5),
            color: brand.blue,
            '&:hover': {
              borderColor: brand.blue,
              backgroundColor: alpha(brand.blue, 0.06),
            },
          },
        },
        defaultProps: { disableElevation: true },
      },

      MuiPaper: {
        styleOverrides: {
          root: {
            backgroundImage: 'none',
            borderRadius: 12,
            border: `1px solid ${isDark ? brand.divDark : brand.divLight}`,
          },
          outlined: {
            borderColor: isDark ? brand.divDark : brand.divLight,
          },
          elevation1: {
            boxShadow: isDark
              ? '0 4px 24px rgba(0,0,0,0.4)'
              : `0 4px 24px ${alpha(brand.blue, 0.08)}`,
          },
        },
        defaultProps: { elevation: 0 },
      },

      MuiCard: {
        styleOverrides: {
          root: {
            borderRadius: 14,
            border: `1px solid ${isDark ? brand.divDark : brand.divLight}`,
            backgroundImage: 'none',
            background: isDark ? brand.navy2 : brand.white,
            boxShadow: isDark
              ? '0 2px 16px rgba(0,0,0,0.3)'
              : `0 2px 16px ${alpha(brand.blue, 0.06)}`,
            transition: 'box-shadow 0.2s',
            '&:hover': {
              boxShadow: isDark
                ? '0 4px 24px rgba(0,0,0,0.5)'
                : `0 4px 24px ${alpha(brand.blue, 0.12)}`,
            },
          },
        },
        defaultProps: { elevation: 0 },
      },

      MuiCardContent: {
        styleOverrides: {
          root: { padding: 16, '&:last-child': { paddingBottom: 16 } },
        },
      },

      MuiChip: {
        styleOverrides: {
          root: { borderRadius: 6, fontWeight: 600, fontSize: '0.75rem' },
          colorPrimary: {
            backgroundColor: alpha(brand.blue, isDark ? 0.2 : 0.1),
            color: brand.blue,
          },
          sizeSmall: { height: 22 },
        },
      },

      MuiTableCell: {
        styleOverrides: {
          root: {
            borderColor: isDark ? brand.divDark : brand.divLight,
            padding: '8px 12px',
            fontSize: '0.8125rem',
          },
          head: {
            fontWeight: 700,
            backgroundColor: isDark ? brand.navy : brand.off,
            color: isDark ? brand.slate2 : brand.navy4,
            fontSize: '0.72rem',
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
          },
        },
      },

      MuiTableRow: {
        styleOverrides: {
          root: {
            '&:hover': {
              backgroundColor: isDark ? alpha(brand.blue, 0.04) : alpha(brand.blue, 0.03),
            },
          },
        },
      },

      MuiTabs: {
        styleOverrides: {
          root: { minHeight: 40 },
          indicator: { height: 2, borderRadius: 1, backgroundColor: brand.blue },
        },
      },

      MuiTab: {
        styleOverrides: {
          root: {
            minHeight: 40,
            padding: '8px 16px',
            fontWeight: 500,
            textTransform: 'none',
            fontSize: '0.875rem',
            color: isDark ? brand.slate2 : brand.navy4,
            '&.Mui-selected': { color: brand.blue, fontWeight: 700 },
          },
        },
      },

      MuiTextField: {
        styleOverrides: {
          root: {
            '& .MuiOutlinedInput-root': {
              borderRadius: 8,
              '& fieldset': {
                borderColor: isDark ? alpha(brand.white, 0.12) : alpha(brand.blue, 0.2),
              },
              '&:hover fieldset': {
                borderColor: isDark ? alpha(brand.white, 0.25) : brand.blue,
              },
              '&.Mui-focused fieldset': {
                borderColor: brand.blue,
                boxShadow: `0 0 0 3px ${alpha(brand.blue, 0.15)}`,
              },
            },
          },
        },
        defaultProps: { size: 'small' },
      },

      MuiSelect: {
        styleOverrides: { root: { borderRadius: 8 } },
        defaultProps: { size: 'small' },
      },

      MuiDialog: {
        styleOverrides: {
          paper: { borderRadius: 18, backgroundImage: 'none' },
        },
      },

      MuiDialogTitle: {
        styleOverrides: {
          root: { fontSize: '1.125rem', fontWeight: 700, padding: '16px 20px' },
        },
      },

      MuiDialogContent: {
        styleOverrides: { root: { padding: '8px 20px 16px' } },
      },

      MuiDialogActions: {
        styleOverrides: { root: { padding: '12px 20px 16px' } },
      },

      MuiTooltip: {
        styleOverrides: {
          tooltip: {
            backgroundColor: isDark ? brand.navy3 : brand.navy,
            color: brand.white,
            fontSize: '0.75rem',
            borderRadius: 6,
            padding: '6px 10px',
          },
          arrow: {
            color: isDark ? brand.navy3 : brand.navy,
          },
        },
      },

      MuiAlert: {
        styleOverrides: {
          root: { borderRadius: 10 },
          standardError:   { backgroundColor: alpha('#EF4444', isDark ? 0.15 : 0.08), color: '#EF4444' },
          standardWarning: { backgroundColor: alpha('#F59E0B', isDark ? 0.15 : 0.08), color: '#D97706' },
          standardSuccess: { backgroundColor: alpha('#10B981', isDark ? 0.15 : 0.08), color: '#059669' },
          standardInfo:    { backgroundColor: alpha(brand.blue, isDark ? 0.15 : 0.08), color: brand.blue },
        },
      },

      MuiDrawer: {
        styleOverrides: {
          paper: {
            backgroundImage: 'none',
            backgroundColor: isDark ? brand.navy : brand.white,
            borderRight: `1px solid ${isDark ? brand.divDark : brand.divLight}`,
          },
        },
      },

      MuiListItemButton: {
        styleOverrides: {
          root: {
            borderRadius: 8,
            '&.Mui-selected': {
              backgroundColor: alpha(brand.blue, isDark ? 0.18 : 0.1),
              '&:hover': { backgroundColor: alpha(brand.blue, isDark ? 0.24 : 0.15) },
            },
            '&:hover': { backgroundColor: alpha(brand.blue, isDark ? 0.1 : 0.06) },
          },
        },
      },

      MuiListItemIcon: {
        styleOverrides: { root: { minWidth: 36, color: 'inherit' } },
      },

      MuiIconButton: {
        styleOverrides: { root: { borderRadius: 8 } },
      },

      MuiSnackbar: {
        defaultProps: { anchorOrigin: { vertical: 'top', horizontal: 'right' } },
      },

      MuiLinearProgress: {
        styleOverrides: {
          root: { borderRadius: 4, backgroundColor: alpha(brand.blue, 0.15) },
          bar:  { backgroundColor: brand.blue, borderRadius: 4 },
        },
      },

      MuiSwitch: {
        styleOverrides: {
          switchBase: {
            '&.Mui-checked': { color: brand.blue },
            '&.Mui-checked + .MuiSwitch-track': { backgroundColor: brand.blue },
          },
        },
      },
    },
  })
}

export { brand }
