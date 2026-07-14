/**
 * Login Page — Sentry Agentic authentication portal.
 * Matches brand: dark navy + electric blue, shield logo.
 */

import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  TextField,
  Button,
  Typography,
  Alert,
  CircularProgress,
  InputAdornment,
  IconButton,
} from '@mui/material';
import { Visibility, VisibilityOff, ArrowBack } from '@mui/icons-material';
import { useAuth } from '../contexts/AuthContext';

export default function Login() {
  const navigate = useNavigate();
  const { login } = useAuth();

  const [usernameOrEmail, setUsernameOrEmail] = useState('');
  const [password, setPassword] = useState('');
  const [mfaCode, setMfaCode] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showMfa, setShowMfa] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const mfaInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (showMfa) setTimeout(() => mfaInputRef.current?.focus(), 100);
  }, [showMfa]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(usernameOrEmail, password, showMfa ? mfaCode : undefined);
      navigate('/');
    } catch (err: any) {
      if (err.message === 'MFA_REQUIRED') {
        setShowMfa(true);
        setMfaCode('');
        setError('Please enter your 2FA code to continue');
      } else {
        setError(err.response?.data?.detail || 'Login failed. Please check your credentials.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box
      sx={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        // Dark navy with blue glow — matches brand screenshot
        background: 'radial-gradient(ellipse at 30% 40%, #0D2952 0%, #071428 40%, #040D1A 100%)',
        position: 'relative',
        overflow: 'hidden',
        p: 2,
      }}
    >
      {/* Ambient blue glow top-left */}
      <Box sx={{ position: 'absolute', top: '-10%', left: '-5%', width: 500, height: 500, borderRadius: '50%', background: 'radial-gradient(circle, rgba(26,106,255,0.18) 0%, transparent 65%)', pointerEvents: 'none' }} />
      {/* Ambient glow bottom-right */}
      <Box sx={{ position: 'absolute', bottom: '-5%', right: '-5%', width: 400, height: 400, borderRadius: '50%', background: 'radial-gradient(circle, rgba(26,106,255,0.10) 0%, transparent 65%)', pointerEvents: 'none' }} />

      {/* Card */}
      <Box
        sx={{
          width: '100%',
          maxWidth: 400,
          bgcolor: '#0D1B2E',
          border: '1px solid rgba(26,106,255,0.2)',
          borderRadius: 4,
          p: { xs: 3.5, sm: 5 },
          boxShadow: '0 32px 80px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.04)',
          position: 'relative',
          zIndex: 1,
        }}
      >
        {/* Logo */}
        <Box sx={{ textAlign: 'center', mb: 3.5 }}>
          <Box sx={{ display: 'inline-flex', mb: 2 }}>
            <img
              src="/logo.svg"
              alt="Sentry Agentic"
              style={{ width: 56, height: 64, filter: 'drop-shadow(0 4px 16px rgba(26,106,255,0.6))' }}
            />
          </Box>

          <Typography
            variant="h5"
            component="h1"
            sx={{ color: 'white', fontWeight: 700, letterSpacing: '-0.02em', mb: 0.25 }}
          >
            Sentry{' '}
            <Box component="span" sx={{ color: '#1A6AFF' }}>
              Agentic
            </Box>
          </Typography>

          {/* Progress dots */}
          <Box sx={{ display: 'flex', justifyContent: 'center', gap: 0.75, mt: 1.5, mb: 0.5 }}>
            <Box sx={{ width: 24, height: 5, borderRadius: 3, bgcolor: '#1A6AFF' }} />
            <Box sx={{ width: 8, height: 5, borderRadius: 3, bgcolor: 'rgba(255,255,255,0.15)' }} />
          </Box>

          <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase', fontSize: '0.68rem' }}>
            {showMfa ? 'Two-Factor Authentication' : 'Secure Portal Access'}
          </Typography>
        </Box>

        {error && (
          <Alert
            severity={showMfa ? 'info' : 'error'}
            sx={{ mb: 2.5, bgcolor: 'rgba(26,106,255,0.08)', border: '1px solid rgba(26,106,255,0.25)', color: 'rgba(255,255,255,0.85)', '& .MuiAlert-icon': { color: '#4D9FFF' }, borderRadius: 2 }}
          >
            {error}
          </Alert>
        )}

        <form onSubmit={handleSubmit}>
          {!showMfa ? (
            <>
              {/* Email field */}
              <Box sx={{ mb: 1.5 }}>
                <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.45)', textTransform: 'uppercase', letterSpacing: '0.08em', fontSize: '0.68rem', fontWeight: 600, mb: 0.75, display: 'block' }}>
                  Email Address
                </Typography>
                <TextField
                  fullWidth variant="outlined" placeholder="you@esentry.io"
                  value={usernameOrEmail} onChange={(e) => setUsernameOrEmail(e.target.value)}
                  required autoFocus disabled={loading} sx={fieldSx}
                />
              </Box>

              {/* Password field */}
              <Box sx={{ mb: 0.5 }}>
                <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.45)', textTransform: 'uppercase', letterSpacing: '0.08em', fontSize: '0.68rem', fontWeight: 600, mb: 0.75, display: 'block' }}>
                  Password
                </Typography>
                <TextField
                  fullWidth variant="outlined" type={showPassword ? 'text' : 'password'}
                  placeholder="Enter your password"
                  value={password} onChange={(e) => setPassword(e.target.value)}
                  required disabled={loading} sx={fieldSx}
                  InputProps={{
                    endAdornment: (
                      <InputAdornment position="end">
                        <IconButton onClick={() => setShowPassword(!showPassword)} edge="end" sx={{ color: 'rgba(255,255,255,0.3)', '&:hover': { color: '#4D9FFF' } }}>
                          {showPassword ? <VisibilityOff fontSize="small" /> : <Visibility fontSize="small" />}
                        </IconButton>
                      </InputAdornment>
                    ),
                  }}
                />
              </Box>
            </>
          ) : (
            <>
              <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.5)', mb: 2 }}>
                Signing in as <strong style={{ color: '#4D9FFF' }}>{usernameOrEmail}</strong>
              </Typography>
              <Box sx={{ mb: 0.5 }}>
                <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.45)', textTransform: 'uppercase', letterSpacing: '0.08em', fontSize: '0.68rem', fontWeight: 600, mb: 0.75, display: 'block' }}>
                  2FA Code
                </Typography>
                <TextField
                  fullWidth variant="outlined" placeholder="000000" value={mfaCode}
                  onChange={(e) => { const v = e.target.value.replace(/\D/g, ''); if (v.length <= 6) setMfaCode(v); }}
                  required disabled={loading} inputRef={mfaInputRef} sx={fieldSx}
                  inputProps={{ maxLength: 6, inputMode: 'numeric' }}
                />
              </Box>
              <Button size="small" startIcon={<ArrowBack fontSize="small" />}
                onClick={() => { setShowMfa(false); setMfaCode(''); setError(''); }}
                sx={{ mt: 0.5, color: 'rgba(255,255,255,0.35)', fontSize: '0.78rem', '&:hover': { color: '#4D9FFF', background: 'transparent' } }}>
                Back to login
              </Button>
            </>
          )}

          {/* CTA Button */}
          <Button
            type="submit" fullWidth variant="contained" size="large"
            disabled={loading || (showMfa && mfaCode.length !== 6)}
            sx={{
              mt: 3, py: 1.6, fontWeight: 700, fontSize: '1rem',
              background: 'linear-gradient(90deg, #1A6AFF 0%, #2979FF 100%)',
              boxShadow: '0 4px 24px rgba(26,106,255,0.45)',
              borderRadius: 2.5,
              letterSpacing: '0.02em',
              '&:hover': {
                background: 'linear-gradient(90deg, #0040FF 0%, #1A6AFF 100%)',
                boxShadow: '0 6px 32px rgba(26,106,255,0.6)',
                transform: 'translateY(-1px)',
              },
              '&:disabled': { opacity: 0.45, transform: 'none' },
              transition: 'all 0.18s ease',
            }}
          >
            {loading ? <CircularProgress size={22} color="inherit" /> : showMfa ? 'Verify & Sign In' : 'Continue'}
          </Button>

          {/* Change password link */}
          <Box sx={{ textAlign: 'center', mt: 2 }}>
            <Typography variant="caption" sx={{ color: 'rgba(26,106,255,0.7)', cursor: 'pointer', '&:hover': { color: '#4D9FFF' }, transition: 'color 0.15s' }}>
              Change your password?
            </Typography>
          </Box>
        </form>

        {/* Footer */}
        <Box sx={{ mt: 3.5, pt: 2.5, borderTop: '1px solid rgba(255,255,255,0.05)', textAlign: 'center' }}>
          <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.18)', fontSize: '0.68rem' }}>
            Sentry Agentic &copy; {new Date().getFullYear()}
          </Typography>
        </Box>
      </Box>
    </Box>
  );
}

// Dark-brand field styles
const fieldSx = {
  '& .MuiOutlinedInput-root': {
    color: 'white',
    bgcolor: 'rgba(255,255,255,0.04)',
    borderRadius: 2,
    '& fieldset': { borderColor: 'rgba(255,255,255,0.1)' },
    '&:hover fieldset': { borderColor: 'rgba(26,106,255,0.5)' },
    '&.Mui-focused fieldset': { borderColor: '#1A6AFF', borderWidth: '1.5px' },
  },
  '& .MuiInputBase-input::placeholder': { color: 'rgba(255,255,255,0.2)', opacity: 1 },
};
