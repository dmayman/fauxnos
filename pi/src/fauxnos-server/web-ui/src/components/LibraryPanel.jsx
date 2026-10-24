import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import {
  IconX,
  IconUpload,
  IconBrandYoutube,
  IconBrandSpotify,
  IconPlayerPlayFilled,
  IconPlus,
  IconDots,
  IconArrowLeft,
  IconPlaylist,
  IconPlaylistAdd,
} from '@tabler/icons-react'
import AnchoredPopover from './AnchoredPopover'
import FormModal from './FormModal'
import { useToast } from './Toasts'
import {
  Art, FilterPills, songsLabel, UNKNOWN_ARTIST, useCollections, usePageStack, PushPage,
} from './LibraryBits'
import { useLibrary, fmtDuration } from '../hooks/useLibrary'
import { homeIdOf } from '../lib/nowPlaying'

/* ─────────────────────────────────────────────────────────────────────────────
 * LibraryPanel — the server-wide music library, as a side panel like the
 * device panel. Drop MP3/M4A files anywhere on it to upload; the Add menu
 * also uploads, imports from YouTube or Spotify (their own page) and makes
 * playlists.
 * Filter pills switch between songs, artists, albums and playlists, which
 * open into their songs. Clicking a song plays it (and the rest of the list
 * after it) in a room; a song playing anywhere shows bars over its art.
 * Messages are toasts; names and details are modals.
 * ────────────────────────────────────────────────────────────────────────── */

const UPLOADABLE = /\.(mp3|m4a)$/i

// Panel-wide actions the rows need (open a modal, the playable rooms).
const PanelContext = createContext(null)

function fmtBytes(n) {
  if (n == null) return ''
  const gb = n / 1e9
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.round(n / 1e6)} MB`
}

/* A button that opens an AnchoredPopover; `children(close)` is its content. */
function MenuButton({ label, className = 'fx-icon-btn', content, children, popoverClass = '' }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const close = useCallback(() => setOpen(false), [])
  return (
    <>
      <button
        ref={ref}
        type="button"
        className={className}
        aria-label={label}
        title={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(e) => { e.stopPropagation(); setOpen(o => !o) }}
      >
        {content}
      </button>
      {open && (
        <AnchoredPopover anchorRef={ref} onClose={close} role="menu" className={`fx-lib-menu ${popoverClass}`}>
          {children(close)}
        </AnchoredPopover>
      )}
    </>
  )
}

function MenuItem({ onClick, danger, icon: Icon, children }) {
  return (
    <button type="button" role="menuitem" className={`fx-lib-menu-item${danger ? ' danger' : ''}`} onClick={onClick}>
      {Icon && <Icon size={16} aria-hidden />}
      {children}
    </button>
  )
}

function PlayButton({ trackIds, label = 'Play' }) {
  const lib = useLibrary()
  const toast = useToast()
  const { rooms } = useContext(PanelContext)
  return (
    <MenuButton label={`${label} in a room`} className="fx-icon-btn fx-lib-play" content={<IconPlayerPlayFilled size={16} />}>
      {(close) => (
        <>
          <div className="fx-lib-menu-caption">Play in</div>
          {rooms.length === 0 && (
            <div className="fx-lib-menu-note">Add Library to a room in its device panel first.</div>
          )}
          {rooms.map(r => (
            <MenuItem
              key={r.id}
              onClick={async () => {
                close()
                try {
                  await lib.play(r.id, trackIds)
                  toast.success(`Playing in ${r.name}`)
                } catch {
                  toast.error(`Couldn't play in ${r.name}`)
                }
              }}
            >
              {r.name}
            </MenuItem>
          ))}
        </>
      )}
    </MenuButton>
  )
}

/* Play `trackIds` from a click, in a room picked from a menu anchored at
   `anchorRef` (always asked, even when only one room has the Library). */
function useRoomPlay(trackIds, anchorRef) {
  const lib = useLibrary()
  const toast = useToast()
  const { rooms } = useContext(PanelContext)
  const [open, setOpen] = useState(false)
  const close = useCallback(() => setOpen(false), [])
  const playIn = async (room) => {
    close()
    try {
      await lib.play(room.id, trackIds)
      toast.success(`Playing in ${room.name}`)
    } catch {
      toast.error(`Couldn't play in ${room.name}`)
    }
  }
  const start = () => {
    if (rooms.length === 0) toast.error('Add Library to a room in its device panel first')
    else setOpen(o => !o)
  }
  const menu = open && (
    <AnchoredPopover anchorRef={anchorRef} onClose={close} role="menu" className="fx-lib-menu">
      <div className="fx-lib-menu-caption">Play in</div>
      {rooms.map(r => <MenuItem key={r.id} onClick={() => playIn(r)}>{r.name}</MenuItem>)}
    </AnchoredPopover>
  )
  return { start, menu }
}

/* Thumbnail with a play icon on hover, and animated bars while the song is
   playing in a room. */
function TrackArt({ track, playingIn }) {
  return (
    <span className="fx-lib-thumb" title={playingIn.length ? `Playing in ${playingIn.join(', ')}` : undefined}>
      <Art track={track} />
      {playingIn.length > 0
        ? <span className="fx-lib-thumb-overlay is-playing" aria-label="Playing"><i /><i /><i /></span>
        : <span className="fx-lib-thumb-overlay is-hover" aria-hidden><IconPlayerPlayFilled size={18} /></span>}
    </span>
  )
}

/* Playlist picker: the add-to-playlist button, and the ⋯ menu's submenu. */
function PlaylistChoices({ trackIds, close }) {
  const lib = useLibrary()
  const toast = useToast()
  const { newPlaylist } = useContext(PanelContext)
  return (
    <>
      <div className="fx-lib-menu-caption">Add to playlist</div>
      {lib.playlists.map(p => (
        <MenuItem
          key={p.id}
          onClick={async () => {
            close()
            try {
              await lib.addToPlaylist(p.id, trackIds)
              toast.success(`Added to ${p.name}`)
            } catch {
              toast.error(`Couldn't add to ${p.name}`)
            }
          }}
        >
          {p.name}
        </MenuItem>
      ))}
      <MenuItem icon={IconPlus} onClick={() => { close(); newPlaylist(trackIds) }}>New playlist…</MenuItem>
    </>
  )
}

function TrackRow({ track, playlist, queue }) {
  const lib = useLibrary()
  const toast = useToast()
  const { editTrack, playingByPath } = useContext(PanelContext)
  const artRef = useRef(null)
  const { start, menu } = useRoomPlay(queue, artRef)
  // Clicks from the row's own menus are portaled out of it but still bubble
  // here through React, so only clicks inside the row's DOM count.
  const onClick = (e) => { if (e.currentTarget.contains(e.target)) start() }
  return (
    <div
      className="fx-lib-row clickable"
      role="button"
      tabIndex={0}
      aria-label={`Play ${track.title}`}
      onClick={onClick}
      onKeyDown={(e) => { if (e.key === 'Enter' && e.target === e.currentTarget) start() }}
    >
      <span ref={artRef}><TrackArt track={track} playingIn={playingByPath.get(track.path) || []} /></span>
      <div className="fx-lib-row-text">
        <span className="fx-lib-row-title" title={track.title}>{track.title}</span>
        <span className="fx-lib-row-sub">
          {[track.artist, track.album].filter(Boolean).join(' · ') || UNKNOWN_ARTIST}
        </span>
      </div>
      <span className="fx-lib-row-time">{fmtDuration(track.duration_ms)}</span>
      <MenuButton label="Add to playlist" className="fx-icon-btn fx-lib-add-to" content={<IconPlaylistAdd size={18} />}>
        {(close) => <PlaylistChoices trackIds={[track.id]} close={close} />}
      </MenuButton>
      <MenuButton label="More" content={<IconDots size={18} />}>
        {(close) => <TrackMenu track={track} playlist={playlist} close={close} lib={lib} toast={toast} editTrack={editTrack} />}
      </MenuButton>
      {menu}
    </div>
  )
}

function TrackMenu({ track, playlist, close, lib, toast, editTrack }) {
  const [picking, setPicking] = useState(false)
  if (picking) return <PlaylistChoices trackIds={[track.id]} close={close} />
  return (
    <>
      <MenuItem onClick={() => { close(); editTrack(track) }}>Edit details…</MenuItem>
      <MenuItem onClick={() => setPicking(true)}>Add to playlist…</MenuItem>
      {playlist && (
        <MenuItem onClick={async () => {
          close()
          try {
            await lib.removeFromPlaylist(playlist.id, [track.id])
            toast.show(`Removed from ${playlist.name}`)
          } catch {
            toast.error(`Couldn't remove from ${playlist.name}`)
          }
        }}>
          Remove from {playlist.name}
        </MenuItem>
      )}
      <MenuItem
        danger
        onClick={async () => {
          close()
          if (!confirm(`Delete "${track.title}" from the library? This removes the file from the server.`)) return
          try {
            await lib.deleteTrack(track.id)
            toast.show(`Deleted ${track.title}`)
          } catch {
            toast.error(`Couldn't delete ${track.title}`)
          }
        }}
      >
        Delete from library
      </MenuItem>
    </>
  )
}

function PlaylistMenu({ playlist, close, onDeleted }) {
  const lib = useLibrary()
  const toast = useToast()
  const { renamePlaylist } = useContext(PanelContext)
  return (
    <>
      <MenuItem onClick={() => { close(); renamePlaylist(playlist) }}>Rename…</MenuItem>
      <MenuItem
        danger
        onClick={async () => {
          close()
          if (!confirm(`Delete the playlist "${playlist.name}"? Its songs stay in the library.`)) return
          try {
            await lib.deletePlaylist(playlist.id)
            toast.show(`Deleted ${playlist.name}`)
            onDeleted?.()
          } catch {
            toast.error(`Couldn't delete ${playlist.name}`)
          }
        }}
      >
        Delete playlist
      </MenuItem>
    </>
  )
}

/* An artist, album or playlist: opens into its songs. */
function CollectionRow({ title, subtitle, art, onOpen, menu, Fallback }) {
  return (
    <div className="fx-lib-row clickable" onClick={onOpen} role="button" tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter') onOpen() }}>
      <Art track={art} Fallback={Fallback} />
      <div className="fx-lib-row-text">
        <span className="fx-lib-row-title" title={title}>{title}</span>
        <span className="fx-lib-row-sub">{subtitle}</span>
      </div>
      {menu && <span onClick={(e) => e.stopPropagation()} className="fx-lib-row-actions">{menu}</span>}
    </div>
  )
}

/* Add from a link — YouTube, or Spotify (details from Spotify, audio from
   the closest YouTube match). Paste it, the details load on their own,
   Import queues it in the background. */
const LINK_SOURCES = {
  youtube: {
    placeholder: 'Paste a YouTube link',
    looking: 'Finding the video…',
    preview: (lib, link) => lib.youtubePreview(link),
    // The import job: what shows in the list while it runs.
    job: (p) => ({ url: p.url, title: p.title, artist: p.artist, thumbnail: p.thumbnail }),
    canImport: (p) => p.importable,
  },
  spotify: {
    placeholder: 'Paste a Spotify song link',
    looking: 'Finding the song and its audio…',
    preview: (lib, link) => lib.spotifyPreview(link),
    job: (p) => ({
      url: p.match.url, title: p.title, artist: p.artist, thumbnail: p.thumbnail,
      tags: { title: p.title, artist: p.artist }, art_url: p.thumbnail,
    }),
    canImport: (p) => !!p.match,
  },
}

function LinkImportView({ source, onDone }) {
  const lib = useLibrary()
  const toast = useToast()
  const src = LINK_SOURCES[source]
  const [url, setUrl] = useState('')
  const [preview, setPreview] = useState(null)
  const [looking, setLooking] = useState(false)
  const lookedUp = useRef('')

  useEffect(() => {
    const link = url.trim()
    if (!/^(https?:\/\/|spotify:)\S+$/.test(link) || link === lookedUp.current) return undefined
    const t = setTimeout(async () => {
      lookedUp.current = link
      setPreview(null)
      setLooking(true)
      try {
        const p = await src.preview(lib, link)
        if (url.trim() === link) setPreview(p)
        if (!src.canImport(p)) {
          toast.error(source === 'spotify' ? "Couldn't find matching audio for that song" : 'That video has no M4A audio to import')
        }
      } catch (e) {
        toast.error(e.status === 503 ? "Importing isn't installed on the server" : `Couldn't look that up: ${e.message}`)
      } finally {
        setLooking(false)
      }
    }, 500)
    return () => clearTimeout(t)
  }, [url, lib, toast, src, source])

  const startImport = async () => {
    try {
      await lib.importYoutube(src.job(preview))
      onDone()
    } catch {
      toast.error("Couldn't start the import")
    }
  }

  return (
    <div className="fx-lib-youtube">
      <input
        className="fx-input"
        type="url"
        placeholder={src.placeholder}
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        autoFocus
        aria-label={src.placeholder}
      />
      {looking && (
        <div className="fx-lib-youtube-looking"><span className="fx-spinner" /> {src.looking}</div>
      )}
      {preview && (
        <div className="fx-lib-youtube-card">
          {preview.thumbnail && (
            <img src={preview.thumbnail} alt="" className={source === 'spotify' ? 'square' : ''} />
          )}
          <div className="fx-lib-youtube-meta">
            <span className="fx-lib-row-title">{preview.title}</span>
            <span className="fx-lib-row-sub">
              {[preview.artist, preview.album].filter(Boolean).join(' · ') || UNKNOWN_ARTIST}
            </span>
            {preview.duration_ms && <span className="fx-lib-row-sub">{fmtDuration(preview.duration_ms)}</span>}
          </div>
          <button type="button" className="fx-btn sm primary" disabled={!src.canImport(preview)} onClick={startImport}>
            Import
          </button>
        </div>
      )}
      {preview?.match && (
        <div className="fx-lib-youtube-match">
          <span>Audio from YouTube:</span>{' '}
          <a href={preview.match.url} target="_blank" rel="noreferrer">{preview.match.title}</a>
          {[preview.match.channel, fmtDuration(preview.match.duration_ms)].filter(Boolean).map(x => ` · ${x}`).join('')}
        </div>
      )}
    </div>
  )
}

/* A toast when a YouTube import finishes or fails. While it runs, the song
   shows in the list with a spinner (ImportingRow), so there's no toast for
   that. Mounted once at the app level, so it reports with the panel closed. */
export function LibraryJobToasts() {
  const lib = useLibrary()
  const toast = useToast()
  const running = useRef(new Set())
  useEffect(() => {
    for (const j of lib.jobs) {
      const name = j.title || 'YouTube audio'
      if (j.status === 'running') {
        running.current.add(j.id)
      } else if (running.current.has(j.id)) {
        // Only jobs we saw running: one that finished before the page loaded stays quiet.
        running.current.delete(j.id)
        if (j.status === 'done') toast.success(`Imported ${name}`)
        else toast.error(`Couldn't import ${name}: ${j.error}`)
      }
    }
  }, [lib.jobs, toast])
  return null
}

/* A YouTube import still downloading: the preview's thumbnail and title,
   with a spinner over the art, until the real song replaces it. */
function ImportingRow({ job }) {
  return (
    <div className="fx-lib-row is-importing" aria-busy="true">
      <span className="fx-lib-thumb">
        <span className="fx-lib-art" style={{ width: 40, height: 40 }}>
          {job.thumbnail && <img src={job.thumbnail} alt="" />}
        </span>
        <span className="fx-lib-thumb-overlay is-busy" aria-label="Importing"><span className="fx-spinner" /></span>
      </span>
      <div className="fx-lib-row-text">
        <span className="fx-lib-row-title" title={job.title || job.url}>{job.title || job.url}</span>
        <span className="fx-lib-row-sub">{job.artist ? `${job.artist} · Importing…` : 'Importing…'}</span>
      </div>
    </div>
  )
}

export default function LibraryPanel({ groups, clients, mqtt, onClose }) {
  const lib = useLibrary()
  const toast = useToast()
  const [view, setView] = useState('browse') // 'browse' | 'youtube' | 'spotify'
  const [filter, setFilter] = useState('songs')
  const [dragging, setDragging] = useState(false)
  const [modal, setModal] = useState(null)
  const fileRef = useRef(null)
  const dragDepth = useRef(0)
  const stack = usePageStack()
  const { artists, albums, pageOf } = useCollections(lib)

  // Rooms that can play the library: their source list includes Library.
  const rooms = useMemo(() => {
    const names = Object.fromEntries((clients || []).map(c => [c.client_id, c.name]))
    return (groups || [])
      .filter(g => (g.sources || []).some(s => s.id === 'library'))
      .map(g => homeIdOf(g))
      .filter(Boolean)
      .map(id => ({ id, name: names[id] || id }))
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [groups, clients])

  const startUpload = useCallback(async (fileList) => {
    const all = [...fileList]
    const files = all.filter(f => UPLOADABLE.test(f.name))
    if (all.length > files.length) {
      const n = all.length - files.length
      toast.error(`Skipped ${n} file${n === 1 ? '' : 's'}: only MP3 and M4A can be uploaded`)
    }
    if (!files.length) return
    const label = files.length === 1 ? files[0].name : `${files.length} files`
    const id = toast.show(`Uploading ${label}`, { progress: 0 })
    try {
      const res = await lib.upload(files, (p) => toast.update(id, { progress: p }))
      const n = res.added?.length || 0
      toast.update(id, { message: `Added ${songsLabel(n)}`, kind: 'success', progress: null })
      for (const e of res.errors || []) toast.error(`${e.file}: ${e.error}`)
    } catch (e) {
      toast.update(id, { message: e.message, kind: 'error', progress: null })
    }
  }, [lib, toast])

  // Drop files anywhere on the panel. dragenter/leave fire for every child,
  // so count depth to know when the drag really leaves.
  const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes('Files')
  const dragHandlers = {
    onDragEnter: (e) => { if (!hasFiles(e)) return; e.preventDefault(); dragDepth.current += 1; setDragging(true) },
    onDragOver: (e) => { if (hasFiles(e)) e.preventDefault() },
    onDragLeave: () => { dragDepth.current -= 1; if (dragDepth.current <= 0) { dragDepth.current = 0; setDragging(false) } },
    onDrop: (e) => {
      if (!hasFiles(e)) return
      e.preventDefault()
      dragDepth.current = 0
      setDragging(false)
      startUpload(e.dataTransfer.files)
    },
  }

  // Which rooms are playing each library path right now (path → names).
  const playingByPath = useMemo(() => {
    const names = Object.fromEntries((clients || []).map(c => [c.client_id, c.name]))
    const map = new Map()
    for (const [id, st] of Object.entries(mqtt?.library || {})) {
      if (st?.state !== 'play' || !st.path || mqtt.modes?.[id] !== 'library') continue
      map.set(st.path, [...(map.get(st.path) || []), names[id] || id])
    }
    return map
  }, [mqtt?.library, mqtt?.modes, clients])

  const panelActions = useMemo(() => ({
    rooms,
    playingByPath,
    newPlaylist: (trackIds = []) => setModal({
      title: 'New playlist',
      submitLabel: 'Create',
      fields: [{ name: 'name', label: 'Name', required: true }],
      onSubmit: async ({ name }) => {
        try {
          await lib.createPlaylist(name.trim(), trackIds)
          toast.success(trackIds.length ? `Added to ${name.trim()}` : `Created ${name.trim()}`)
        } catch (e) { toast.error("Couldn't create the playlist"); throw e }
      },
    }),
    renamePlaylist: (p) => setModal({
      title: 'Rename playlist',
      fields: [{ name: 'name', label: 'Name', value: p.name, required: true }],
      onSubmit: async ({ name }) => {
        try { await lib.renamePlaylist(p.id, name.trim()) } catch (e) { toast.error("Couldn't rename the playlist"); throw e }
      },
    }),
    editTrack: (t) => setModal({
      title: 'Edit details',
      fields: [
        { name: 'title', label: 'Title', value: t.title, required: true },
        { name: 'artist', label: 'Artist', value: t.artist || '' },
        { name: 'album', label: 'Album', value: t.album || '' },
      ],
      onSubmit: async (values) => {
        try { await lib.updateTrack(t.id, values) } catch (e) { toast.error("Couldn't save the details"); throw e }
      },
    }),
  }), [rooms, playingByPath, lib, toast])

  const page = stack.page ? pageOf(stack.page) : null

  let body
  if (page) {
    body = (
      <>
        <div className="fx-lib-drill-head">
          <button type="button" className="fx-icon-btn" aria-label="Back" onClick={stack.pop}>
            <IconArrowLeft size={18} />
          </button>
          <span className="fx-lib-drill-title">{page.title}</span>
          {page.tracks.length > 0 && <PlayButton trackIds={page.tracks.map(t => t.id)} label="Play all" />}
          {page.playlist && (
            <MenuButton label="Playlist options" content={<IconDots size={18} />}>
              {(close) => <PlaylistMenu playlist={page.playlist} close={close} onDeleted={stack.pop} />}
            </MenuButton>
          )}
        </div>
        <div className="fx-lib-list">
          {page.tracks.map((t, i) => (
            <TrackRow key={t.id} track={t} playlist={page.playlist} queue={page.tracks.slice(i).map(x => x.id)} />
          ))}
          {page.tracks.length === 0 && (
            <div className="fx-lib-empty">No songs yet. Use the add-to-playlist button on any song.</div>
          )}
        </div>
      </>
    )
  } else {
    body = (
      <div className="fx-lib-list">
        {filter === 'songs' && lib.jobs.filter(j => j.status === 'running').map(j => (
          <ImportingRow key={j.id} job={j} />
        ))}
        {filter === 'songs' && lib.tracks.map((t, i) => (
          <TrackRow key={t.id} track={t} queue={lib.tracks.slice(i).map(x => x.id)} />
        ))}
        {filter === 'songs' && lib.tracks.length === 0 && lib.loaded && (
          <div className="fx-lib-empty">Drop MP3 or M4A files here, or use Add.</div>
        )}
        {filter === 'artists' && [...artists].map(([name, tracks]) => (
          <CollectionRow
            key={name}
            title={name}
            subtitle={songsLabel(tracks.length)}
            art={tracks.find(t => t.art)}
            onOpen={() => stack.push({ kind: 'artist', key: name })}
          />
        ))}
        {filter === 'albums' && [...albums].map(([key, tracks]) => (
          <CollectionRow
            key={key}
            title={tracks[0].album}
            subtitle={[tracks[0].artist, songsLabel(tracks.length)].filter(Boolean).join(' · ')}
            art={tracks.find(t => t.art)}
            onOpen={() => stack.push({ kind: 'album', key })}
          />
        ))}
        {filter === 'albums' && albums.size === 0 && lib.loaded && (
          <div className="fx-lib-empty">No albums. Albums come from each song's details.</div>
        )}
        {filter === 'playlists' && lib.playlists.map(p => {
          const tracks = p.track_ids.map(id => lib.byId.get(id)).filter(Boolean)
          return (
            <CollectionRow
              key={p.id}
              title={p.name}
              subtitle={songsLabel(tracks.length)}
              art={tracks.find(t => t.art)}
              Fallback={IconPlaylist}
                onOpen={() => stack.push({ kind: 'playlist', key: p.id })}
              menu={(
                <MenuButton label="Playlist options" content={<IconDots size={18} />}>
                  {(close) => <PlaylistMenu playlist={p} close={close} />}
                </MenuButton>
              )}
            />
          )
        })}
        {filter === 'playlists' && lib.playlists.length === 0 && lib.loaded && (
          <div className="fx-lib-empty">No playlists yet. Make one from Add.</div>
        )}
      </div>
    )
  }

  return (
    <PanelContext.Provider value={panelActions}>
      <div className={`fx-side-panel wide fx-library-panel${dragging ? ' is-dragging' : ''}`} {...dragHandlers}>
        <div className="fx-device-panel-head">
          {view !== 'browse' && (
            <button type="button" className="fx-icon-btn" aria-label="Back" onClick={() => setView('browse')}>
              <IconArrowLeft size={18} />
            </button>
          )}
          <span className="fx-h2" style={{ flex: 1 }}>
            {view === 'youtube' ? 'Add from YouTube' : view === 'spotify' ? 'Add from Spotify' : 'Library'}
          </span>
          <button className="fx-icon-btn" onClick={onClose} aria-label="Close">
            <IconX size={18} />
          </button>
        </div>

        {view === 'youtube' || view === 'spotify' ? (
          <LinkImportView key={view} source={view} onDone={() => setView('browse')} />
        ) : (
          <>
            {!page && (
              <div className="fx-lib-filter-row">
                <FilterPills value={filter} onChange={setFilter} />
                <MenuButton label="Add" className="fx-btn sm primary fx-lib-add-btn" content={<><IconPlus size={14} aria-hidden /> Add</>}>
                  {(close) => (
                    <>
                      <MenuItem icon={IconUpload} onClick={() => { close(); fileRef.current?.click() }}>Upload files</MenuItem>
                      <MenuItem
                        icon={IconBrandYoutube}
                        onClick={() => {
                          close()
                          if (lib.youtube_available) setView('youtube')
                          else toast.error("YouTube import isn't installed on the server")
                        }}
                      >
                        From YouTube
                      </MenuItem>
                      <MenuItem
                        icon={IconBrandSpotify}
                        onClick={() => {
                          close()
                          if (lib.youtube_available) setView('spotify')
                          else toast.error("Importing isn't installed on the server")
                        }}
                      >
                        From Spotify
                      </MenuItem>
                      <MenuItem icon={IconPlaylist} onClick={() => { close(); panelActions.newPlaylist() }}>New playlist</MenuItem>
                    </>
                  )}
                </MenuButton>
              </div>
            )}
            {!page && (
              <div className="fx-lib-storage">
                {songsLabel(lib.tracks.length)}
                {lib.storage && ` • ${fmtBytes(lib.storage.free)} free`}
              </div>
            )}
            <PushPage pageKey={stack.page ? `${stack.page.kind}:${stack.page.key}` : `list:${filter}`} dir={stack.dir}>
              {body}
            </PushPage>
          </>
        )}

        <input
          ref={fileRef}
          type="file"
          accept=".mp3,.m4a,audio/mpeg,audio/mp4"
          multiple
          hidden
          onChange={(e) => { startUpload(e.target.files); e.target.value = '' }}
        />

        {dragging && (
          <div className="fx-lib-dropzone" aria-hidden>
            <IconUpload size={28} />
            <span>Drop MP3 or M4A files to upload</span>
          </div>
        )}
      </div>
      {modal && <FormModal {...modal} onClose={() => setModal(null)} />}
    </PanelContext.Provider>
  )
}
