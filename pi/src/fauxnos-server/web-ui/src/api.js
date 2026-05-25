const API = ''

export async function apiFetch(path, options = {}) {
  const res = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

/**
 * Send a transport command to a client's go-librespot (play/pause/next/prev/seek).
 *
 * The server proxies POST /api/clients/<id>/playback/<action>; for `seek`,
 * pass `{ position_ms }` as the body. UI is optimistic — the real state
 * arrives a few hundred ms later via the MQTT playback topic.
 */
export async function sendPlayback(clientId, action, body) {
  const res = await fetch(API + `/api/clients/${clientId}/playback/${action}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
}

/**
 * Trigger a snapcast orphan cleanup.
 *
 * Walks snapserver's client registry on the server and deletes any client
 * whose id isn't a registered fauxnos device — typically the install-time
 * orphan that snapclient leaves under its pre-rename hostname/MAC. Returns
 * `{deleted: [...], failed: [...], registered_count}`. Idempotent.
 */
export async function cleanupSnapcastOrphans() {
  return apiFetch('/api/snapcast/cleanup-orphans', { method: 'POST' })
}

/**
 * Subscribe to /api/install/stream (SSE).
 *
 * The server emits four event types:
 *   - snapshot: full runner state (sent on subscribe + on snapshot replay)
 *   - step:     a step transitioned (pending → active → succeeded/failed/stalled)
 *   - tail:     a new stdout line was captured for the active step
 *   - done:     the install finished (final snapshot)
 *
 * `onEvent` is called as `onEvent({ type, data })`. Returns an unsubscribe fn.
 */
export function subscribeInstallStream(onEvent) {
  const es = new EventSource(API + '/api/install/stream')
  const handler = (type) => (e) => {
    let data
    try { data = JSON.parse(e.data) } catch { data = e.data }
    onEvent({ type, data })
  }
  es.addEventListener('snapshot', handler('snapshot'))
  es.addEventListener('step', handler('step'))
  es.addEventListener('tail', handler('tail'))
  es.addEventListener('done', handler('done'))
  // Server-Sent Events also fire generic `message` for unnamed events; we
  // don't emit any unnamed events, but keep onerror silent so a transient
  // network blip doesn't surface as a console error.
  es.onerror = () => { /* let the browser auto-reconnect */ }
  return () => { try { es.close() } catch { /* ignore */ } }
}

// ── Update pipeline ─────────────────────────────────────────────────────────

/**
 * Get the server's git status — current SHA, branch, ahead/behind vs
 * origin/main, dirty-ness. Drives the "Update server" pill in the header.
 *
 *   { sha, short_sha, branch, dirty, origin_sha, behind, ahead, fetch_failed }
 *
 * The endpoint runs a `git fetch` on the server before returning, so the
 * counts are accurate at click time. ~500ms typical latency.
 */
export async function getServerVersion() {
  return apiFetch('/api/server/version')
}

/**
 * Get a single client's deploy info — what SHA was last pushed to it via
 * the update pipeline, when, and how many commits behind the server it is.
 *
 *   { client_id, deployed_sha, deployed_sha_short, deployed_at,
 *     deploy_needs_reboot, deploy_log_path, behind_server }
 *
 * Returns all-null fields for clients registered before the pipeline
 * existed; the UI renders that as "unknown — first update will sync."
 */
export async function getClientVersion(clientId) {
  return apiFetch(`/api/clients/${clientId}/version`)
}

/**
 * Stream a POST endpoint that responds with text/event-stream as its
 * response body. `EventSource` is GET-only, so we use fetch() + the
 * ReadableStream API to consume the response line-by-line and yield
 * parsed SSE events.
 *
 * Yields `{ type, data }` objects matching the same shape the rest of
 * the app uses. Errors propagate as exceptions.
 *
 * Usage:
 *
 *   for await (const ev of sseFetch('/api/server/update', {
 *     method: 'POST', body: JSON.stringify({ force: true }),
 *   })) {
 *     handleEvent(ev)
 *   }
 *
 * The for-await loop exits naturally when the server closes the stream
 * (final `done` event followed by EOF). To cancel mid-stream, throw or
 * break inside the loop body — the underlying reader is cleaned up.
 */
export async function* sseFetch(url, options = {}) {
  const res = await fetch(API + url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (!res.ok) {
    // For non-stream errors (e.g. 409 update_in_progress), the server
    // returns JSON. Surface it so callers can branch on `.error`.
    let body
    try { body = await res.json() } catch { body = { error: 'unknown', message: res.statusText } }
    const err = new Error(`${res.status}: ${body.error || res.statusText}`)
    err.status = res.status
    err.body = body
    throw err
  }
  if (!res.body) {
    // Some environments give the whole body up front instead of streaming.
    // Parse the text once and yield each event.
    const text = await res.text()
    for (const ev of parseSseBlocks(text)) yield ev
    return
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      // SSE event boundary is a blank line (\n\n). Drain every complete
      // block out of the buffer; keep the trailing partial.
      let idx
      while ((idx = buf.indexOf('\n\n')) !== -1) {
        const block = buf.slice(0, idx)
        buf = buf.slice(idx + 2)
        const parsed = parseSseBlock(block)
        if (parsed) yield parsed
      }
    }
    // Flush any trailing partial as a final event block.
    if (buf.trim()) {
      const parsed = parseSseBlock(buf)
      if (parsed) yield parsed
    }
  } finally {
    try { reader.releaseLock() } catch { /* already released */ }
  }
}

function parseSseBlock(block) {
  // One SSE event = a sequence of `field: value` lines terminated by a
  // blank line. We care about `event:` and `data:`; everything else
  // (`:` keep-alives, `id:`, `retry:`) is ignored.
  let type = 'message'
  const dataLines = []
  for (const raw of block.split('\n')) {
    if (raw.startsWith(':')) continue
    const idx = raw.indexOf(':')
    if (idx === -1) continue
    const field = raw.slice(0, idx)
    let value = raw.slice(idx + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') type = value
    else if (field === 'data') dataLines.push(value)
  }
  if (dataLines.length === 0) return null
  const raw = dataLines.join('\n')
  let data
  try { data = JSON.parse(raw) } catch { data = raw }
  return { type, data }
}

function* parseSseBlocks(text) {
  for (const block of text.split('\n\n')) {
    const parsed = parseSseBlock(block)
    if (parsed) yield parsed
  }
}
