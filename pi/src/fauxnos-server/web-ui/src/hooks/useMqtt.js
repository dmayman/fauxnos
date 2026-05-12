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
  const clientRef = useRef(null)

  // Track last publish time per client to suppress echoes
  const lastPublishRef = useRef({})
  // Throttle state per client: { timerId, pendingValue }
  const throttleRef = useRef({})
  // Per-(client,source) tracking for calibration echo suppression / throttling
  const lastCalPublishRef = useRef({})  // key: `${cid}/${sid}` → timestamp
  const calThrottleRef = useRef({})     // key: `${cid}/${sid}` → { timerId, pendingValue }

  useEffect(() => {
    const wsUrl = `ws://${location.hostname}:9001`
    const client = mqtt.connect(wsUrl, { reconnectPeriod: 5000 })
    clientRef.current = client

    client.on('connect', () => {
      setConnected(true)
      client.subscribe('status/clients/+/volume')
      client.subscribe('status/clients/+/mode')
      client.subscribe('status/clients/+/hello')
      // Per-source calibration: 5-part topic with source_id at the tail
      client.subscribe('status/clients/+/calibration/+')
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
      }
    })

    return () => client.end()
  }, [])

  const publishVolume = useCallback((clientId, vol) => {
    // Optimistic update — always immediate
    setVolumes(prev => ({ ...prev, [clientId]: vol }))

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
  }, [])

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
    publishVolume,
    setMode,
    publishCalibration,
  }
}
