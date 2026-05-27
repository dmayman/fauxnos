import { useState, useMemo, useRef, useEffect } from 'react'
import { ICON_LIST } from '../icons/iconData'

export default function IconPicker({ value, onSelect }) {
  const [q, setQ] = useState('')
  const inputRef = useRef(null)
  useEffect(() => { inputRef.current?.focus() }, [])

  const filtered = useMemo(() => {
    const query = q.trim().toLowerCase()
    if (!query) return ICON_LIST
    const parts = query.split(/\s+/).filter(Boolean)
    return ICON_LIST.filter(({ search }) =>
      parts.every(p => search.includes(p))
    )
  }, [q])

  return (
    <div className="fx-icon-picker">
      <input
        ref={inputRef}
        className="fx-input fx-icon-picker-search"
        type="text"
        placeholder="Search for an icon"
        value={q}
        onChange={e => setQ(e.target.value)}
        autoComplete="off"
        spellCheck={false}
      />
      <div className="fx-icon-picker-grid" role="listbox" aria-label="Tabler icons">
        {filtered.map(({ name, svg }) => (
          <button
            key={name}
            type="button"
            className={`fx-icon-picker-cell${value === name ? ' active' : ''}`}
            title={name.replace(/-/g, ' ')}
            aria-label={name.replace(/-/g, ' ')}
            aria-selected={value === name}
            role="option"
            onClick={() => onSelect(name)}
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        ))}
        {filtered.length === 0 && (
          <div className="fx-icon-picker-empty fx-mute">No icons match "{q}".</div>
        )}
      </div>
    </div>
  )
}
