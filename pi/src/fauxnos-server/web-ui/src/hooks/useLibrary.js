import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { apiFetch } from '../api'

/* ─────────────────────────────────────────────────────────────────────────────
 * The server-wide music library (GET /api/library): tracks with tags + art,
 * playlists, storage, and YouTube import jobs. One copy for the whole app,
 * shared through LibraryContext, so the Library panel and each room's
 * Library card agree. Polls every 2 s while an import job is running.
 * ────────────────────────────────────────────────────────────────────────── */

export const LibraryContext = createContext(null)
export const useLibrary = () => useContext(LibraryContext)

// POST {url} for a link preview. Throws the server's own message (yt-dlp's
// or Spotify's reason), not just the status.
async function lookup(path, url) {
  const res = await fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw Object.assign(new Error(body.error || `Lookup failed (${res.status})`), { status: res.status })
  return body
}

const EMPTY = { tracks: [], playlists: [], jobs: [], storage: null, youtube_available: false }

export function useLibraryState() {
  const [data, setData] = useState(EMPTY)
  const [loaded, setLoaded] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setData(await apiFetch('/api/library'))
    } catch { /* keep the last copy */ }
    setLoaded(true)
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const importing = data.jobs.some(j => j.status === 'running')
  useEffect(() => {
    if (!importing) return undefined
    const id = setInterval(refresh, 2000)
    return () => clearInterval(id)
  }, [importing, refresh])

  const byId = useMemo(() => new Map(data.tracks.map(t => [t.id, t])), [data.tracks])
  const byPath = useMemo(() => new Map(data.tracks.map(t => [t.path, t])), [data.tracks])

  // Upload with progress (fetch can't report upload progress; XHR can).
  const upload = useCallback((files, onProgress) => new Promise((resolve, reject) => {
    const form = new FormData()
    for (const f of files) form.append('file', f)
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/library/upload')
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total)
    xhr.onload = () => {
      let body = {}
      try { body = JSON.parse(xhr.responseText) } catch { /* not JSON */ }
      refresh()
      if (xhr.status >= 200 && xhr.status < 300) resolve(body)
      else reject(new Error(body.errors?.[0]?.error || body.error || `Upload failed (${xhr.status})`))
    }
    xhr.onerror = () => reject(new Error('Upload failed'))
    xhr.send(form)
  }), [refresh])

  const call = useCallback(async (path, method, body) => {
    const res = await apiFetch(path, { method, body: body ? JSON.stringify(body) : undefined })
    refresh()
    return res
  }, [refresh])

  const api = useMemo(() => ({
    upload,
    deleteTrack: (id) => call(`/api/library/tracks/${id}`, 'DELETE'),
    updateTrack: (id, changes) => call(`/api/library/tracks/${id}`, 'PATCH', changes),
    youtubePreview: (url) => lookup('/api/library/youtube/preview', url),
    spotifyPreview: (url) => lookup('/api/library/spotify/preview', url),
    createPlaylist: (name, trackIds) => call('/api/library/playlists', 'POST', { name, track_ids: trackIds }),
    renamePlaylist: (id, name) => call(`/api/library/playlists/${id}`, 'PATCH', { name }),
    addToPlaylist: (id, trackIds) => call(`/api/library/playlists/${id}`, 'PATCH', { add: trackIds }),
    removeFromPlaylist: (id, trackIds) => call(`/api/library/playlists/${id}`, 'PATCH', { remove: trackIds }),
    deletePlaylist: (id) => call(`/api/library/playlists/${id}`, 'DELETE'),
    // job: {url, title, artist, thumbnail} so the import shows in the song
    // list (with a spinner) before the download finishes, plus {tags, art_url}
    // for a Spotify import's details and cover.
    importYoutube: (job) => call('/api/library/youtube', 'POST', job),
    play: (clientId, trackIds) => apiFetch('/api/library/play', {
      method: 'POST', body: JSON.stringify({ client_id: clientId, track_ids: trackIds }),
    }),
  }), [upload, call])

  return { ...data, loaded, byId, byPath, refresh, ...api }
}

/** URL of a track's cover art, or null. */
export const artUrl = (track) => (track?.art ? `/library-art/${track.art}` : null)

/** "3:07" from milliseconds. */
export function fmtDuration(ms) {
  if (!ms && ms !== 0) return ''
  const s = Math.round(ms / 1000)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
