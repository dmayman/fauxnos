import { useEffect, useRef, useState } from 'react'
import {
  IconChevronDownFilled,
  IconCopyFilled,
  IconRefresh,
  IconX,
} from '@tabler/icons-react'
import { HexColorPicker, RgbaStringColorPicker } from 'react-colorful'
import { useTuning, setTuning, resetTuning } from '../hooks/useTuning'
import { useTokens, setToken, resetTokens, getTokenValue, TOKEN_GROUPS, TOKEN_DEFAULTS } from '../hooks/useTokens'
import { useTheme } from '../hooks/useTheme'
import useAlbumArtColor from '../hooks/useAlbumArtColor'
import { ALBUM_SAMPLES } from '../lib/albumSamples'

/* ─────────────────────────────────────────────────────────────────────────────
 * TuningPanel — TEMPORARY.
 *
 * Floating bottom-right panel with two tabs:
 *   • "Art"    — OKLCH clamp sliders + a simulated source-color H/C/L
 *                row that drives the inline ScaffoldGroupCard rendered
 *                at the top of GroupsTab. Edit there, watch the inline
 *                card update.
 *   • "Tokens" — every `--fx-*` color token, editable per mode (dark
 *                or light, defaulting to the active theme). Edits inject
 *                into a <style id="fx-token-overrides"> tag at runtime.
 *
 * A single "Reveal JSON" button at the bottom dumps both tabs' values
 * combined so they can be pasted to the user / baked into source.
 *
 * Once values lock, delete this file, useTuning.js, useTokens.js, and
 * ScaffoldGroupCard.jsx; bake the constants into index.css and
 * buildArtTokens.
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

/* ─────────────────────────────────────────────────────────────────────────────
 * TokenRow — single token editor: swatch + text input + reset.
 *
 * The swatch toggles a color picker popover. Picker variant depends on the
 * value's CSS form:
 *   - rgba(...)/rgb(...)  → RgbaStringColorPicker (alpha-aware)
 *   - hex                 → HexColorPicker
 *   - anything else (oklch, currentColor, ...) → no picker, text input only.
 * Off-the-shelf react-colorful — dev-only tooling, no need to roll our own.
 * ────────────────────────────────────────────────────────────────────────── */
function TokenRow({ name, mode, overrides }) {
  const overridden = name in (overrides || {})
  const value = getTokenValue(mode, name)
  const [pickerOpen, setPickerOpen] = useState(false)
  const wrapRef = useRef(null)

  // Close on outside click. Listener is only attached while the picker
  // is mounted, so it doesn't burn cycles for closed rows.
  useEffect(() => {
    if (!pickerOpen) return undefined
    const onDown = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setPickerOpen(false)
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [pickerOpen])

  const isShadow = name.startsWith('--fx-shadow-')
  const isRgba = !isShadow && /^rgba?\(/i.test(value)
  const isHex  = !isShadow && /^#([0-9a-f]{3,8})$/i.test(value)
  const canPick = isRgba || isHex

  // Shadow swatch: a small light tile floating above a neutral backdrop,
  // with the token's box-shadow applied — so the user sees what the
  // shadow actually looks like, not a meaningless color square.
  const swatchStyle = isShadow
    ? { background: 'var(--fx-surface-1)', boxShadow: value, borderColor: 'var(--fx-line)' }
    : { background: value }

  return (
    <div className={`fx-token-row${overridden ? ' is-overridden' : ''}${isShadow ? ' is-shadow' : ''}`} ref={wrapRef}>
      <button
        type="button"
        className="fx-token-swatch"
        style={swatchStyle}
        onClick={() => canPick && setPickerOpen(o => !o)}
        title={canPick ? 'Open color picker' : (isShadow ? 'Edit shadow CSS in the text field' : 'No picker for this value type')}
        aria-label={`Edit ${name}`}
        disabled={!canPick}
      />
      <code className="fx-token-name">{name}</code>
      <input
        type="text"
        className="fx-token-input"
        value={value}
        spellCheck={false}
        onChange={(e) => setToken(mode, name, e.target.value)}
      />
      <button
        type="button"
        className="fx-token-reset"
        onClick={() => setToken(mode, name, null)}
        title="Reset to default"
        aria-label={`Reset ${name}`}
        disabled={!overridden}
      >
        <IconRefresh size={12} />
      </button>
      {pickerOpen && canPick && (
        <div className="fx-token-picker-pop" onMouseDown={(e) => e.stopPropagation()}>
          {isRgba ? (
            <RgbaStringColorPicker color={value} onChange={(v) => setToken(mode, name, v)} />
          ) : (
            <HexColorPicker color={value} onChange={(v) => setToken(mode, name, v)} />
          )}
        </div>
      )}
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────────
 * AlbumPicker — grid of 100 sample album covers. Clicking sets the
 * scaffold's art URL and metadata. The harvester (in the parent) feeds
 * the extracted OKLCH back into scaffold_h/c/l so the sliders track
 * the live image.
 * ────────────────────────────────────────────────────────────────────────── */
function AlbumPicker({ activeUrl }) {
  return (
    <div className="fx-album-grid">
      {ALBUM_SAMPLES.map(a => (
        <button
          key={a.id}
          type="button"
          className={`fx-album-thumb${activeUrl === a.art ? ' is-active' : ''}`}
          onClick={() => setTuning({
            scaffold_art_url: a.art,
            scaffold_art_title: a.name,
            scaffold_art_subtitle: a.artist,
          })}
          title={`${a.name} — ${a.artist}`}
        >
          <img src={a.thumb} alt="" loading="lazy" crossOrigin="anonymous" />
        </button>
      ))}
    </div>
  )
}

export default function TuningPanel() {
  const t = useTuning()
  const tokens = useTokens()
  const { effective } = useTheme()
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState('art')          // 'art' | 'tokens'
  const [tokensMode, setTokensMode] = useState(effective) // 'dark' | 'light'
  const [revealed, setRevealed] = useState(false)

  // Harvest OKLCH from the currently-picked album cover (if any) and
  // write it back into the scaffold H/C/L so the sliders reflect the
  // live extraction. Effect only fires when the extracted result
  // actually changes (per-URL cache in useAlbumArtColor).
  const harvested = useAlbumArtColor(t.scaffold_art_url)
  useEffect(() => {
    if (!harvested) return
    setTuning({
      scaffold_h: Math.round(harvested.h * 100) / 100,
      scaffold_c: Math.round(harvested.c * 1000) / 1000,
      scaffold_l: Math.round(harvested.l * 1000) / 1000,
    })
  }, [harvested?.h, harvested?.c, harvested?.l])

  const clearAlbum = () => setTuning({
    scaffold_art_url: null,
    scaffold_art_title: null,
    scaffold_art_subtitle: null,
  })

  const combinedJson = JSON.stringify({
    tuning: t,
    tokens: {
      dark:  { ...TOKEN_DEFAULTS.dark,  ...tokens.dark },
      light: { ...TOKEN_DEFAULTS.light, ...tokens.light },
    },
    tokenOverrides: tokens, // also include just the deltas, for easy diff
  }, null, 2)

  return (
    <div className={`fx-tune-panel${open ? ' open' : ''}`}>
      <button
        type="button"
        className="fx-tune-toggle"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
      >
        <span>Color tuning</span>
        <IconChevronDownFilled size={16} style={{ transform: open ? 'rotate(180deg)' : 'none' }} />
      </button>
      {open && (
        <>
          <div className="fx-tune-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'art'}
              className={`fx-tune-tab${tab === 'art' ? ' is-active' : ''}`}
              onClick={() => setTab('art')}
            >Art</button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'tokens'}
              className={`fx-tune-tab${tab === 'tokens' ? ' is-active' : ''}`}
              onClick={() => setTab('tokens')}
            >Tokens</button>
          </div>

          <div className="fx-tune-body">
            {tab === 'art' && (
              <>
                <Section title={
                  <span className="fx-album-section-head">
                    Album sampler
                    {t.scaffold_art_url && (
                      <button
                        type="button"
                        className="fx-album-clear"
                        onClick={clearAlbum}
                        title="Clear album — back to manual sliders"
                      >
                        <IconX size={11} /> clear
                      </button>
                    )}
                  </span>
                }>
                  <AlbumPicker activeUrl={t.scaffold_art_url} />
                </Section>

                <Section title="Scaffold source color (drives inline card)">
                  <Slider label="H" value={t.scaffold_h} min={0}    max={360}  step={1}     onChange={v => setTuning({ scaffold_h: v })} hint="hue 0-360°" />
                  <Slider label="C" value={t.scaffold_c} min={0}    max={0.35} step={0.005} onChange={v => setTuning({ scaffold_c: v })} hint="chroma raw" />
                  <Slider label="L" value={t.scaffold_l} min={0.05} max={0.95} step={0.01}  onChange={v => setTuning({ scaffold_l: v })} hint="lightness raw" /></Section>

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
              </>
            )}

            {tab === 'tokens' && (
              <>
                <div className="fx-tune-mode-toggle" role="tablist" aria-label="Token mode">
                  <button
                    type="button"
                    className={`fx-tune-tab sub${tokensMode === 'dark' ? ' is-active' : ''}`}
                    onClick={() => setTokensMode('dark')}
                    role="tab"
                    aria-selected={tokensMode === 'dark'}
                  >Dark</button>
                  <button
                    type="button"
                    className={`fx-tune-tab sub${tokensMode === 'light' ? ' is-active' : ''}`}
                    onClick={() => setTokensMode('light')}
                    role="tab"
                    aria-selected={tokensMode === 'light'}
                  >Light</button>
                  {tokensMode !== effective && (
                    <span className="fx-tune-hint" style={{ marginLeft: 'auto', alignSelf: 'center' }}>
                      Switch theme to preview live
                    </span>
                  )}
                </div>

                {TOKEN_GROUPS.map(g => (
                  <Section key={g.title} title={g.title}>
                    {g.names.map(n => (
                      <TokenRow
                        key={n}
                        name={n}
                        mode={tokensMode}
                        overrides={tokens[tokensMode]}
                      />
                    ))}
                  </Section>
                ))}
              </>
            )}
          </div>

          <div className="fx-tune-actions">
            <button type="button" className="fx-btn sm" onClick={() => setRevealed(r => !r)}>
              <IconCopyFilled size={14} /> {revealed ? 'Hide JSON' : 'Reveal JSON'}
            </button>
            <button
              type="button"
              className="fx-btn sm ghost"
              onClick={() => { resetTuning(); resetTokens() }}
              title="Reset both tabs"
            >
              <IconRefresh size={14} /> Reset all
            </button>
          </div>
          {revealed && (
            <textarea
              className="fx-tune-json"
              value={combinedJson}
              readOnly
              spellCheck={false}
              onFocus={(e) => e.target.select()}
              rows={Math.min(combinedJson.split('\n').length, 24)}
            />
          )}
        </>
      )}
    </div>
  )
}
