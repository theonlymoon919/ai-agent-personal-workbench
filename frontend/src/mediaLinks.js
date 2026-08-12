const VIDEO_FILE_PATTERN = /\.(?:mp4|m4v|webm|ogg|mov)(?:$|[?#])/i
const KNOWN_VIDEO_CDN_PATTERN = /(?:douyinvod\.com|bytecdn\.cn|pstatp\.com|ixiguavideo\.com|bilivideo\.com)$/i

function parseUrl(value) {
  try {
    return new URL(value)
  } catch {
    return null
  }
}

export function platformKind(item) {
  const label = String(item?.platform || '').toLowerCase()
  const urls = [item?.source_url, item?.media_url].filter(Boolean).map(parseUrl).filter(Boolean)
  if (label.includes('抖音') || label.includes('douyin') || urls.some((url) => /(^|\.)douyin\.com$|(^|\.)iesdouyin\.com$/.test(url.hostname))) return 'douyin'
  if (label.includes('哔哩') || label.includes('b站') || label.includes('bilibili') || urls.some((url) => /(^|\.)bilibili\.com$|(^|\.)b23\.tv$/.test(url.hostname))) return 'bilibili'
  if (label.includes('youtube') || urls.some((url) => /(^|\.)youtube\.com$|(^|\.)youtu\.be$/.test(url.hostname))) return 'youtube'
  return 'other'
}

export function extractDouyinVideoId(value) {
  const parsed = parseUrl(value)
  if (!parsed) return ''
  const pathMatch = parsed.pathname.match(/\/(?:video|discover)\/(\d{8,})/i)
  return pathMatch?.[1] || parsed.searchParams.get('vid')?.match(/^\d{8,}$/)?.[0] || ''
}

export function extractBilibiliVideoId(value) {
  return String(value || '').match(/(?:bilibili\.com\/video\/|^)(BV[\w]+)/i)?.[1] || ''
}

function youtubeEmbed(value) {
  const parsed = parseUrl(value)
  if (!parsed) return ''
  if (/(^|\.)youtube\.com$/.test(parsed.hostname)) {
    const id = parsed.searchParams.get('v') || parsed.pathname.match(/^\/shorts\/([^/?#]+)/)?.[1]
    return id ? `https://www.youtube.com/embed/${id}` : ''
  }
  if (/(^|\.)youtu\.be$/.test(parsed.hostname)) {
    const id = parsed.pathname.split('/').filter(Boolean)[0]
    return id ? `https://www.youtube.com/embed/${id}` : ''
  }
  return ''
}

function isDirectMediaUrl(value, sourceUrl) {
  if (!value) return false
  if (VIDEO_FILE_PATTERN.test(value)) return true
  const parsed = parseUrl(value)
  if (!parsed || !/^https?:$/.test(parsed.protocol)) return false
  if (KNOWN_VIDEO_CDN_PATTERN.test(parsed.hostname)) return true
  if (value === sourceUrl) return false
  if (/(^|\.)(?:douyin\.com|iesdouyin\.com|bilibili\.com|b23\.tv|youtube\.com|youtu\.be)$/.test(parsed.hostname)) return false
  return true
}

export function videoPlayer(item) {
  const mediaUrl = item?.media_url || ''
  const sourceUrl = item?.source_url || ''
  if (isDirectMediaUrl(mediaUrl, sourceUrl)) return { type: 'video', src: mediaUrl, platform: platformKind(item) }

  const youtube = youtubeEmbed(mediaUrl) || youtubeEmbed(sourceUrl)
  if (youtube) return { type: 'iframe', src: youtube, platform: 'youtube' }

  const bilibili = extractBilibiliVideoId(mediaUrl) || extractBilibiliVideoId(sourceUrl)
  if (bilibili) {
    return {
      type: 'iframe',
      src: `https://player.bilibili.com/player.html?bvid=${bilibili}&page=1&high_quality=1`,
      platform: 'bilibili',
    }
  }
  return null
}

export function openExternalTarget(value) {
  if (!value) return false
  const nativeBridge = window.PersonalWorkbenchAndroid
  if (nativeBridge && typeof nativeBridge.openExternalLink === 'function') {
    nativeBridge.openExternalLink(value)
    return true
  }
  window.open(value, '_blank', 'noopener,noreferrer')
  return true
}
