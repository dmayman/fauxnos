import { useState, useEffect, useRef, useCallback } from 'react'
import mqtt from 'mqtt'

const ECHO_SUPPRESS_MS = 2000  // ignore inbound echoes for 2s after last publish
const THROTTLE_MS = 100        // send at most every 100ms per client

export function useMqtt() {
  const [connected, setConnected] = useState(false)
  const [volumes, setVolumes] = useState({})
  const [modes, setModes] = useState({})
  // calibrations: { [deviceId]: { [sourceId]: 0..100 } }
  const [calibrations, setCalibrations] = useState({})
  // tracks:    { [deviceId]: { source, title, artist, album, art_url, duration_ms, uri } }
  // playback:  { [deviceId]: { is_playing, position_ms, updated_at } }
  // playback_manager.py publishes both retained, so a mid-session UI
  // join sees current state without waiting for the next event.
  const [tracks, setTracks] = useState({})
  const [playback, setPlayback] = useState({})
  const clientRef = useRef(null)

  // Track last publish time per client to suppress echoes
  const lastPublishRef = useRef({})
  // Throttle state per client: { timerId, pendingValue }
  const throttleRef = useRef({})
  // Per-(client,source) tracking for calibration echo suppression / throttling
  const lastCalPublishRef = useRef({})  // key: `${cid}/${sid}` → timestamp
  const calThrottleRef = useRef({})     // key: `${cid}/${sid}` → { timerId, pendingValue }

  // External volume controller routing map: { [clientId]: true } for clients
  // whose `external_volume_controller.enabled` is true in server_config. App.jsx
  // populates this via setExternalVolumeMap whenever the client list refreshes.
  // When a clientId is in this map, publishVolume routes its slider moves to
  // POST /api/clients/<id>/external_volume (which fires the configured HTTP
  // POST and pins local PA/snapcast to 100) instead of the direct MQTT publish.
  const externalVolumeMapRef = useRef({})
  // HTTP throttle for external dispatch — separate from MQTT throttle so an
  // external client doesn't share a window with a local one.
  const externalThrottleRef = useRef({})

  useEffect(() => {
    const mqttHost = import.meta.env.DEV ? 'fauxnos000.local' : location.hostname
    const wsUrl = `ws://${mqttHost}:9001`
    const client = mqtt.connect(wsUrl, { reconnectPeriod: 5000 })
    clientRef.current = client

    client.on('connect', () => {
      setConnected(true)
      client.subscribe('status/clients/+/volume')
      client.subscribe('status/clients/+/mode')
      client.subscribe('status/clients/+/hello')
      // Per-source calibration: 5-part topic with source_id at the tail
      client.subscribe('status/clients/+/calibration/+')
      // Now-playing topics published by server's PlaybackManager.
      client.subscribe('status/clients/+/track')
      client.subscribe('status/clients/+/playback')
      // Ask every connected client to broadcast hello so we get
      // initial state (including pa_calibrations) without waiting.
      client.publish('get/clients/all/status', '')
    })
    client.on('close', () => setConnected(false))
    client.on('message', (topic, msg) => {
      const parts = topic.split('/')
      if (parts.length < 4) return
      const deviceId = parts[2]
      const action = parts[3]
      if (action === 'volume') {
        // Suppress echoes — if we recently published to this client,
        // ignore inbound status (our optimistic value is authoritative)
        const lastPub = lastPublishRef.current[deviceId] || 0
        if (Date.now() - lastPub < ECHO_SUPPRESS_MS) return

        setVolumes(prev => ({ ...prev, [deviceId]: parseInt(msg.toString(), 10) }))
      } else if (action === 'mode') {
        // Mode change = new source context. fauxnos-client republishes
        // the new source's stored volume right after the mode message
        // (mqtt_client.py phase 4), but that volume status would land
        // inside the ECHO_SUPPRESS_MS window if the user was dragging
        // the slider just before the source switch — and get dropped.
        // Clear the suppression timestamp here so the next volume
        // status message wins.
        lastPublishRef.current[deviceId] = 0
        setModes(prev => ({ ...prev, [deviceId]: msg.toString() }))
      } else if (action === 'calibration' && parts.length >= 5) {
        const sourceId = parts[4]
        const key = `${deviceId}/${sourceId}`
        const lastPub = lastCalPublishRef.current[key] || 0
        if (Date.now() - lastPub < ECHO_SUPPRESS_MS) return
        const value = parseInt(msg.toString(), 10)
        if (Number.isFinite(value)) {
          setCalibrations(prev => ({
            ...prev,
            [deviceId]: { ...(prev[deviceId] || {}), [sourceId]: value },
          }))
        }
      } else if (action === 'hello') {
        // Hello may include pa_calibrations: {source_id: value, ...}
        try {
          const payload = JSON.parse(msg.toString())
          if (payload && payload.pa_calibrations) {
            setCalibrations(prev => ({
              ...prev,
              [deviceId]: { ...(prev[deviceId] || {}), ...payload.pa_calibrations },
            }))
          }
        } catch (e) { /* ignore */ }
      } else if (action === 'track') {
        // Retained empty payload = session inactive → drop the track.
        const body = msg.toString()
        if (!body) {
          setTracks(prev => {
            if (!(deviceId in prev)) return prev
            const next = { ...prev }
            delete next[deviceId]
            return next
          })
          return
        }
        try {
          const payload = JSON.parse(body)
          setTracks(prev => ({ ...prev, [deviceId]: payload }))
        } catch (e) { /* ignore malformed */ }
      } else if (action === 'playback') {
        const body = msg.toString()
        if (!body) {
          setPlayback(prev => {
            if (!(deviceId in prev)) return prev
            const next = { ...prev }
            delete next[deviceId]
            return next
          })
          return
        }
        try {
          const payload = JSON.parse(body)
          setPlayback(prev => ({ ...prev, [deviceId]: payload }))
        } catch (e) { /* ignore malformed */ }
      }
    })

    return () => client.end()
  }, [])

  // Set the external volume routing map. App.jsx calls this after each
  // /api/clients refresh; we store in a ref so publishVolume always sees the
  // current value without needing to be re-created when the map changes.
  const setExternalVolumeMap = useCallback((map) => {
    externalVolumeMapRef.current = map || {}
  }, [])

  // Fire the external HTTP dispatch with the same throttle shape as MQTT
  // publishVolume — immediate first call, then a trailing-edge timer that
  // sends the latest pending value when the window expires. Particle
  // setVolume can absorb ~2/sec; THROTTLE_MS=100 (10/sec) would hit limits,
  // so we use a longer 250ms window for external dispatches.
  const EXTERNAL_THROTTLE_MS = 250
  const sendExternalVolume = useCallback((clientId, vol) => {
    const fire = (v) => {
      fetch(`/api/clients/${clientId}/external_volume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: v }),
      }).catch(() => { /* swallow — UI optimistic update already happened */ })
    }
    const state = externalThrottleRef.current[clientId]
    if (state?.timerId) {
      state.pendingValue = vol
      return
    }
    fire(vol)
    externalThrottleRef.current[clientId] = {
      pendingValue: null,
      timerId: setTimeout(() => {
        const s = externalThrottleRef.current[clientId]
        if (s?.pendingValue != null) fire(s.pendingValue)
        externalThrottleRef.current[clientId] = null
      }, EXTERNAL_THROTTLE_MS),
    }
  }, [])

  const publishVolume = useCallback((clientId, vol) => {
    // Optimistic update — always immediate, regardless of route.
    setVolumes(prev => ({ ...prev, [clientId]: vol }))

    // Route through the external HTTP endpoint if this client is configured
    // for an external volume controller. The server handler fires the
    // configured HTTP POST AND publishes set/.../volume=100 to pin the local
    // chain at unity, so we don't double-publish here.
    if (externalVolumeMapRef.current[clientId]) {
      sendExternalVolume(clientId, vol)
      return
    }

    // Throttle actual MQTT sends per client
    const now = Date.now()
    lastPublishRef.current[clientId] = now

    const state = throttleRef.current[clientId]
    if (state?.timerId) {
      // Timer already running — just update the pending value
      state.pendingValue = vol
      return
    }

    // No timer running — send immediately and start throttle window
    if (clientRef.current?.connected) {
      clientRef.current.publish(`set/clients/${clientId}/volume`, String(vol))
    }

    throttleRef.current[clientId] = {
      pendingValue: null,
      timerId: setTimeout(() => {
        const s = throttleRef.current[clientId]
        if (s?.pendingValue != null && clientRef.current?.connected) {
          clientRef.current.publish(`set/clients/${clientId}/volume`, String(s.pendingValue))
          lastPublishRef.current[clientId] = Date.now()
        }
        throttleRef.current[clientId] = null
      }, THROTTLE_MS),
    }
  }, [sendExternalVolume])

  const setMode = useCallback((clientId, mode) => {
    setModes(prev => ({ ...prev, [clientId]: mode }))
  }, [])

  /**
   * Publish a calibration change for a given (client, source).
   * Optimistic update + throttled MQTT publish, mirroring publishVolume.
   */
  const publishCalibration = useCallback((clientId, sourceId, value) => {
    // Optimistic
    setCalibrations(prev => ({
      ...prev,
      [clientId]: { ...(prev[clientId] || {}), [sourceId]: value },
    }))

    const key = `${clientId}/${sourceId}`
    const now = Date.now()
    lastCalPublishRef.current[key] = now

    const state = calThrottleRef.current[key]
    if (state?.timerId) {
      state.pendingValue = value
      return
    }

    if (clientRef.current?.connected) {
      clientRef.current.publish(
        `set/clients/${clientId}/calibration/${sourceId}`,
        String(value)
      )
    }

    calThrottleRef.current[key] = {
      pendingValue: null,
      timerId: setTimeout(() => {
        const s = calThrottleRef.current[key]
        if (s?.pendingValue != null && clientRef.current?.connected) {
          clientRef.current.publish(
            `set/clients/${clientId}/calibration/${sourceId}`,
            String(s.pendingValue)
          )
          lastCalPublishRef.current[key] = Date.now()
        }
        calThrottleRef.current[key] = null
      }, THROTTLE_MS),
    }
  }, [])

  return {
    connected,
    volumes,
    modes,
    calibrations,
    tracks,
    playback,
    publishVolume,
    setMode,
    publishCalibration,
    setExternalVolumeMap,
  }
}
