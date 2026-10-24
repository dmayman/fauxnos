import { IconArrowLeft, IconPlaylist, IconPlayerPlayFilled, IconChevronRight } from '@tabler/icons-react'
import { useLibrary } from '../hooks/useLibrary'
import {
  Art, FilterPills, songsLabel, UNKNOWN_ARTIST, useCollections, usePageStack, PushPage,
} from './LibraryBits'
import { useState } from 'react'

/* ─────────────────────────────────────────────────────────────────────────────
 * LibraryBrowser — a room's Browse popover: filter pills, then artist /
 * album / playlist pages that push in. Tapping a song plays it (with the
 * rest of that list queued after it); a page's Play all plays the whole list.
 * ────────────────────────────────────────────────────────────────────────── */
export default function LibraryBrowser({ currentTrackId, onPlay }) {
  const lib = useLibrary()
  const [filter, setFilter] = useState('songs')
  const stack = usePageStack()
  const { artists, albums, pageOf } = useCollections(lib)
  const page = stack.page ? pageOf(stack.page) : null

  const songList = (tracks) => tracks.map((t, i) => (
    <button
      key={t.id}
      type="button"
      className={`fx-library-browse-row${t.id === currentTrackId ? ' active' : ''}`}
      onClick={() => onPlay(tracks.slice(i).map(x => x.id))}
    >
      <Art track={t} size={32} />
      <span className="fx-library-browse-text">
        <span className="fx-library-browse-title">{t.title}</span>
        <span className="fx-library-browse-sub">{t.artist || UNKNOWN_ARTIST}</span>
      </span>
    </button>
  ))

  const collection = (key, title, sub, tracks, pageKey, Fallback) => (
    <button key={key} type="button" className="fx-library-browse-row" onClick={() => stack.push(pageKey)}>
      <Art track={tracks.find(t => t.art)} size={32} Fallback={Fallback} />
      <span className="fx-library-browse-text">
        <span className="fx-library-browse-title">{title}</span>
        <span className="fx-library-browse-sub">{sub}</span>
      </span>
      <IconChevronRight size={16} className="fx-library-browse-chevron" aria-hidden />
    </button>
  )

  let body
  if (page) {
    body = (
      <>
        <div className="fx-library-browse-head">
          <button type="button" className="fx-icon-btn sm" aria-label="Back" onClick={stack.pop}>
            <IconArrowLeft size={16} />
          </button>
          <span className="fx-library-browse-page-title">{page.title}</span>
          {page.tracks.length > 0 && (
            <button type="button" className="fx-icon-btn sm" aria-label="Play all" title="Play all"
              onClick={() => onPlay(page.tracks.map(t => t.id))}>
              <IconPlayerPlayFilled size={14} />
            </button>
          )}
        </div>
        {songList(page.tracks)}
        {page.tracks.length === 0 && <div className="fx-lib-menu-note">No songs here yet.</div>}
      </>
    )
  } else if (filter === 'songs') {
    body = songList(lib.tracks)
  } else if (filter === 'artists') {
    body = [...artists].map(([name, tracks]) =>
      collection(name, name, songsLabel(tracks.length), tracks, { kind: 'artist', key: name }))
  } else if (filter === 'albums') {
    body = [...albums].map(([key, tracks]) =>
      collection(key, tracks[0].album, tracks[0].artist || songsLabel(tracks.length), tracks, { kind: 'album', key }))
  } else {
    body = lib.playlists.map(p => {
      const tracks = p.track_ids.map(id => lib.byId.get(id)).filter(Boolean)
      return collection(p.id, p.name, songsLabel(tracks.length), tracks, { kind: 'playlist', key: p.id }, IconPlaylist)
    })
  }

  const empty = !page && Array.isArray(body) && body.length === 0
  return (
    <div className="fx-library-browser">
      {!page && <FilterPills value={filter} onChange={setFilter} className="compact" />}
      <PushPage pageKey={stack.page ? `${stack.page.kind}:${stack.page.key}` : `list:${filter}`} dir={stack.dir}
        className="fx-library-browse-list">
        {body}
        {empty && (
          <div className="fx-lib-menu-note">
            {lib.tracks.length ? 'Nothing here yet.' : 'The library is empty. Add songs from Library at the top of the page.'}
          </div>
        )}
      </PushPage>
    </div>
  )
}
