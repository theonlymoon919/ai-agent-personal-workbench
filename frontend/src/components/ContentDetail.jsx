import { ArrowLeft, BrainCircuit, CirclePlay, ExternalLink, LoaderCircle, RefreshCw, Video } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { openExternalTarget, platformKind, videoPlayer } from '../mediaLinks.js'
import { MarkdownContent } from './LearningPlanDetail.jsx'

export function ContentDetail({ itemId, onBack }) {
  const [item, setItem] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [failedPlayerSrc, setFailedPlayerSrc] = useState('')

  async function load() {
    setLoading(true)
    try {
      setItem(await api.contentItem(itemId))
      setError('')
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [itemId])
  const player = useMemo(() => item ? videoPlayer(item) : null, [item])
  const platform = useMemo(() => item ? platformKind(item) : 'other', [item])
  const playerTarget = item?.source_url || item?.media_url || ''
  const playerFailed = Boolean(player?.src && failedPlayerSrc === player.src)

  if (loading && !item) return <div className="detail-state"><LoaderCircle className="spin" size={28} />正在打开内容详情…</div>
  if (error && !item) return <div className="detail-state is-error"><p>{error}</p><button type="button" className="secondary-button" onClick={load}><RefreshCw size={16} />重新加载</button></div>

  const isVideo = item.category === 'video_trend'
  const DetailIcon = isVideo ? Video : BrainCircuit
  return (
    <div className="detail-page content-detail-page">
      <header className="detail-toolbar"><button type="button" onClick={onBack}><ArrowLeft size={18} />返回今日资讯</button>{item.source_url ? <button type="button" className="secondary-button" onClick={() => openExternalTarget(item.source_url)}>打开原始来源 <ExternalLink size={15} /></button> : null}</header>
      <section className="content-detail-hero">
        <span className="content-detail-hero__icon"><DetailIcon size={25} /></span>
        <div><span className="eyebrow">{isVideo ? '短视频热点' : '今日资讯'}{item.platform ? ` · ${item.platform}` : ''}</span><h1>{item.title}</h1><p>{item.summary || 'AI Agent 已保存这条内容，完整信息见下方。'}</p></div>
      </section>

      {player?.type === 'video' && !playerFailed ? <div className="content-player-wrap"><video className="content-player" src={player.src} controls playsInline preload="metadata" poster={item.thumbnail_url || undefined} onError={() => setFailedPlayerSrc(player.src)} /><p><CirclePlay size={14} />站内播放 · 可使用播放器全屏按钮</p></div> : null}
      {player?.type === 'iframe' && !playerFailed ? <div className="content-player-wrap"><div className="content-embed"><iframe src={player.src} title={item.title} allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; fullscreen" allowFullScreen referrerPolicy="strict-origin-when-cross-origin" /></div><p><CirclePlay size={14} />站内播放 · 可使用播放器全屏按钮</p></div> : null}
      {(!player || playerFailed) && isVideo && playerTarget ? <button type="button" className={`video-source-card${platform === 'douyin' ? ' is-douyin' : ''}`} onClick={() => openExternalTarget(playerTarget)}><span><CirclePlay size={26} /></span><div><strong>{platform === 'douyin' ? '在抖音播放视频' : '在原平台播放视频'}</strong><small>{playerFailed ? '站内媒体暂时无法播放，已安全保留原始作品入口。' : platform === 'douyin' ? '优先打开抖音 APP；AI Agent 补充真实媒体地址后可站内播放。' : playerTarget}</small></div><ExternalLink size={18} /></button> : null}
      {(!player || playerFailed) && isVideo && !playerTarget ? <div className="video-source-card"><span><CirclePlay size={26} /></span><div><strong>等待 AI Agent 补充可播放地址</strong><small>视频详情已经保存，媒体来源仍在补充。</small></div></div> : null}

      <section className="content-article"><div className="detail-section-heading"><div><span className="eyebrow">DETAILS</span><h2>完整内容</h2></div></div><MarkdownContent markdown={item.details || item.summary || ''} /></section>
    </div>
  )
}
