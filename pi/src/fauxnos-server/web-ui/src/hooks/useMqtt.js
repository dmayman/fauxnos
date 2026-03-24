import { useState, useEffect, useRef, useCallback } from 'react'
import mqtt from 'mqtt'

const ECHO_SUPPRESS_MS = 2000  // ignore inbound echoes for 2s after last publish
const THROTTLE_MS = 100        // send at most every 100ms per client

export function useMqtt() {
  const [connected, setConnected] = useState(false)
  const [volumes, setVolumes] = useState({})
  const [modes, setModes] = useState({})
  const clientRef = useRef(null)

  // Track last publish time per client to suppress echoes
  const lastPublishRef = useRef({})
  // Throttle state per client: { timerId, pendingValue }
  const throttleRef = useRef({})

  useEffect(() => {
    const wsUrl = `ws://${location.hostname}:9001`
    const client = mqtt.connect(wsUrl, { reconnectPeriod: 5000 })
    clientRef.current = client

    client.on('connect', () => {
      setConnected(true)
      client.subscribe('status/clients/+/volume')
      client.subscribe('status/clients/+/mode')
      client.subscribe('status/clients/+/hello')
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
        setModes(prev => ({ ...prev, [deviceId]: msg.toString() }))
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

  return { connected, volumes, modes, publishVolume, setMode }
}
