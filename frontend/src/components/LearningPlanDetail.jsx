import {
  ArrowLeft,
  BookOpenCheck,
  Check,
  ChevronRight,
  CirclePlay,
  Clock3,
  ExternalLink,
  GraduationCap,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api.js'

const statusMeta = {
  waiting_for_hermes: { label: '等待 AI Agent 制定计划', tone: 'waiting' },
  active: { label: '学习中', tone: 'active' },
  paused: { label: '已暂停', tone: 'paused' },
  completed: { label: '已完成', tone: 'completed' },
}

const jobStatusMeta = {
  pending: '已进入待处理队列',
  in_progress: 'AI Agent 正在制定计划',
  completed: 'AI Agent 已完成规划',
  failed: '本次生成未完成',
}

function InlineText({ text }) {
  const parts = text.split(/(\[[^\]]+\]\(https?:\/\/[^)]+\)|\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean)
  return parts.map((part, index) => {
    const link = part.match(/^\[([^\]]+)\]\((https?:\/\/[^)]+)\)$/)
    if (link) return <a key={`${link[2]}-${index}`} href={link[2]} target="_blank" rel="noreferrer">{link[1]} <ExternalLink size={13} /></a>
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>
    if (part.startsWith('`') && part.endsWith('`')) return <code key={index}>{part.slice(1, -1)}</code>
    return <span key={index}>{part}</span>
  })
}

export function MarkdownContent({ markdown }) {
  const lines = markdown.split('\n')
  return <div className="plan-markdown">{lines.map((raw, index) => {
    const line = raw.trim()
    if (!line || (index === 0 && line.startsWith('# '))) return null
    if (line.startsWith('### ')) return <h4 key={index}><InlineText text={line.slice(4)} /></h4>
    if (line.startsWith('## ')) return <h3 key={index}><InlineText text={line.slice(3)} /></h3>
    if (line.startsWith('# ')) return <h2 key={index}><InlineText text={line.slice(2)} /></h2>
    const task = line.match(/^- \[([ xX])\] (.+)$/)
    if (task) return <div className={`plan-check ${task[1].toLowerCase() === 'x' ? 'is-done' : ''}`} key={index}><span><Check size={12} /></span><InlineText text={task[2]} /></div>
    if (line.startsWith('- ')) return <div className="plan-bullet" key={index}><i /><p><InlineText text={line.slice(2)} /></p></div>
    if (/^\d+[.)]\s/.test(line)) return <div className="plan-numbered" key={index}><span>{line.match(/^\d+/)[0]}</span><p><InlineText text={line.replace(/^\d+[.)]\s*/, '')} /></p></div>
    return <p key={index}><InlineText text={line} /></p>
  })}</div>
}

function ResourceList({ resources }) {
  if (!resources?.length) return null
  return (
    <section className="plan-resources">
      <div className="detail-section-heading"><div><span className="eyebrow">RESOURCES</span><h2>学习资料</h2></div><span>{resources.length} 项</span></div>
      <div className="resource-list">{resources.map((resource) => (
        <a href={resource.url} target="_blank" rel="noreferrer" key={resource.url}>
          <span className="resource-icon">{(resource.type || resource.resource_type) === 'video' ? <CirclePlay size={20} /> : <BookOpenCheck size={20} />}</span>
          <span><strong>{resource.title}</strong><small>{[resource.platform || resource.domain, resource.published_at ? `发布于 ${String(resource.published_at).slice(0, 10)}` : '', resource.verified_at ? '已核验' : ''].filter(Boolean).join(' · ')}</small>{resource.relevance_reason ? <em>{resource.relevance_reason}</em> : null}</span>
          <ChevronRight size={18} />
        </a>
      ))}</div>
    </section>
  )
}

function LearningPlanEditorDialog({ plan, busy, error, onClose, onSave }) {
  return (
    <div className="dialog-backdrop" role="presentation">
      <section className="record-dialog plan-editor-dialog" role="dialog" aria-modal="true" aria-labelledby="plan-editor-title">
        <header><div><span className="eyebrow">LEARNING PLAN</span><h2 id="plan-editor-title">编辑学习计划</h2></div><button type="button" onClick={onClose} aria-label="关闭"><X size={19} /></button></header>
        <form onSubmit={(event) => {
          event.preventDefault()
          const form = new FormData(event.currentTarget)
          onSave({ name: form.get('name'), goal: form.get('goal'), status: form.get('status') })
        }}>
          <label><span>计划名称</span><input name="name" defaultValue={plan.name} maxLength="120" required autoFocus /></label>
          <label><span>学习目标</span><textarea name="goal" defaultValue={plan.goal || ''} maxLength="1000" rows="4" placeholder="写下希望达到的结果和验收标准" /></label>
          <label><span>当前状态</span><select name="status" defaultValue={plan.status}>
            <option value="waiting_for_hermes" disabled={plan.status !== 'waiting_for_hermes'}>等待 AI Agent 制定计划</option>
            <option value="active">学习中</option>
            <option value="paused">已暂停</option>
            <option value="completed">已完成</option>
          </select></label>
          <p className="dialog-helper">编辑名称和目标不会覆盖 AI Agent 已生成的课程与学习资料。</p>
          {error ? <p className="form-error">{error}</p> : null}
          <div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>取消</button><button type="submit" className="primary-button" disabled={busy}>{busy ? '正在保存…' : '保存修改'}</button></div>
        </form>
      </section>
    </div>
  )
}

function LearningPlanDeleteDialog({ plan, busy, error, onClose, onConfirm }) {
  return (
    <div className="dialog-backdrop" role="presentation">
      <section className="record-dialog compact-dialog" role="alertdialog" aria-modal="true" aria-labelledby="plan-delete-title" aria-describedby="plan-delete-description">
        <header><div><span className="eyebrow">CONFIRM DELETE</span><h2 id="plan-delete-title">删除学习计划？</h2></div><button type="button" onClick={onClose} aria-label="关闭"><X size={19} /></button></header>
        <div className="confirm-dialog-body">
          <p id="plan-delete-description">“{plan.name}”将移入计划回收站，普通列表和 AI Agent 写回不会再把它当作有效计划。之后仍可从回收站恢复。</p>
          {error ? <p className="form-error">{error}</p> : null}
          <div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>保留计划</button><button type="button" className="danger-button" disabled={busy} onClick={onConfirm}>{busy ? '正在删除…' : '确认移入回收站'}</button></div>
        </div>
      </section>
    </div>
  )
}

export function LearningPlanDetail({ planId, refreshToken, onBack, onNewPlan, onDashboardReload, onDeleted }) {
  const [plan, setPlan] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  async function load({ quiet = false } = {}) {
    if (!quiet) setLoading(true)
    try {
      setPlan(await api.learningPlan(planId))
      setError('')
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      if (!quiet) setLoading(false)
    }
  }

  useEffect(() => { load() }, [planId])
  useEffect(() => { if (plan && refreshToken) load({ quiet: true }) }, [refreshToken])

  async function completeLesson() {
    if (!plan || busy) return
    setBusy(true)
    try {
      const nextCompleted = Math.min(plan.completed_lessons + 1, plan.total_lessons || plan.completed_lessons + 1)
      setPlan(await api.updateLearningProgress(plan.id, { completed_lessons: nextCompleted }))
      await onDashboardReload()
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy(false)
    }
  }

  async function savePlan(changes) {
    if (!plan || busy) return
    setBusy(true)
    setError('')
    try {
      setPlan(await api.updateLearningPlan(plan.id, changes))
      setEditing(false)
      await onDashboardReload()
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy(false)
    }
  }

  async function deletePlan() {
    if (!plan || busy) return
    setBusy(true)
    setError('')
    try {
      await api.deleteLearningPlan(plan.id)
      if (onDeleted) await onDeleted()
      else {
        await onDashboardReload()
        onBack()
      }
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy(false)
    }
  }

  if (loading && !plan) return <div className="detail-state"><LoaderCircle className="spin" size={28} />正在打开学习计划…</div>
  if (error && !plan) return <div className="detail-state is-error"><p>{error}</p><button type="button" className="secondary-button" onClick={() => load()}><RefreshCw size={16} />重新加载</button></div>

  const status = statusMeta[plan.status] || statusMeta.waiting_for_hermes
  const percent = plan.total_lessons ? Math.round((plan.completed_lessons / plan.total_lessons) * 100) : 0
  const waiting = ['waiting_for_hermes'].includes(plan.status) || ['pending', 'in_progress'].includes(plan.agent_job?.status)

  return (
    <div className="detail-page">
      <header className="detail-toolbar">
        <button type="button" onClick={onBack}><ArrowLeft size={18} />返回个人成长</button>
        <div><button type="button" className="secondary-button" onClick={() => { setError(''); setEditing(true) }}><Pencil size={15} />编辑</button><button type="button" className="secondary-button is-danger" onClick={() => { setError(''); setConfirmingDelete(true) }}><Trash2 size={15} />删除</button><button type="button" className="secondary-button" onClick={onNewPlan}><Plus size={16} />新计划</button></div>
      </header>

      <section className="plan-hero">
        <div className="plan-hero__main">
          <span className={`plan-status plan-status--${status.tone}`}>{status.label}</span>
          <h1>{plan.name}</h1>
          <p>{plan.goal || '还没有填写学习目标。'}</p>
        </div>
        <div className="plan-progress-card">
          <div><span>学习进度</span><strong>{plan.completed_lessons}<small> / {plan.total_lessons || '--'} 课</small></strong></div>
          <div className="plan-progress-track"><i style={{ width: `${percent}%` }} /></div>
          <span>{plan.total_lessons ? `${percent}%` : '等待计划生成'}</span>
        </div>
      </section>

      {waiting ? (
        <section className="agent-job-card">
          <span className="agent-job-card__icon"><Sparkles size={22} /></span>
          <div><span className="eyebrow">AI AGENT TASK</span><h2>{jobStatusMeta[plan.agent_job?.status] || '准备生成学习计划'}</h2><p>AI Agent 接入后会读取你的目标，拆分每日课程，并把可直接打开的视频与资料写回这里。</p></div>
          <span className="job-reference"><Clock3 size={14} />{plan.agent_job?.id || '正在建立任务'}</span>
        </section>
      ) : null}

      <div className="plan-detail-grid">
        <section className="plan-roadmap">
          <div className="detail-section-heading"><div><span className="eyebrow">ROADMAP</span><h2>学习路线</h2></div>{plan.total_lessons ? <button type="button" className="primary-button" disabled={busy || plan.status === 'completed'} onClick={completeLesson}>{busy ? '正在记录…' : plan.status === 'completed' ? '计划已完成' : '完成一课'}</button> : null}</div>
          <MarkdownContent markdown={plan.details || ''} />
        </section>
        <ResourceList resources={plan.resources} />
      </div>
      {error ? <div className="inline-error">{error}</div> : null}
      {editing ? <LearningPlanEditorDialog plan={plan} busy={busy} error={error} onClose={() => !busy && setEditing(false)} onSave={savePlan} /> : null}
      {confirmingDelete ? <LearningPlanDeleteDialog plan={plan} busy={busy} error={error} onClose={() => !busy && setConfirmingDelete(false)} onConfirm={deletePlan} /> : null}
    </div>
  )
}
