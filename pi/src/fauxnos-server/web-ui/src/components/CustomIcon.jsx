import { getIconSvg } from '../icons/iconData'

export default function CustomIcon({ name, size = 16, ariaHidden = true }) {
  const svg = getIconSvg(name)
  if (!svg) return null
  return (
    <span
      className="fx-custom-icon"
      style={{ width: size, height: size }}
      aria-hidden={ariaHidden}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  )
}
