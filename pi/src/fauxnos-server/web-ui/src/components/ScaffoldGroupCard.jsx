import {
  IconPlayerPlayFilled,
  IconPlayerTrackPrevFilled,
  IconPlayerTrackNextFilled,
  IconBrandSpotifyFilled,
  IconChevronDownFilled,
} from '@tabler/icons-react'
import { useTuning } from '../hooks/useTuning'
import { useTheme } from '../hooks/useTheme'
import { buildArtTokens } from '../lib/artTokens'
import { SHOW_COLOR_TUNING } from '../lib/devFlags'

/* ─────────────────────────────────────────────────────────────────────────────
 * ScaffoldGroupCard — TEMPORARY.
 *
 * Faux GroupCard rendered inline in the Groups grid for color tuning.
 * Uses the live `.fx-group-card-v2.v3` markup and classes so all the
 * `--art-*` cascade rules apply identically to a real card. The simulated
 * album-art color (H/C/L) is read from useTuning, so the TuningPanel
 * sliders drive this card live.
 *
 * No drag/drop, no state changes, no MQTT — placeholder text only.
 * Deletes alongside the rest of the tuning kit once colors lock.
 * ────────────────────────────────────────────────────────────────────────── */
export default function ScaffoldGroupCard() {
  if (!SHOW_COLOR_TUNING) return null
  return <ScaffoldGroupCardInner />
}

function ScaffoldGroupCardInner() {
  const t = useTuning()
  const { effective } = useTheme()
  const isDark = effective === 'dark'
  const src = { h: t.scaffold_h, c: t.scaffold_c, l: t.scaffold_l }
  const artStyle = buildArtTokens(src, isDark, t)
  const titleText = t.scaffold_art_title || 'Placeholder Track Title'
  const subText   = t.scaffold_art_subtitle || 'Placeholder Artist · Placeholder Album'

  return (
    <div className="fx-group-row-v2-wrap" data-group-card-id="__scaffold__">
      <div
        className="fx-group-card-v2 fx-card-hover v3"
        data-has-media="true"
        style={artStyle}
      >
        <div className="fx-media-reveal">
          <div className="fx-media-reveal-inner">
            <div className="fx-group-media-card">
              <div className="fx-group-media-art">
                {t.scaffold_art_url
                  ? <img src={t.scaffold_art_url} alt="" loading="lazy" crossOrigin="anonymous" />
                  : <div
                      className="fx-scaffold-art-swatch"
                      style={{ background: `oklch(${src.l} ${src.c} ${src.h})` }}
                      aria-hidden
                    />}
              </div>
              <div className="fx-group-media-body">
                <div className="fx-group-media-text">
                  <span className="fx-title-track" title={titleText}>{titleText}</span>
                  <span className="fx-meta-track" title={subText}>{subText}</span>
                </div>
                <div className="fx-group-progress">
                  <div className="fx-group-progress-bar">
                    <span className="fx-time-track">1:24</span>
                    <div className="fx-group-progress-track">
                      <div className="fx-group-progress-fill" style={{ width: '42%' }} />
                      <div className="fx-group-progress-thumb" style={{ left: '42%', opacity: 1 }} />
                    </div>
                    <span className="fx-time-track">3:18</span>
                  </div>
                  <div className="fx-group-progress-actions">
                    <button type="button" className="fx-icon-btn" aria-label="Previous" tabIndex={-1}>
                      <IconPlayerTrackPrevFilled size={16} stroke={0} />
                    </button>
                    <button type="button" className="fx-icon-btn" aria-label="Play" tabIndex={-1}>
                      <IconPlayerPlayFilled size={18} stroke={0} />
                    </button>
                    <button type="button" className="fx-icon-btn" aria-label="Next" tabIndex={-1}>
                      <IconPlayerTrackNextFilled size={16} stroke={0} />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
        <button
          type="button"
          className="fx-source-trigger anchor"
          aria-haspopup="menu"
          aria-label="Scaffold source"
          tabIndex={-1}
        >
          <IconBrandSpotifyFilled size={24} aria-hidden />
          <IconChevronDownFilled size={24} aria-hidden />
        </button>
        <div className="fx-group-rows">
          <div className="fx-group-row-v2">
            <div className="fx-group-row-name">
              <span className="fx-name-device fx-group-row-name-label">Scaffold</span>
            </div>
            <div className="fx-group-row-volume">
              <span className="fx-group-row-volume-icon" aria-hidden />
              <div className="fx-scaffold-volume-track">
                <div className="fx-scaffold-volume-fill" style={{ width: '60%' }} />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
