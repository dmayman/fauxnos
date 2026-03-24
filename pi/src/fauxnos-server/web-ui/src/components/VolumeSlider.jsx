import { useState, useEffect, useRef } from 'react'

export default function VolumeSlider({ clientId, value, mqtt }) {
  const [localVal, setLocalVal] = useState(value)
  const draggingRef = useRef(false)

  const mqttVol = mqtt.volumes[clientId]
  const displayVol = mqttVol ?? value

  useEffect(() => {
    if (!draggingRef.current) setLocalVal(displayVol)
  }, [displayVol])

  return (
    <div className="volume-control">
      <input
        type="range"
        className="vol-slider"
        min="0"
        max="100"
        value={localVal}
        onPointerDown={() => { draggingRef.current = true }}
        onPointerUp={() => { draggingRef.current = false }}
        onInput={e => {
          const v = parseInt(e.target.value, 10)
          setLocalVal(v)
          mqtt.publishVolume(clientId, v)
        }}
        onChange={() => {}}
      />
      <span className="vol-label">{localVal}%</span>
    </div>
  )
}
