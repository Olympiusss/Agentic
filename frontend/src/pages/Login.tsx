/**
 * Login Page - Sentry Agentic SOC
 * Left panel: Pure canvas spider-web thread animation (transparent, dynamic)
 * Right panel: Login card
 * Curtain reveal on mount
 */

import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

/* ---------- 3-bar shield logo ---------- */
const SentryLogo = ({ size, glow }: { size: number; glow?: boolean }) => (
  <svg
    width={size}
    height={Math.round(size * 1.1)}
    viewBox="0 0 100 110"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    style={glow ? { filter: 'drop-shadow(0 0 28px rgba(26,106,255,1))' } : undefined}
  >
    <defs>
      {/* Shield body gradient - electric blue top to deep navy bottom */}
      <linearGradient id="sa-shield-grad" x1="15" y1="0" x2="85" y2="110" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stopColor="#2D6FFF" />
        <stop offset="45%" stopColor="#1A4FE8" />
        <stop offset="100%" stopColor="#0A1E7A" />
      </linearGradient>
      {/* Gloss highlight gradient */}
      <linearGradient id="sa-gloss" x1="10" y1="0" x2="60" y2="50" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stopColor="rgba(255,255,255,0.42)" />
        <stop offset="100%" stopColor="rgba(255,255,255,0)" />
      </linearGradient>
      {/* Bar inner glow */}
      <filter id="sa-bar-glow" x="-30%" y="-10%" width="160%" height="120%">
        <feGaussianBlur stdDeviation="1.2" result="blur" />
        <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
      </filter>
      {/* Outer shield glow */}
      <filter id="sa-outer-glow" x="-20%" y="-15%" width="140%" height="140%">
        <feGaussianBlur stdDeviation="3" result="gblur" />
        <feMerge><feMergeNode in="gblur" /><feMergeNode in="SourceGraphic" /></feMerge>
      </filter>
      <clipPath id="sa-shield-clip">
        <path d="M50 3 L95 20 L95 62 C95 88 50 107 50 107 C50 107 5 88 5 62 L5 20 Z" />
      </clipPath>
    </defs>

    {/* Outer glow halo */}
    <path
      d="M50 3 L95 20 L95 62 C95 88 50 107 50 107 C50 107 5 88 5 62 L5 20 Z"
      fill="rgba(26,106,255,0.25)"
      filter="url(#sa-outer-glow)"
    />

    {/* Shield body */}
    <path
      d="M50 3 L95 20 L95 62 C95 88 50 107 50 107 C50 107 5 88 5 62 L5 20 Z"
      fill="url(#sa-shield-grad)"
    />

    {/* Inner border/edge highlight */}
    <path
      d="M50 7 L91 23 L91 62 C91 85 50 103 50 103 C50 103 9 85 9 62 L9 23 Z"
      fill="none"
      stroke="rgba(120,170,255,0.35)"
      strokeWidth="1.5"
    />

    {/* 3 glass bars - left shorter, center tallest, right shorter */}
    {/* Left bar */}
    <rect x="21" y="42" width="14" height="42" rx="7" fill="rgba(255,255,255,0.15)" />
    <rect x="21" y="42" width="14" height="42" rx="7"
      fill="none" stroke="rgba(255,255,255,0.7)" strokeWidth="1.2"
      filter="url(#sa-bar-glow)"
    />
    <rect x="23" y="44" width="6" height="14" rx="3" fill="rgba(255,255,255,0.45)" />

    {/* Center bar - tallest */}
    <rect x="43" y="32" width="14" height="52" rx="7" fill="rgba(255,255,255,0.15)" />
    <rect x="43" y="32" width="14" height="52" rx="7"
      fill="none" stroke="rgba(255,255,255,0.75)" strokeWidth="1.2"
      filter="url(#sa-bar-glow)"
    />
    <rect x="45" y="34" width="6" height="16" rx="3" fill="rgba(255,255,255,0.5)" />

    {/* Right bar */}
    <rect x="65" y="42" width="14" height="42" rx="7" fill="rgba(255,255,255,0.15)" />
    <rect x="65" y="42" width="14" height="42" rx="7"
      fill="none" stroke="rgba(255,255,255,0.7)" strokeWidth="1.2"
      filter="url(#sa-bar-glow)"
    />
    <rect x="67" y="44" width="6" height="14" rx="3" fill="rgba(255,255,255,0.45)" />

    {/* Top gloss highlight */}
    <path
      d="M50 7 L91 23 L91 46 C70 38 30 38 9 46 L9 23 Z"
      fill="url(#sa-gloss)"
      clipPath="url(#sa-shield-clip)"
    />
  </svg>
);

/* ---------- Spider-web canvas animation ---------- */
interface Node {
  x: number; y: number;
  vx: number; vy: number;
  radius: number;
  pulsePhase: number;
}

const SpiderWebCanvas = ({ width, height }: { width: number; height: number }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animRef   = useRef<number>(0);
  const nodesRef  = useRef<Node[]>([]);

  /* Build initial nodes */
  const initNodes = useCallback((w: number, h: number) => {
    const count = 55;
    return Array.from({ length: count }, () => ({
      x:          Math.random() * w,
      y:          Math.random() * h,
      vx:         (Math.random() - 0.5) * 0.55,
      vy:         (Math.random() - 0.5) * 0.55,
      radius:     Math.random() * 1.6 + 0.4,
      pulsePhase: Math.random() * Math.PI * 2,
    }));
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    canvas.width  = width;
    canvas.height = height;

    nodesRef.current = initNodes(width, height);
    const nodes = nodesRef.current;
    const MAX_DIST = 160;   // max distance to draw a thread
    const MOUSE_RADIUS = 120;

    let mouseX = width / 2;
    let mouseY = height / 2;
    let mouseActive = false;
    let tick = 0;

    const onMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      mouseX = e.clientX - rect.left;
      mouseY = e.clientY - rect.top;
      mouseActive = true;
    };
    const onLeave = () => { mouseActive = false; };
    canvas.addEventListener('mousemove', onMove);
    canvas.addEventListener('mouseleave', onLeave);

    const draw = () => {
      tick++;
      ctx.clearRect(0, 0, width, height);

      /* Move nodes */
      nodes.forEach(n => {
        /* Gentle drift */
        n.x += n.vx;
        n.y += n.vy;

        /* Soft bounce off walls with padding */
        if (n.x < 30)       { n.vx += 0.04; }
        if (n.x > width-30) { n.vx -= 0.04; }
        if (n.y < 30)       { n.vy += 0.04; }
        if (n.y > height-30){ n.vy -= 0.04; }

        /* Speed cap */
        const spd = Math.sqrt(n.vx*n.vx + n.vy*n.vy);
        if (spd > 1.0) { n.vx *= 0.98; n.vy *= 0.98; }

        /* Mouse repulsion - nodes drift away gently */
        if (mouseActive) {
          const dx = n.x - mouseX;
          const dy = n.y - mouseY;
          const d  = Math.sqrt(dx*dx + dy*dy);
          if (d < MOUSE_RADIUS && d > 0) {
            const force = (MOUSE_RADIUS - d) / MOUSE_RADIUS * 0.015;
            n.vx += (dx/d) * force;
            n.vy += (dy/d) * force;
          }
        }
      });

      /* Draw threads between nearby nodes */
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i];
          const b = nodes[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const dist = Math.sqrt(dx*dx + dy*dy);

          if (dist < MAX_DIST) {
            const alpha = (1 - dist / MAX_DIST) * 0.38;
            /* Subtle shimmer */
            const shimmer = 0.85 + 0.15 * Math.sin(tick * 0.03 + a.pulsePhase);
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.strokeStyle = `rgba(120,180,255,${(alpha * shimmer).toFixed(3)})`;
            ctx.lineWidth = 0.5;
            ctx.stroke();
          }
        }
      }

      /* Draw nodes as tiny glowing dots */
      nodes.forEach(n => {
        const pulse = 0.6 + 0.4 * Math.sin(tick * 0.04 + n.pulsePhase);
        const r = n.radius * pulse;
        const grd = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, r * 5);
        grd.addColorStop(0,   `rgba(130,190,255,${(0.9 * pulse).toFixed(2)})`);
        grd.addColorStop(0.4, `rgba(80,140,255,${(0.35 * pulse).toFixed(2)})`);
        grd.addColorStop(1,   'rgba(26,106,255,0)');
        ctx.beginPath();
        ctx.arc(n.x, n.y, r * 5, 0, Math.PI * 2);
        ctx.fillStyle = grd;
        ctx.fill();

        /* Hard centre dot */
        ctx.beginPath();
        ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(180,220,255,${(0.85 * pulse).toFixed(2)})`;
        ctx.fill();
      });

      /* Mouse attraction point - extra bright hub when hovering */
      if (mouseActive) {
        const hub = ctx.createRadialGradient(mouseX, mouseY, 0, mouseX, mouseY, 40);
        hub.addColorStop(0,   'rgba(100,160,255,0.25)');
        hub.addColorStop(1,   'rgba(26,106,255,0)');
        ctx.beginPath();
        ctx.arc(mouseX, mouseY, 40, 0, Math.PI * 2);
        ctx.fillStyle = hub;
        ctx.fill();

        nodes.forEach(n => {
          const dx = n.x - mouseX;
          const dy = n.y - mouseY;
          const dist = Math.sqrt(dx*dx + dy*dy);
          if (dist < 80) {
            const alpha = (1 - dist/80) * 0.5;
            ctx.beginPath();
            ctx.moveTo(mouseX, mouseY);
            ctx.lineTo(n.x, n.y);
            ctx.strokeStyle = `rgba(150,200,255,${alpha.toFixed(2)})`;
            ctx.lineWidth = 0.7;
            ctx.stroke();
          }
        });
      }

      animRef.current = requestAnimationFrame(draw);
    };

    draw();
    return () => {
      cancelAnimationFrame(animRef.current);
      canvas.removeEventListener('mousemove', onMove);
      canvas.removeEventListener('mouseleave', onLeave);
    };
  }, [width, height, initNodes]);

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        opacity: 0.92,
        display: 'block',
      }}
    />
  );
};

/* ---------- Input base style ---------- */
const baseInput: React.CSSProperties = {
  width: '100%',
  padding: '11px 14px',
  borderRadius: 8,
  border: '1.5px solid #dde1ea',
  fontSize: 14,
  color: '#1a1a2e',
  background: '#f7f8fc',
  boxSizing: 'border-box',
  fontFamily: 'inherit',
  outline: 'none',
  transition: 'border-color 0.2s, box-shadow 0.2s',
};

/* ===================================================================
   Main Login component
   =================================================================== */
export default function Login() {
  const navigate = useNavigate();
  const { login } = useAuth();

  const [username, setUsername]             = useState('');
  const [password, setPassword]             = useState('');
  const [mfaCode, setMfaCode]               = useState('');
  const [showPw, setShowPw]                 = useState(false);
  const [showMfa, setShowMfa]               = useState(false);
  const [loading, setLoading]               = useState(false);
  const [error, setError]                   = useState('');
  const [curtainOpen, setCurtainOpen]       = useState(false);
  const [contentVisible, setContentVisible] = useState(false);
  const [panelSize, setPanelSize]           = useState({ w: 0, h: 0 });
  const mfaRef    = useRef<HTMLInputElement>(null);
  const leftPanel = useRef<HTMLDivElement>(null);

  /* Curtain timing */
  useEffect(() => {
    const t1 = setTimeout(() => setCurtainOpen(true),     700);
    const t2 = setTimeout(() => setContentVisible(true), 1500);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, []);

  /* Measure left panel for canvas */
  useEffect(() => {
    if (!leftPanel.current) return;
    const ro = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect;
      setPanelSize({ w: Math.round(width), h: Math.round(height) });
    });
    ro.observe(leftPanel.current);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (showMfa) setTimeout(() => mfaRef.current?.focus(), 120);
  }, [showMfa]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(username, password, showMfa ? mfaCode : undefined);
      navigate('/');
    } catch (err: any) {
      if (err.message === 'MFA_REQUIRED') {
        setShowMfa(true);
        setMfaCode('');
        setError('Enter your 2-factor authentication code.');
      } else {
        setError(err.response?.data?.detail || 'Invalid credentials. Please check username and password.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      position: 'relative',
      width: '100vw',
      height: '100vh',
      overflow: 'hidden',
      fontFamily: '"Inter","Roboto",sans-serif',
    }}>

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
        @keyframes sa-spin { to { transform: rotate(360deg); } }

        .sa-input:focus {
          border-color: #1A6AFF !important;
          box-shadow: 0 0 0 3px rgba(26,106,255,0.14) !important;
          background: #fff !important;
        }
        .sa-btn:hover:not(:disabled) {
          background: #1133e8 !important;
          transform: translateY(-1px);
          box-shadow: 0 8px 24px rgba(26,106,255,0.45) !important;
        }
        .sa-link {
          background: none; border: none; cursor: pointer;
          font-size: 12px; color: #1A6AFF; font-weight: 500;
          padding: 0; font-family: inherit;
        }
        .sa-link:hover { text-decoration: underline; }
      `}</style>

      {/* ===== BACKGROUND ===== */}
      <div style={{ position: 'absolute', inset: 0, display: 'flex' }}>
        <div style={{
          width: '50%', height: '100%',
          background: 'radial-gradient(ellipse at 60% 50%, #0c1fa8 0%, #040f5c 35%, #000820 100%)',
        }} />
        {/* Right panel - brand-synced dark navy blue */}
        <div style={{
          width: '50%', height: '100%',
          background: 'linear-gradient(160deg, #0a0e1f 0%, #0d1535 50%, #060c1a 100%)',
        }} />
      </div>

      {/* ===== LEFT PANEL - spider web canvas ===== */}
      <div
        ref={leftPanel}
        style={{
          position: 'absolute',
          left: 0, top: 0,
          width: '50%', height: '100%',
          zIndex: 5,
          opacity: contentVisible ? 1 : 0,
          transition: 'opacity 1s ease 0.3s',
        }}
      >
        {panelSize.w > 0 && panelSize.h > 0 && (
          <SpiderWebCanvas width={panelSize.w} height={panelSize.h} />
        )}
      </div>

      {/* ===== RIGHT PANEL - Login card ===== */}
      <div style={{
        position: 'absolute', inset: 0, zIndex: 10,
        display: 'flex', alignItems: 'center', justifyContent: 'flex-end',
        opacity: contentVisible ? 1 : 0,
        transition: 'opacity 0.6s ease 0.4s',
        pointerEvents: contentVisible ? 'auto' : 'none',
      }}>
        <div style={{
          width: '50%', height: '100%',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <div style={{
            background: '#ffffff',
            borderRadius: 20,
            boxShadow: '0 24px 64px rgba(0,0,0,0.65), 0 6px 24px rgba(10,30,100,0.35), 0 0 0 1px rgba(26,106,255,0.12)',
            padding: '22px 28px 20px',
            width: 300,
            maxWidth: '88vw',
          }}>

            {/* -- Header -- */}
            <div style={{ textAlign: 'center', marginBottom: 12 }}>
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                gap: 9, marginBottom: 6,
              }}>
                <SentryLogo size={34} />
                <div style={{ textAlign: 'left' }}>
                  <div style={{
                    fontSize: '20px',
                    fontWeight: 800,
                    color: '#0a1128',
                    letterSpacing: '-0.025em',
                    lineHeight: 1.1,
                    fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, sans-serif',
                  }}>
                    Sentry Agentic
                  </div>
                  <div style={{
                    fontSize: '9px',
                    fontWeight: 700,
                    color: '#1A6AFF',
                    letterSpacing: '3px',
                    marginTop: 1,
                    fontFamily: '"Inter", sans-serif',
                  }}>
                    S O C
                  </div>
                </div>
              </div>
              <p style={{
                fontSize: 12,
                color: '#7a8399',
                margin: '4px 0 0',
                lineHeight: 1.45,
                fontWeight: 400,
                fontFamily: '"Inter", sans-serif',
              }}>
                Welcome back! Please login to your account.
              </p>
            </div>

            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              gap: 0, marginBottom: 14,
            }}>
              <div style={{
                width: 10, height: 10, borderRadius: '50%',
                background: !showMfa ? '#1A6AFF' : '#d1d5db',
                flexShrink: 0,
                transition: 'background 0.3s',
              }} />
              <div style={{
                flex: '0 0 48px', height: 2,
                background: 'linear-gradient(90deg, #1A6AFF 0%, #d1d5db 100%)',
                transition: 'background 0.3s',
              }} />
              <div style={{
                width: 10, height: 10, borderRadius: '50%',
                background: showMfa ? '#1A6AFF' : '#d1d5db',
                border: !showMfa ? '2px solid #d1d5db' : 'none',
                flexShrink: 0,
                boxSizing: 'border-box',
                transition: 'background 0.3s',
              }} />
            </div>

            {/* Error */}
            {error && (
              <div style={{
                padding: '10px 14px', borderRadius: 8, marginBottom: 14,
                fontSize: 13, lineHeight: 1.4,
                background: showMfa ? '#eff6ff' : '#fff0f0',
                color:      showMfa ? '#1A6AFF' : '#b91c1c',
                border: `1px solid ${showMfa ? '#bfdbfe' : '#fecaca'}`,
              }}>
                {error}
              </div>
            )}

            {/* Form */}
            <form onSubmit={handleSubmit}>
              {!showMfa ? (
                <>
                  <div style={{ marginBottom: 10 }}>
                    <label style={{
                      fontSize: 12.5,
                      fontWeight: 700,
                      color: '#1a1a2e',
                      display: 'block', marginBottom: 5,
                    }}>
                      Username
                    </label>
                    <input
                      className="sa-input"
                      type="text"
                      placeholder="Enter your username"
                      value={username}
                      onChange={e => setUsername(e.target.value)}
                      required
                      autoFocus
                      disabled={loading}
                      style={{ ...baseInput, fontSize: 14.5 }}
                    />
                  </div>

                  <div style={{ marginBottom: 2 }}>
                    <label style={{
                      fontSize: 12.5,
                      fontWeight: 700,
                      color: '#1a1a2e',
                      display: 'block', marginBottom: 5,
                    }}>
                      Password
                    </label>
                    <div style={{ position: 'relative' }}>
                      <input
                        className="sa-input"
                        type={showPw ? 'text' : 'password'}
                        placeholder="Enter your password"
                        value={password}
                        onChange={e => setPassword(e.target.value)}
                        required
                        disabled={loading}
                        style={{ ...baseInput, paddingRight: 52, fontSize: 14.5 }}
                      />
                      <button
                        type="button"
                        onClick={() => setShowPw(v => !v)}
                        style={{
                          position: 'absolute', right: 12, top: '50%',
                          transform: 'translateY(-50%)',
                          background: 'none', border: 'none', cursor: 'pointer',
                          fontSize: 12, color: '#6b7280',
                          fontFamily: 'inherit', fontWeight: 500, padding: '2px 4px',
                        }}
                      >
                        {showPw ? 'Hide' : 'Show'}
                      </button>
                    </div>
                  </div>

                  <div style={{ marginBottom: 14 }}>
                    <button
                      type="button"
                      className="sa-link"
                      style={{ fontSize: 12.5, fontWeight: 700 }}
                    >
                      Forgot Password
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <p style={{ fontSize: 13, color: '#6b7280', marginBottom: 14 }}>
                    Signing in as <strong style={{ color: '#1a1a2e' }}>{username}</strong>
                  </p>
                  <div style={{ marginBottom: 16 }}>
                    <label style={{
                      fontSize: 12, fontWeight: 600, color: '#374151',
                      display: 'block', marginBottom: 6,
                    }}>
                      2FA Code
                    </label>
                    <input
                      className="sa-input"
                      type="text"
                      placeholder="000000"
                      value={mfaCode}
                      onChange={e => {
                        const v = e.target.value.replace(/\D/g, '');
                        if (v.length <= 6) setMfaCode(v);
                      }}
                      required
                      disabled={loading}
                      maxLength={6}
                      inputMode="numeric"
                      ref={mfaRef}
                      style={{
                        ...baseInput,
                        letterSpacing: '6px', textAlign: 'center', fontSize: 20,
                      }}
                    />
                  </div>
                  <button
                    type="button"
                    className="sa-link"
                    onClick={() => { setShowMfa(false); setMfaCode(''); setError(''); }}
                    style={{ marginBottom: 16, display: 'block' }}
                  >
                    Back to login
                  </button>
                </>
              )}

              <button
                className="sa-btn"
                type="submit"
                disabled={loading || (showMfa && mfaCode.length !== 6)}
                style={{
                  width: '100%', padding: '11px 0',
                  borderRadius: 10, border: 'none',
                  background: loading || (showMfa && mfaCode.length !== 6)
                    ? '#8faaf5' : 'linear-gradient(135deg, #1A3AFF 0%, #2235D6 100%)',
                  color: '#fff', fontWeight: 700, fontSize: 14.5,
                  fontFamily: 'inherit',
                  cursor: loading || (showMfa && mfaCode.length !== 6)
                    ? 'not-allowed' : 'pointer',
                  display: 'flex', alignItems: 'center',
                  justifyContent: 'center', gap: 8,
                  letterSpacing: '0.2px',
                  transition: 'background 0.2s, transform 0.15s, box-shadow 0.2s',
                }}
              >
                {loading ? (
                  <>
                    <span style={{
                      width: 16, height: 16,
                      border: '2px solid rgba(255,255,255,0.35)',
                      borderTopColor: '#fff',
                      borderRadius: '50%',
                      display: 'inline-block',
                      animation: 'sa-spin 0.75s linear infinite',
                    }} />
                    Signing in...
                  </>
                ) : showMfa ? 'Verify and Sign In' : 'Login'}
              </button>
            </form>

            <p style={{
              textAlign: 'center', fontSize: 10.5,
              color: '#a0aec0', margin: '12px 0 0', lineHeight: 1.4,
            }}>
              Security Operations Portal
              {' '}&middot;{' '}
              <span style={{ color: '#1A6AFF', fontWeight: 600 }}>Sentry Agentic</span>
            </p>
          </div>
        </div>
      </div>

      {/* ===== CURTAIN ===== */}
      <div style={{
        position: 'absolute', inset: 0, zIndex: 20,
        pointerEvents: curtainOpen ? 'none' : 'auto',
      }}>
        {/* Left curtain */}
        <div style={{
          position: 'absolute', left: 0, top: 0, width: '50%', height: '100%',
          background: 'radial-gradient(ellipse at 65% 50%, #0c22b8 0%, #040f5c 38%, #000820 100%)',
          transform: curtainOpen ? 'translateX(-100%)' : 'translateX(0)',
          transition: 'transform 1.1s cubic-bezier(0.77,0,0.175,1)',
        }} />
        {/* Right curtain */}
        <div style={{
          position: 'absolute', right: 0, top: 0, width: '50%', height: '100%',
          background: 'linear-gradient(160deg, #0a0e1f 0%, #0d1535 50%, #060c1a 100%)',
          transform: curtainOpen ? 'translateX(100%)' : 'translateX(0)',
          transition: 'transform 1.1s cubic-bezier(0.77,0,0.175,1)',
        }} />

        {/* Centre reveal logo */}
        <div style={{
          position: 'absolute', left: '50%', top: '50%',
          transform: 'translate(-50%, -50%)',
          display: 'flex', flexDirection: 'column',
          alignItems: 'center', gap: 14,
          zIndex: 21, pointerEvents: 'none',
          opacity: curtainOpen ? 0 : 1,
          transition: 'opacity 0.4s ease 0.5s',
        }}>
          <SentryLogo size={90} glow />
          <div style={{
            fontSize: '12px', fontWeight: 700, letterSpacing: '5px',
            color: '#1A6AFF', textTransform: 'uppercase',
            textShadow: '0 0 24px rgba(26,106,255,0.9)',
          }}>
            Sentry Agentic
          </div>
        </div>
      </div>
    </div>
  );
}
