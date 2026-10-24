import { useCallback, useMemo, useState } from 'react'
import { IconMusic } from '@tabler/icons-react'
import { artUrl } from '../hooks/useLibrary'

/* Pieces shared by the Library panel and a room's Browse popover. */

export const UNKNOWN_ARTIST = 'Unknown artist'
export const FILTERS = [
  { id: 'songs', label: 'Songs' },
  { id: 'artists', label: 'Artists' },
  { id: 'albums', label: 'Albums' },
  { id: 'playlists', label: 'Playlists' },
]
export const songsLabel = (n) => `${n} song${n === 1 ? '' : 's'}`

export function Art({ track, size = 40, Fallback = IconMusic }) {
  const url = artUrl(track)
  return (
    <span className="fx-lib-art" style={{ width: size, height: size }}>
      {url ? <img src={url} alt="" loading="lazy" draggable={false} /> : <Fallback size={size * 0.45} aria-hidden />}
    </span>
  )
}

export function FilterPills({ value, onChange, className = '' }) {
  return (
    <div className={`fx-lib-filters ${className}`} role="tablist" aria-label="Browse by">
      {FILTERS.map(f => (
        <button
          key={f.id}
          type="button"
          role="tab"
          aria-selected={value === f.id}
          className={`fx-lib-pill${value === f.id ? ' active' : ''}`}
          onClick={() => onChange(f.id)}
        >
          {f.label}
        </button>
      ))}
    </div>
  )
}

function groupBy(tracks, keyOf) {
  const map = new Map()
  for (const t of tracks) {
    const k = keyOf(t)
    if (!map.has(k)) map.set(k, [])
    map.get(k).push(t)
  }
  return new Map([...map].sort((a, b) => a[0].localeCompare(b[0])))
}

/* Artists and albums (Map of key → tracks), and the tracks a drilled-in page
   shows. A page is { kind: 'artist'|'album'|'playlist', key }. */
export function useCollections(lib) {
  const artists = useMemo(() => groupBy(lib.tracks, t => t.artist || UNKNOWN_ARTIST), [lib.tracks])
  const albums = useMemo(
    () => groupBy(lib.tracks.filter(t => t.album), t => `${t.album}\u0000${t.artist || ''}`),
    [lib.tracks],
  )
  const pageOf = useCallback((page) => {
    if (page.kind === 'artist') return { title: page.key, tracks: artists.get(page.key) || [] }
    if (page.kind === 'album') {
      const tracks = albums.get(page.key) || []
      return { title: tracks[0]?.album || 'Album', tracks }
    }
    const playlist = lib.playlists.find(p => p.id === page.key)
    return {
      title: playlist?.name || 'Playlist',
      playlist,
      tracks: (playlist?.track_ids || []).map(id => lib.byId.get(id)).filter(Boolean),
    }
  }, [artists, albums, lib.playlists, lib.byId])
  return { artists, albums, pageOf }
}

/* A stack of pages (the filter list, then artist → songs, …). Opening a page
   slides it in from the right; going back slides the previous one in from
   the left. */
export function usePageStack() {
  const [stack, setStack] = useState([])
  const [dir, setDir] = useState('none')
  const push = useCallback((page) => { setDir('forward'); setStack(s => [...s, page]) }, [])
  const pop = useCallback(() => { setDir('back'); setStack(s => s.slice(0, -1)) }, [])
  const reset = useCallback(() => { setDir('none'); setStack([]) }, [])
  return { page: stack[stack.length - 1] || null, depth: stack.length, dir, push, pop, reset }
}

export function PushPage({ pageKey, dir, className = '', children }) {
  return (
    <div key={pageKey} className={`fx-push-page ${dir} ${className}`}>
      {children}
    </div>
  )
}
