export function normalizeAvatarSrc(src) {
  return typeof src === 'string' ? src.trim() : ''
}

export function shouldRenderAvatar(src, errored = false) {
  return Boolean(normalizeAvatarSrc(src)) && !errored
}

export function getAvatarInitial(name) {
  const label = typeof name === 'string' ? name.trim() : ''
  if (!label) {
    return '?'
  }
  return Array.from(label)[0]?.toUpperCase() ?? '?'
}
