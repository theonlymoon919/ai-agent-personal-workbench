import { ArrowLeft, BookOpen, Film, LoaderCircle, MessageCircle, NotebookPen, RefreshCw, Save, Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { MarkdownContent } from './LearningPlanDetail.jsx'

const kindMeta = {
  book: { label: '书籍', icon: BookOpen },
  movie: { label: '电影', icon: Film },
  documentary: { label: '纪录片', icon: Film },
}

const statusLabels = { want: '想看', in_progress: '进行中', done: '已完成' }

export function LibraryDetail({ itemId, refreshToken, onBack, onDashboardReload }) {
  const [item, setItem] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [progress, setProgress] = useState(0)
  const [position, setPosition] = useState('')
  const [reflection, setReflection] = useState('')

  async function load({ quiet = false } = {}) {
    if (!quiet) setLoading(true)
    try {
      const record = await api.libraryItem(itemId)
      setItem(record)
      setProgress(record.progress_percent || 0)
      setPosition(record.current_position || '')
      setReflection(record.reflection || '')
      setError('')
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      if (!quiet) setLoading(false)
    }
  }

  useEffect(() => { load() }, [itemId])
  useEffect(() => { if (item && refreshToken) load({ quiet: true }) }, [refreshToken])

  async function save(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const nextStatus = Number(progress) >= 100 ? 'done' : Number(progress) > 0 ? 'in_progress' : 'want'
      const updated = await api.updateLibraryItem(item.id, {
        status: nextStatus,
        progress_percent: Number(progress),
        current_position: position,
        reflection,
      })
      setItem(updated)
      await onDashboardReload()
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy(false)
    }
  }

  if (loading && !item) return <div className="detail-state"><LoaderCircle className="spin" size={28} />正在打开书影音记录…</div>
  if (error && !item) return <div className="detail-state is-error"><p>{error}</p><button type="button" className="secondary-button" onClick={() => load()}><RefreshCw size={16} />重新加载</button></div>

  const config = kindMeta[item.kind] || kindMeta.book
  const KindIcon = config.icon
  return (
    <div className="detail-page library-detail-page">
      <header className="detail-toolbar"><button type="button" onClick={onBack}><ArrowLeft size={18} />返回个人成长</button></header>
      <section className="library-hero">
        <span className="library-hero__icon"><KindIcon size={25} /></span>
        <div><span className="eyebrow">{config.label} · {statusLabels[item.status] || '想看'}</span><h1>{item.title}</h1><p>{item.reason || '还没有补充推荐理由。'}</p></div>
        <div className="library-progress-summary"><strong>{item.progress_percent || 0}%</strong><span>{item.current_position || '还未开始'}</span><div><i style={{ width: `${item.progress_percent || 0}%` }} /></div></div>
      </section>

      <div className="library-detail-grid">
        <form className="reading-checkin" onSubmit={save}>
          <div className="detail-section-heading"><div><span className="eyebrow">CHECK-IN</span><h2>更新进度与心得</h2></div></div>
          <label className="reading-progress-control">整体进度 <strong>{progress}%</strong><div><input aria-label="进度滑杆" type="range" min="0" max="100" step="5" value={progress} onChange={(event) => setProgress(event.target.value)} /><span className="reading-progress-number"><input aria-label="完成百分比" type="number" min="0" max="100" value={progress} onChange={(event) => setProgress(Math.max(0, Math.min(100, Number(event.target.value))))} /><i>%</i></span></div></label>
          <label>看到哪里了<input value={position} onChange={(event) => setPosition(event.target.value)} placeholder="例如：第 6 章 / 48 分钟 / 第 2 集" /></label>
          <label>我的想法与心得<textarea rows="8" value={reflection} onChange={(event) => setReflection(event.target.value)} placeholder="把读到或看到这里的感受写下来，也可以直接提出想与 AI Agent 讨论的问题。" /></label>
          <p className="form-note"><MessageCircle size={14} />保存心得后会自动进入 AI Agent 讨论队列，它可以回应并整理成读书或观影笔记。</p>
          <button type="submit" className="primary-button" disabled={busy}><Save size={16} />{busy ? '正在保存…' : '保存进度与心得'}</button>
        </form>

        <div className="library-ai-column">
          <section className="library-note-card"><span className="library-note-card__icon"><Sparkles size={20} /></span><div><span className="eyebrow">AI AGENT</span><h2>讨论与回应</h2>{item.agent_comment ? <MarkdownContent markdown={item.agent_comment} /> : <p>保存你的心得后，AI Agent 的回应会显示在这里。</p>}</div></section>
          <section className="library-note-card"><span className="library-note-card__icon is-notes"><NotebookPen size={20} /></span><div><span className="eyebrow">NOTES</span><h2>整理后的笔记</h2>{item.organized_notes ? <MarkdownContent markdown={item.organized_notes} /> : <p>AI Agent 可以把多次讨论归纳成持续更新的笔记。</p>}</div></section>
        </div>
      </div>
      {error ? <div className="inline-error">{error}</div> : null}
    </div>
  )
}
