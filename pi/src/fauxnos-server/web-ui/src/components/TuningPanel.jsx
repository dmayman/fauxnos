import { useState } from 'react'
import { IconChevronDown, IconCopy, IconRefresh } from '@tabler/icons-react'
import { useTuning, setTuning, resetTuning } from '../hooks/useTuning'

/* ─────────────────────────────────────────────────────────────────────────────
 * TuningPanel — TEMPORARY.
 *
 * Floating bottom-right panel exposing sliders for every OKLCH clamp the
 * album-art accent system uses. Live updates propagate to all GroupCards
 * via useTuning(). Persists to localStorage so reloads keep your tweaks.
 *
 * Once we lock in values, delete this file + useTuning.js and bake the
 * constants into `buildArtTokens` in GroupCard.jsx.
 * ────────────────────────────────────────────────────────────────────────── */

function Slider({ label, value, min, max, step, onChange, hint }) {
  return (
    <label className="fx-tune-row">
      <span className="fx-tune-label">{label}</span>
      <input
        type="range"
        min={min} max={max} step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
      />
      <input
        type="number"
        className="fx-tune-num"
        min={min} max={max} step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
      />
      {hint && <span className="fx-tune-hint">{hint}</span>}
    </label>
  )
}

function Section({ title, children }) {
  return (
    <div className="fx-tune-section">
      <div className="fx-tune-section-title">{title}</div>
      {children}
    </div>
  )
}

export default function TuningPanel() {
  const t = useTuning()
  const [open, setOpen] = useState(false)
  const [revealed, setRevealed] = useState(false)
  const json = JSON.stringify(t, null, 2)

  return (
    <div className={`fx-tune-panel${open ? ' open' : ''}`}>
      <button
        type="button"
        className="fx-tune-toggle"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
      >
        <span>Color tuning</span>
        <IconChevronDown size={16} style={{ transform: open ? 'rotate(180deg)' : 'none' }} />
      </button>
      {open && (
        <div className="fx-tune-body">
          <Section title="Card tint — dark mode">
            <Slider label="L"        value={t.cardTintL_dark}    min={0.05} max={0.40} step={0.005} onChange={v => setTuning({ cardTintL_dark: v })} hint="lightness of outer card bg" />
            <Slider label="C min"    value={t.cardTintCmin_dark} min={0}    max={0.20} step={0.005} onChange={v => setTuning({ cardTintCmin_dark: v })} />
            <Slider label="C max"    value={t.cardTintCmax_dark} min={0}    max={0.20} step={0.005} onChange={v => setTuning({ cardTintCmax_dark: v })} hint="cap on saturation" />
          </Section>

          <Section title="Card tint — light mode">
            <Slider label="L"        value={t.cardTintL_light}    min={0.80} max={1.00} step={0.005} onChange={v => setTuning({ cardTintL_light: v })} />
            <Slider label="C min"    value={t.cardTintCmin_light} min={0}    max={0.15} step={0.005} onChange={v => setTuning({ cardTintCmin_light: v })} />
            <Slider label="C max"    value={t.cardTintCmax_light} min={0}    max={0.15} step={0.005} onChange={v => setTuning({ cardTintCmax_light: v })} />
          </Section>

          <Section title="Accent — dark mode">
            <Slider label="L min"    value={t.accentLmin_dark}  min={0.40} max={0.95} step={0.01} onChange={v => setTuning({ accentLmin_dark: v })} hint="floor lightness of accent" />
            <Slider label="L max"    value={t.accentLmax_dark}  min={0.40} max={0.95} step={0.01} onChange={v => setTuning({ accentLmax_dark: v })} />
          </Section>

          <Section title="Accent — light mode">
            <Slider label="L min"    value={t.accentLmin_light} min={0.20} max={0.70} step={0.01} onChange={v => setTuning({ accentLmin_light: v })} />
            <Slider label="L max"    value={t.accentLmax_light} min={0.20} max={0.70} step={0.01} onChange={v => setTuning({ accentLmax_light: v })} />
          </Section>

          <Section title="Accent chroma (both modes)">
            <Slider label="C min"    value={t.accentCmin}       min={0}    max={0.30} step={0.005} onChange={v => setTuning({ accentCmin: v })} />
            <Slider label="C max"    value={t.accentCmax}       min={0}    max={0.30} step={0.005} onChange={v => setTuning({ accentCmax: v })} />
          </Section>

          <Section title="Slider / progress track alpha">
            <Slider label="Dark"     value={t.trackAlpha_dark}  min={0}    max={0.40} step={0.005} onChange={v => setTuning({ trackAlpha_dark: v })} />
            <Slider label="Light"    value={t.trackAlpha_light} min={0}    max={0.40} step={0.005} onChange={v => setTuning({ trackAlpha_light: v })} />
          </Section>

          <div className="fx-tune-actions">
            <button type="button" className="fx-btn sm" onClick={() => setRevealed(r => !r)}>
              <IconCopy size={14} /> {revealed ? 'Hide JSON' : 'Reveal JSON'}
            </button>
            <button type="button" className="fx-btn sm ghost" onClick={() => resetTuning()} title="Reset to defaults">
              <IconRefresh size={14} /> Reset
            </button>
          </div>
          {revealed && (
            <textarea
              className="fx-tune-json"
              value={json}
              readOnly
              spellCheck={false}
              onFocus={(e) => e.target.select()}
              rows={Math.min(json.split('\n').length, 18)}
            />
          )}
        </div>
      )}
    </div>
  )
}
