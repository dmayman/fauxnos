import { useEffect, useState, useRef, useCallback } from 'react'
import {
  Sun, Moon, Settings2, GripVertical, X, Plus, Check,
  Volume1, Volume2, VolumeX, Speaker, ChevronRight, ChevronDown,
  Music, Radio, Disc, Trash2, RefreshCw, Wifi, WifiOff, Copy,
  ExternalLink, AlertCircle,
} from 'lucide-react'

/**
 * ComponentSheet
 *
 * Mounted at `?vibe=1` (see App.jsx). Renders the full design language —
 * colors, type, primitives, composites — on one scrollable page so we can
 * sign off on the vibe before migrating real components.
 *
 * Nothing here is shipped UI. Once approved, primitives stay (the .fx-*
 * classes), composites become reference for the real component edits.
 */
export default function ComponentSheet() {
  // Theme persistence — write to <html data-theme="..."> so the tokens
  // route through the same vars the live app will eventually use.
  const initial = typeof window !== 'undefined'
    ? (window.localStorage.getItem('fx-theme') || 'dark')
    : 'dark'
  const [theme, setTheme] = useState(initial)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    window.localStorage.setItem('fx-theme', theme)
  }, [theme])

  return (
    <div className="fx-sheet fx-root">
      <header className="fx-sheet-bar">
        <div className="fx-sheet-bar-left">
          <span className="fx-sheet-wordmark">
            <span className="fx-dot accent pulse" style={{ color: 'var(--fx-accent)' }} />
            fauxnos
          </span>
          <span className="fx-sheet-tag">design preview · Warm Studio</span>
        </div>
        <div className="fx-sheet-bar-right">
          <span className="fx-caption">Theme</span>
          <div className="fx-theme-toggle" role="tablist" aria-label="Theme">
            <button
              className={theme === 'dark' ? 'active' : ''}
              onClick={() => setTheme('dark')}
              role="tab"
              aria-selected={theme === 'dark'}
            >
              <Moon size={12} /> Dark
            </button>
            <button
              className={theme === 'light' ? 'active' : ''}
              onClick={() => setTheme('light')}
              role="tab"
              aria-selected={theme === 'light'}
            >
              <Sun size={12} /> Light
            </button>
          </div>
          <a className="fx-btn ghost sm" href="/" title="Back to live UI">Back</a>
        </div>
      </header>

      <main className="fx-sheet-main">
        <Hero />
        <Foundations />
        <Buttons />
        <IconsAndDots />
        <Badges />
        <Forms />
        <VolumeSliders />
        <Segmented />
        <ComposedHeader />
        <DevicesPopoverPreview />
        <GroupCardPreviews />
        <SourceRowPreviews />
        <DevicePanelPreview />
        <TimelinePreview />
        <EmptyStates />
      </main>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────── */

function Section({ title, desc, children }) {
  return (
    <section className="fx-sheet-section">
      <div>
        <h2>{title}</h2>
        {desc && <p className="fx-sheet-section-desc">{desc}</p>}
      </div>
      {children}
    </section>
  )
}

function Hero() {
  return (
    <div className="fx-sheet-hero">
      <h1 className="fx-h1">Warm Studio</h1>
      <p className="fx-small" style={{ maxWidth: '60ch' }}>
        Visual language for the Fauxnos management UI. Warm dark surfaces,
        a single amber accent, hairline borders, and a six-step type scale.
        Scroll for every primitive; resize the window for responsive checks.
      </p>
    </div>
  )
}

/* ── Foundations ──────────────────────────────────────────────────────────── */

function Swatch({ name, varName }) {
  return (
    <div className="fx-swatch">
      <div className="fx-swatch-chip" style={{ background: `var(${varName})` }} />
      <div className="fx-swatch-name">{name}</div>
      <div className="fx-swatch-val">{varName}</div>
    </div>
  )
}

function Foundations() {
  return (
    <>
      <Section
        title="Color"
        desc="Surfaces lift through subtle elevation rather than border weight. The single amber accent carries active states everywhere — source pills, focus rings, install progress."
      >
        <div className="fx-sheet-grid">
          <Swatch name="bg"          varName="--fx-bg" />
          <Swatch name="surface-1"   varName="--fx-surface-1" />
          <Swatch name="surface-2"   varName="--fx-surface-2" />
          <Swatch name="surface-3"   varName="--fx-surface-3" />
          <Swatch name="accent"      varName="--fx-accent" />
          <Swatch name="accent-soft" varName="--fx-accent-soft" />
          <Swatch name="ok"          varName="--fx-ok" />
          <Swatch name="warn"        varName="--fx-warn" />
          <Swatch name="err"         varName="--fx-err" />
          <Swatch name="text"        varName="--fx-text" />
          <Swatch name="text-2"      varName="--fx-text-2" />
          <Swatch name="text-3"      varName="--fx-text-3" />
        </div>
      </Section>

      <Section
        title="Typography"
        desc="Inter for everything except literal IDs and code, which use JetBrains Mono. Six steps, sentence case throughout — no all-caps section labels."
      >
        <div className="fx-card">
          <div className="fx-type-row">
            <span className="fx-type-meta">xl / 28&nbsp;·&nbsp;600</span>
            <span className="fx-h1">Living Room</span>
          </div>
          <div className="fx-type-row">
            <span className="fx-type-meta">lg / 20&nbsp;·&nbsp;600</span>
            <span className="fx-h2">Add a new device</span>
          </div>
          <div className="fx-type-row">
            <span className="fx-type-meta">md / 16&nbsp;·&nbsp;500</span>
            <span className="fx-h3">Kitchen, Office, Bedroom</span>
          </div>
          <div className="fx-type-row">
            <span className="fx-type-meta">base / 14</span>
            <span className="fx-body">Default UI body text. Used for source names, device rows, button labels.</span>
          </div>
          <div className="fx-type-row">
            <span className="fx-type-meta">sm / 13</span>
            <span className="fx-small">Secondary text for hints, metadata, form descriptions.</span>
          </div>
          <div className="fx-type-row">
            <span className="fx-type-meta">xs / 11</span>
            <span className="fx-caption">Captions and tertiary labels.</span>
          </div>
          <div className="fx-type-row">
            <span className="fx-type-meta">mono / 12</span>
            <span className="fx-mono" style={{ fontSize: 12, color: 'var(--fx-text-2)' }}>fauxnos001 · 3600 · 192.168.1.42</span>
          </div>
        </div>
      </Section>

      <Section
        title="Surface elevation"
        desc="Three shadow + ring tokens. Cards lift gently; popovers and side panels float dramatically."
      >
        <div className="fx-sheet-grid cols-3">
          <div className="fx-card" style={{ boxShadow: 'var(--fx-shadow-1)' }}>
            <div className="fx-h3">Card</div>
            <div className="fx-small">shadow-1 — resting cards</div>
          </div>
          <div className="fx-card" style={{ boxShadow: 'var(--fx-shadow-2)' }}>
            <div className="fx-h3">Popover</div>
            <div className="fx-small">shadow-2 — devices popover, dropdowns</div>
          </div>
          <div className="fx-card" style={{ boxShadow: 'var(--fx-shadow-3)' }}>
            <div className="fx-h3">Side panel</div>
            <div className="fx-small">shadow-3 — floating drawers</div>
          </div>
        </div>
      </Section>
    </>
  )
}

/* ── Buttons ──────────────────────────────────────────────────────────────── */

function Buttons() {
  return (
    <Section
      title="Buttons"
      desc="One height (36px) for default actions, plus sm/lg variants. Primary uses amber + dark text — high contrast in both themes."
    >
      <div className="fx-card fx-stack">
        <div className="fx-row">
          <button className="fx-btn primary">Save changes</button>
          <button className="fx-btn">Cancel</button>
          <button className="fx-btn ghost">Skip</button>
          <button className="fx-btn danger">Remove device</button>
          <button className="fx-btn primary" disabled>Saving…</button>
        </div>
        <div className="fx-row">
          <button className="fx-btn sm">Refresh</button>
          <button className="fx-btn primary sm">Apply</button>
          <button className="fx-btn lg primary">Add device</button>
        </div>
        <div className="fx-row">
          <button className="fx-btn primary"><Check size={14} /> Saved</button>
          <button className="fx-btn"><RefreshCw size={14} /> Refresh</button>
          <button className="fx-btn ghost"><Plus size={14} /> Add custom source</button>
        </div>
      </div>
    </Section>
  )
}

/* ── Icon buttons + dots ──────────────────────────────────────────────────── */

function IconsAndDots() {
  return (
    <Section
      title="Icon buttons & status dots"
      desc="All icons are Lucide at consistent stroke. Dot variants cover connection, source state, and the pulse used for 'live' indicators."
    >
      <div className="fx-card fx-stack">
        <div className="fx-row">
          <button className="fx-icon-btn" aria-label="Settings"><Settings2 size={16} /></button>
          <button className="fx-icon-btn active" aria-label="Settings"><Settings2 size={16} /></button>
          <button className="fx-icon-btn" aria-label="Refresh"><RefreshCw size={16} /></button>
          <button className="fx-icon-btn" aria-label="Copy"><Copy size={16} /></button>
          <button className="fx-icon-btn danger" aria-label="Remove"><X size={18} /></button>
          <button className="fx-icon-btn danger" aria-label="Delete"><Trash2 size={16} /></button>
          <button className="fx-icon-btn" disabled aria-label="Disabled"><Plus size={16} /></button>
          <span className="fx-drag" title="Drag"><GripVertical size={16} /></span>
        </div>
        <div className="fx-row" style={{ paddingTop: 'var(--fx-2)' }}>
          <span className="fx-row" style={{ gap: 'var(--fx-1)' }}><span className="fx-dot" /> <span className="fx-caption">idle</span></span>
          <span className="fx-row" style={{ gap: 'var(--fx-1)' }}><span className="fx-dot ok" /> <span className="fx-caption">connected</span></span>
          <span className="fx-row" style={{ gap: 'var(--fx-1)' }}><span className="fx-dot warn" /> <span className="fx-caption">stalled</span></span>
          <span className="fx-row" style={{ gap: 'var(--fx-1)' }}><span className="fx-dot err" /> <span className="fx-caption">failed</span></span>
          <span className="fx-row" style={{ gap: 'var(--fx-1)' }}><span className="fx-dot accent" /> <span className="fx-caption">active</span></span>
          <span className="fx-row" style={{ gap: 'var(--fx-1)' }}><span className="fx-dot accent pulse" style={{ color: 'var(--fx-accent)' }} /> <span className="fx-caption">live</span></span>
        </div>
      </div>
    </Section>
  )
}

/* ── Badges ───────────────────────────────────────────────────────────────── */

function Badges() {
  return (
    <Section
      title="Badges"
      desc="Five tones. Each pairs a soft fill with a saturated text color so they stay legible without borders."
    >
      <div className="fx-card fx-row">
        <span className="fx-badge ok"><span className="fx-dot ok" /> connected</span>
        <span className="fx-badge"><span className="fx-dot" /> offline</span>
        <span className="fx-badge accent">active source</span>
        <span className="fx-badge accent">internal · snapcast</span>
        <span className="fx-badge">external</span>
        <span className="fx-badge warn">reboot pending</span>
        <span className="fx-badge err">install failed</span>
      </div>
    </Section>
  )
}

/* ── Forms ────────────────────────────────────────────────────────────────── */

function Forms() {
  const [enabled, setEnabled] = useState(true)
  return (
    <Section
      title="Forms"
      desc="Inputs sit on surface-2 so they read as 'wells'; focus inflates to surface-1 + amber ring. The select chevron is drawn in CSS — no native arrow."
    >
      <div className="fx-card fx-stack">
        <div className="fx-sheet-grid cols-2">
          <div>
            <label className="fx-label">Display name</label>
            <input className="fx-input" defaultValue="Kitchen" />
          </div>
          <div>
            <label className="fx-label">API URL</label>
            <input className="fx-input" placeholder="https://api.particle.io/v1/…" />
          </div>
          <div>
            <label className="fx-label">DAC overlay</label>
            <select className="fx-select" defaultValue="hifiberry-dac">
              <option value="hifiberry-dac">HiFiBerry DAC+ Light</option>
              <option value="hifiberry-dacplus">HiFiBerry DAC+ Standard / Pro</option>
              <option value="allo-boss-dac-pcm512x-audio">Allo Boss / INNO-MAKER</option>
            </select>
          </div>
          <div>
            <label className="fx-label">Encoding</label>
            <select className="fx-select" defaultValue="json">
              <option value="json">JSON</option>
              <option value="form">Form (x-www-form-urlencoded)</option>
            </select>
          </div>
        </div>
        <div>
          <label className="fx-label">Payload</label>
          <textarea className="fx-textarea" rows={3} defaultValue={'{ "source": "fauxnos" }'} />
          <div className="fx-hint">JSON or form data sent when this source is selected. Defaults to the source id.</div>
        </div>
        <label className="fx-checkbox-row">
          <input className="fx-checkbox" type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} />
          Call external API when this source is selected
        </label>
      </div>
    </Section>
  )
}

/* ── Volume slider ────────────────────────────────────────────────────────── */

function VolumeRow({ defaultValue = 48, variant = '', label = 'Kitchen' }) {
  const [val, setVal] = useState(defaultValue)
  const trackRef = useRef(null)
  const Icon = val === 0 ? VolumeX : val < 40 ? Volume1 : Volume2

  // Snap the thumb to the fill end. Track is 100% width, so the thumb's
  // left = pct.
  const pct = `${val}%`

  return (
    <div className="fx-row" style={{ width: '100%' }}>
      <span style={{ width: 110, fontSize: 'var(--fx-text-sm)' }}>{label}</span>
      <div className={`fx-volume ${variant}`} style={{ flex: 1 }}>
        <span className="fx-volume-icon"><Icon size={16} /></span>
        <div className="fx-volume-track" ref={trackRef}>
          <div className="fx-volume-fill" style={{ width: pct }} />
          <div className="fx-volume-thumb" style={{ left: pct }} />
          <input
            className="fx-volume-input"
            type="range"
            min={0}
            max={100}
            value={val}
            onChange={e => setVal(parseInt(e.target.value, 10))}
            aria-label={`${label} volume`}
          />
        </div>
        <span className="fx-volume-label fx-num">{val}%</span>
      </div>
    </div>
  )
}

function VolumeSliders() {
  return (
    <Section
      title="Volume slider"
      desc="Custom-built. The fill is a real rectangle so level is readable at a glance; the thumb expands on hover/drag. Tabular-numeral label so width doesn't reflow."
    >
      <div className="fx-card fx-stack">
        <VolumeRow defaultValue={48} label="Kitchen" />
        <VolumeRow defaultValue={72} label="Living Room" variant="accent" />
        <VolumeRow defaultValue={28} label="Bedroom" />
        <VolumeRow defaultValue={88} label="Whole house" variant="lg" />
      </div>
    </Section>
  )
}

/* ── Segmented control ────────────────────────────────────────────────────── */

function Segmented() {
  const [val, setVal] = useState('spotify')
  return (
    <Section
      title="Source selector"
      desc="Replaces the old segmented dropdown in group cards. Active source carries the amber-soft fill. Equal-width segments, ellipsis on overflow."
    >
      <div className="fx-card fx-stack">
        <div className="fx-segmented" role="radiogroup" aria-label="Source">
          {['spotify', 'airplay', 'analog'].map(s => (
            <button
              key={s}
              role="radio"
              aria-checked={val === s}
              className={`fx-segmented-btn${val === s ? ' active' : ''}`}
              onClick={() => setVal(s)}
            >
              {s === 'spotify' ? 'Spotify' : s === 'airplay' ? 'AirPlay' : 'Analog In'}
            </button>
          ))}
        </div>
        <div className="fx-segmented">
          <button className="fx-segmented-btn active">Spotify</button>
          <button className="fx-segmented-btn">AirPlay</button>
          <button className="fx-segmented-btn">Analog In</button>
          <button className="fx-segmented-btn">Vinyl</button>
          <button className="fx-segmented-btn">Aux In</button>
        </div>
      </div>
    </Section>
  )
}

/* ── Header preview ───────────────────────────────────────────────────────── */

function ComposedHeader() {
  return (
    <Section
      title="Floating header"
      desc="Backdrop-blurred bar with a leading pulsing amber dot before the wordmark. The status pill is a button — chevron, dot, device count."
    >
      <div className="fx-card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: 'var(--fx-3) var(--fx-5)',
          background: 'color-mix(in srgb, var(--fx-surface-1) 70%, transparent)',
          backdropFilter: 'blur(12px)',
          borderBottom: '1px solid var(--fx-line)',
        }}>
          <div className="fx-row" style={{ gap: 'var(--fx-2)' }}>
            <span className="fx-dot accent pulse" style={{ color: 'var(--fx-accent)' }} />
            <span style={{ fontSize: 'var(--fx-text-md)', fontWeight: 600, letterSpacing: '-0.01em' }}>fauxnos</span>
          </div>
          <button className="fx-btn ghost sm">
            <span className="fx-dot ok" />
            <span>3 devices</span>
            <ChevronDown size={14} />
          </button>
        </div>
        <div style={{ padding: 'var(--fx-5)', background: 'var(--fx-bg)' }}>
          <div className="fx-small">Sticky on scroll, 80% opacity backdrop, 12px blur. Wordmark dot pulses while the server is running.</div>
        </div>
      </div>
    </Section>
  )
}

/* ── Devices popover preview ──────────────────────────────────────────────── */

function DevicesPopoverPreview() {
  const devices = [
    { id: 'fauxnos000', name: 'Living Room',  connected: true },
    { id: 'fauxnos001', name: 'Kitchen',      connected: true },
    { id: 'fauxnos002', name: 'Office',       connected: true },
    { id: 'fauxnos003', name: 'Bedroom',      connected: false },
  ]
  return (
    <Section
      title="Devices popover"
      desc="Opens from the header status pill. Connected first, alphabetical within each group. Each row → opens that device's panel."
    >
      <div className="fx-row" style={{ alignItems: 'flex-start' }}>
        <div className="fx-popover" style={{ width: 320 }}>
          <div className="fx-caption" style={{ padding: 'var(--fx-2) var(--fx-3) var(--fx-1)' }}>Devices</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2, padding: '0 var(--fx-1) var(--fx-1)' }}>
            {devices.map(d => (
              <button
                key={d.id}
                className="fx-btn ghost"
                style={{
                  justifyContent: 'flex-start',
                  height: 'auto',
                  padding: 'var(--fx-2) var(--fx-2)',
                  gap: 'var(--fx-3)',
                  width: '100%',
                }}
              >
                <span className={`fx-dot ${d.connected ? 'ok' : ''}`} />
                <span style={{ flex: 1, textAlign: 'left', display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <span style={{ fontSize: 'var(--fx-text-sm)', color: 'var(--fx-text)' }}>{d.name}</span>
                  <span className="fx-mono" style={{ fontSize: 11, color: 'var(--fx-text-3)' }}>{d.id}</span>
                </span>
                <ChevronRight size={14} style={{ color: 'var(--fx-text-3)' }} />
              </button>
            ))}
          </div>
          <div style={{ padding: 'var(--fx-2)', borderTop: '1px solid var(--fx-line)', marginTop: 'var(--fx-2)' }}>
            <button className="fx-btn block"><Plus size={14} /> Add device</button>
          </div>
        </div>
      </div>
    </Section>
  )
}

/* ── Group cards ──────────────────────────────────────────────────────────── */

function GroupCardSingle({ name, source, vol }) {
  return (
    <div className="fx-demo-group">
      <span className="fx-drag" title="Drag to regroup"><GripVertical size={16} /></span>
      <div className="fx-card fx-card-hover">
        <div className="fx-row" style={{ justifyContent: 'space-between', marginBottom: 'var(--fx-3)' }}>
          <span className="fx-h3">{name}</span>
          <button className="fx-icon-btn sm" aria-label="Device settings"><Settings2 size={14} /></button>
        </div>
        <div className="fx-segmented" style={{ marginBottom: 'var(--fx-3)' }}>
          {['Spotify', 'AirPlay', 'Analog In'].map(s => (
            <button key={s} className={`fx-segmented-btn${source === s ? ' active' : ''}`}>{s}</button>
          ))}
        </div>
        <VolumeRow label="" defaultValue={vol} variant="accent" />
      </div>
    </div>
  )
}

function GroupCardMulti() {
  const members = [
    { id: 'fauxnos000', name: 'Living Room', isHome: true,  vol: 64, connected: true },
    { id: 'fauxnos001', name: 'Kitchen',     isHome: false, vol: 48, connected: true },
    { id: 'fauxnos002', name: 'Office',      isHome: false, vol: 30, connected: true },
  ]
  return (
    <div className="fx-demo-group">
      <span className="fx-drag" style={{ visibility: 'hidden' }}><GripVertical size={16} /></span>
      <div className="fx-card">
        <div className="fx-row" style={{ justifyContent: 'space-between', marginBottom: 'var(--fx-3)' }}>
          <span className="fx-h3">Living Room, Kitchen, Office</span>
          <button className="fx-icon-btn sm" aria-label="Device settings"><Settings2 size={14} /></button>
        </div>
        <div className="fx-segmented" style={{ marginBottom: 'var(--fx-3)' }}>
          <button className="fx-segmented-btn active">Spotify</button>
          <button className="fx-segmented-btn">AirPlay</button>
          <button className="fx-segmented-btn">Analog In</button>
        </div>
        <VolumeRow label="Group" defaultValue={64} variant="lg accent" />
        <hr className="fx-divider" />
        {members.map(m => (
          <div className="fx-demo-row" key={m.id}>
            <span>
              {m.isHome
                ? <span style={{ width: 16, display: 'inline-block' }} />
                : <span className="fx-drag" title="Drag out"><GripVertical size={14} /></span>}
            </span>
            <div className="fx-demo-rowname">
              <span className={`fx-dot ${m.connected ? 'ok' : ''}`} />
              <span>{m.name}</span>
            </div>
            <div style={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 'var(--fx-2)' }}>
              <VolumeRow label="" defaultValue={m.vol} />
              {!m.isHome && (
                <button className="fx-icon-btn sm danger" aria-label="Remove from group"><X size={16} /></button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function GroupCardPreviews() {
  return (
    <Section
      title="Group card"
      desc="One row in the Groups column. Single-device cards get a drag handle in the gutter; multi-device cards expand to show members with their own sliders. Drop-target state shown in the third card."
    >
      <div className="fx-stack">
        <GroupCardSingle name="Bedroom" source="Spotify" vol={48} />
        <GroupCardMulti />
        <div className="fx-demo-group">
          <span className="fx-drag"><GripVertical size={16} /></span>
          <div className="fx-card fx-drop">
            <div className="fx-row" style={{ justifyContent: 'space-between', marginBottom: 'var(--fx-3)' }}>
              <span className="fx-h3">Office</span>
              <button className="fx-icon-btn sm" aria-label="Device settings"><Settings2 size={14} /></button>
            </div>
            <div className="fx-small fx-mute">Drop here to join Office's group</div>
          </div>
        </div>
      </div>
    </Section>
  )
}

/* ── Source rows (inside device panel) ────────────────────────────────────── */

function SourceRow({ label, kind, expanded = false, onToggle, removable }) {
  return (
    <>
      <div className="fx-row" style={{
        justifyContent: 'space-between',
        padding: 'var(--fx-3) 0',
        borderBottom: '1px solid var(--fx-line)',
      }}>
        <div className="fx-stack" style={{ gap: 2 }}>
          <span style={{ fontSize: 'var(--fx-text-base)', fontWeight: 500 }}>{label}</span>
          <span className="fx-row" style={{ gap: 'var(--fx-2)' }}>
            {kind === 'internal' && <span className="fx-badge accent">internal · snapcast</span>}
            {kind === 'external' && <span className="fx-badge">external</span>}
          </span>
        </div>
        <div className="fx-row" style={{ gap: 'var(--fx-1)' }}>
          <button className={`fx-icon-btn sm${expanded ? ' active' : ''}`} onClick={onToggle} aria-label="Configure">
            <Settings2 size={14} />
          </button>
          {removable && (
            <button className="fx-icon-btn sm danger" aria-label="Remove"><X size={16} /></button>
          )}
        </div>
      </div>
      {expanded && (
        <div className="fx-stack" style={{
          padding: 'var(--fx-3) 0',
          gap: 'var(--fx-3)',
          borderBottom: '1px solid var(--fx-line)',
        }}>
          <div>
            <label className="fx-label">Calibration <span className="fx-mute">— max output 100%</span></label>
            <VolumeRow label="" defaultValue={92} variant="accent" />
            <div className="fx-hint">Tune so this source matches the others. Spotify often comes in hot; analog may be quiet.</div>
          </div>
          <label className="fx-checkbox-row">
            <input className="fx-checkbox" type="checkbox" defaultChecked />
            Call external API when selected
          </label>
          <div className="fx-sheet-grid cols-2">
            <div>
              <label className="fx-label">API URL</label>
              <input className="fx-input" defaultValue="https://api.particle.io/v1/devices/27…/setSource" />
            </div>
            <div>
              <label className="fx-label">Encoding</label>
              <select className="fx-select" defaultValue="form">
                <option value="json">JSON</option>
                <option value="form">Form</option>
              </select>
            </div>
          </div>
          <div>
            <label className="fx-label">Payload</label>
            <textarea className="fx-textarea" rows={2} defaultValue={'{ "arg": "1" }'} />
          </div>
          <div className="fx-row">
            <button className="fx-btn primary"><Check size={14} /> Save</button>
          </div>
        </div>
      )}
    </>
  )
}

function SourceRowPreviews() {
  const [expanded, setExpanded] = useState('spotify')
  return (
    <Section
      title="Source rows (device panel)"
      desc="No nested boxes. Rows separated by hairlines; expanded form drops below in the same column. Icon actions appear inline at row-end."
    >
      <div className="fx-card">
        <div className="fx-section-label">
          <span>Built-in sources</span>
          <button className="fx-icon-btn sm" aria-label="Add built-in"><Plus size={14} /></button>
        </div>
        <SourceRow
          label="Spotify"
          kind="internal"
          expanded={expanded === 'spotify'}
          onToggle={() => setExpanded(expanded === 'spotify' ? null : 'spotify')}
        />
        <SourceRow label="AirPlay"   kind="internal" />
        <SourceRow label="Analog In" kind="internal" removable />

        <div className="fx-section-label" style={{ marginTop: 'var(--fx-4)' }}>
          <span>Custom sources</span>
        </div>
        <SourceRow label="Vinyl"  kind="external" />
        <SourceRow label="Aux In" kind="external" />
      </div>
    </Section>
  )
}

/* ── Device panel preview ─────────────────────────────────────────────────── */

function DevicePanelPreview() {
  return (
    <Section
      title="Floating side panel"
      desc="Drawer becomes a floating card — 12px inset from the page edges, full shadow + 1px hairline. The dashed plate behind it represents the dimmed/blurred main view."
    >
      <div className="fx-sheet-panel-frame">
        <div className="fx-sheet-panel-mock">
          <div className="fx-row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
            <span className="fx-h2">Kitchen</span>
            <button className="fx-icon-btn" aria-label="Close"><X size={18} /></button>
          </div>
          <div className="fx-row" style={{ gap: 'var(--fx-3)', marginTop: 'var(--fx-1)' }}>
            <span className="fx-row" style={{ gap: 'var(--fx-1)' }}>
              <span className="fx-caption">ID</span>
              <span className="fx-mono" style={{ fontSize: 12, color: 'var(--fx-text-2)' }}>fauxnos001</span>
            </span>
            <span className="fx-badge ok"><span className="fx-dot ok" /> connected</span>
          </div>
          <hr className="fx-divider" />
          <div className="fx-section-label">
            <span>Built-in sources</span>
            <button className="fx-icon-btn sm" aria-label="Add"><Plus size={14} /></button>
          </div>
          <div className="fx-row" style={{ justifyContent: 'space-between', padding: 'var(--fx-2) 0' }}>
            <div>
              <div style={{ fontWeight: 500 }}>Spotify</div>
              <span className="fx-badge accent">internal · snapcast</span>
            </div>
            <button className="fx-icon-btn sm" aria-label="Configure"><Settings2 size={14} /></button>
          </div>
          <div className="fx-row" style={{ justifyContent: 'space-between', padding: 'var(--fx-2) 0' }}>
            <div>
              <div style={{ fontWeight: 500 }}>AirPlay</div>
              <span className="fx-badge accent">internal · snapcast</span>
            </div>
            <button className="fx-icon-btn sm" aria-label="Configure"><Settings2 size={14} /></button>
          </div>
        </div>
      </div>
    </Section>
  )
}

/* ── Timeline ─────────────────────────────────────────────────────────────── */

function TimelineStep({ state, label, note, tail }) {
  const isLast = state === '_last'
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '28px 1fr', gap: 'var(--fx-3)', minHeight: 40 }}>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <span className={`fx-timeline-dot ${isLast ? '' : state}`} style={{ marginTop: 4 }} />
        {!isLast && <span style={{ width: 2, flex: 1, background: 'var(--fx-line)', marginTop: 2 }} />}
      </div>
      <div style={{ paddingBottom: 'var(--fx-3)' }}>
        <div style={{
          fontSize: 'var(--fx-text-sm)',
          fontWeight: 500,
          color: state === 'skipped' ? 'var(--fx-text-3)' : 'var(--fx-text)',
        }}>{label}</div>
        {note && <div className="fx-caption" style={{ color: state === 'failed' ? 'var(--fx-err)' : 'var(--fx-warn)' }}>{note}</div>}
        {tail && <div className="fx-mono" style={{ fontSize: 11, color: 'var(--fx-text-3)', marginTop: 2 }}>{tail}</div>}
      </div>
    </div>
  )
}

function TimelinePreview() {
  return (
    <Section
      title="Install timeline"
      desc="Single column, hairline-connected dots. The active step gets a soft amber halo; failed steps surface their error inline. Used in the Add Device wizard."
    >
      <div className="fx-card">
        <TimelineStep state="done"    label="Reach device over SSH" tail="fauxnos001.local → 192.168.1.42" />
        <TimelineStep state="done"    label="Copy installer scripts" tail="84 files, 312 KB" />
        <TimelineStep state="done"    label="Detect DAC hardware"    tail="hifiberry-dac · pcm5102" />
        <TimelineStep state="active"  label="Install snapclient + go-librespot" tail="apt install snapclient ⟶" />
        <TimelineStep state="stalled" label="Register with server"   note="Waiting for client to phone home (60s)" />
        <TimelineStep state="skipped" label="Assign to home group" />
        <TimelineStep state="_last"   label="Verify audio output" />
      </div>
    </Section>
  )
}

/* ── Empty states ─────────────────────────────────────────────────────────── */

function EmptyStates() {
  return (
    <Section
      title="Empty & loading"
      desc="Calm, never apologetic. The amber halo on the spinner ties loading to the brand color."
    >
      <div className="fx-sheet-grid cols-2">
        <div className="fx-card" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 'var(--fx-2)', padding: 'var(--fx-6) var(--fx-4)', textAlign: 'center' }}>
          <Speaker size={28} style={{ color: 'var(--fx-text-3)' }} />
          <div className="fx-h3">No devices yet</div>
          <div className="fx-small fx-mute" style={{ maxWidth: 280 }}>
            Add your first Fauxnos device to start streaming. You'll need a Raspberry Pi and a DAC HAT.
          </div>
          <button className="fx-btn primary" style={{ marginTop: 'var(--fx-2)' }}><Plus size={14} /> Add device</button>
        </div>
        <div className="fx-card" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 'var(--fx-2)', padding: 'var(--fx-6) var(--fx-4)', textAlign: 'center' }}>
          <span className="fx-spinner lg" />
          <div className="fx-h3" style={{ marginTop: 'var(--fx-1)' }}>Loading sources</div>
          <div className="fx-small fx-mute">Fetching the current source list for this device…</div>
        </div>
      </div>
    </Section>
  )
}
