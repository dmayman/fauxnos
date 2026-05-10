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
