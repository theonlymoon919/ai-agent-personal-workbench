import {
  ArrowLeft,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Diamond,
  Edit3,
  Filter,
  Flag,
  FolderKanban,
  Layers3,
  Link2,
  ListTodo,
  LoaderCircle,
  MoreVertical,
  Plus,
  RotateCcw,
  Save,
  Trash2,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'

const statusMeta = {
  planned: { label: '待开始', tone: 'planned' },
  in_progress: { label: '进行中', tone: 'active' },
  blocked: { label: '受阻', tone: 'blocked' },
  completed: { label: '已完成', tone: 'completed' },
  cancelled: { label: '已取消', tone: 'cancelled' },
  active: { label: '进行中', tone: 'active' },
  paused: { label: '已暂停', tone: 'blocked' },
}

const scaleMeta = {
  day: { label: '日', pixelsPerDay: 34, step: 1 },
  week: { label: '周', pixelsPerDay: 13, step: 7 },
  month: { label: '月', pixelsPerDay: 5, step: 30 },
  quarter: { label: '季度', pixelsPerDay: 2.4, step: 90 },
}

function parseDate(value) {
  if (!value) return null
  if (value instanceof Date) {
    if (Number.isNaN(value.getTime())) return null
    const parsed = new Date(value)
    parsed.setHours(12, 0, 0, 0)
    return parsed
  }
  const parsed = new Date(`${String(value).slice(0, 10)}T12:00:00`)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function isoDate(value) {
  const parsed = parseDate(value)
  if (!parsed) return ''
  const year = parsed.getFullYear()
  const month = String(parsed.getMonth() + 1).padStart(2, '0')
  const day = String(parsed.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function dateDiff(start, end) {
  return Math.round((end.getTime() - start.getTime()) / 86400000)
}

function addDays(value, amount) {
  const next = new Date(value)
  next.setDate(next.getDate() + amount)
  return next
}

function formatDate(value, withYear = false) {
  const parsed = parseDate(value)
  if (!parsed) return '未排期'
  return new Intl.DateTimeFormat('zh-CN', withYear
    ? { year: 'numeric', month: '2-digit', day: '2-digit' }
    : { month: '2-digit', day: '2-digit' }).format(parsed)
}

function taskRange(task) {
  const start = task.start_date || task.end_date || task.due_at
  const end = task.end_date || task.start_date || task.due_at
  return { start: isoDate(start), end: isoDate(end) }
}

function rangeFromTasks(tasks) {
  const dates = tasks.flatMap((task) => {
    const range = taskRange(task)
    return [parseDate(range.start), parseDate(range.end)].filter(Boolean)
  })
  if (!dates.length) return { start: '', end: '' }
  return {
    start: new Date(Math.min(...dates)).toISOString().slice(0, 10),
    end: new Date(Math.max(...dates)).toISOString().slice(0, 10),
  }
}

function timelineTicks(start, end, count = 4) {
  const totalDays = Math.max(1, dateDiff(start, end))
  const offsets = Array.from({ length: count }, (_, index) => Math.round((totalDays * index) / (count - 1)))
  return [...new Set(offsets)].map((offset) => addDays(start, offset))
}

function StatusBadge({ status }) {
  const meta = statusMeta[status] || statusMeta.planned
  return <span className={`planner-status planner-status--${meta.tone}`}>{meta.label}</span>
}

function ConfirmDialog({ title, description, busy, onCancel, onConfirm }) {
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onCancel()}>
      <section className="record-dialog confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="planner-confirm-title">
        <header><span className="dialog-icon is-danger"><CircleAlert size={21} /></span><div><h2 id="planner-confirm-title">{title}</h2><p>{description}</p></div><button type="button" className="dialog-close" onClick={onCancel} aria-label="关闭"><X size={20} /></button></header>
        <div className="confirm-dialog-body"><p>删除后会进入回收站，可以恢复。</p><div className="dialog-actions"><button type="button" className="secondary-button" onClick={onCancel}>取消</button><button type="button" className="primary-button is-danger" disabled={busy} onClick={onConfirm}>{busy ? '正在删除…' : '确认删除'}</button></div></div>
      </section>
    </div>
  )
}

function ProjectForm({ project, busy, error, onClose, onSubmit }) {
  const [name, setName] = useState(project?.name || '')
  const [description, setDescription] = useState(project?.description || '')
  const [startDate, setStartDate] = useState(isoDate(project?.start_date))
  const [dueDate, setDueDate] = useState(isoDate(project?.due_date))
  const [status, setStatus] = useState(project?.status || 'active')
  const [currentStage, setCurrentStage] = useState(project?.current_stage || '准备中')
  const [nextMilestone, setNextMilestone] = useState(project?.next_milestone || '')

  return <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section className="record-dialog planner-form-dialog" role="dialog" aria-modal="true"><header><span className="dialog-icon"><FolderKanban size={21} /></span><div><h2>{project ? '编辑项目' : '新建项目'}</h2><p>先写清目标与边界，再用阶段和任务展开。</p></div><button type="button" className="dialog-close" onClick={onClose} aria-label="关闭"><X size={20} /></button></header><form onSubmit={(event) => { event.preventDefault(); onSubmit({ name: name.trim(), description: description.trim(), start_date: startDate || null, due_date: dueDate || null, status, current_stage: currentStage.trim() || '准备中', next_milestone: nextMilestone.trim() }) }}>
    <label>项目名称<input autoFocus required maxLength={160} value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：年度学习与成长计划" /></label>
    <label>项目说明<textarea rows="3" maxLength={4000} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="这个项目要解决什么问题，完成标准是什么？" /></label>
    <div className="form-columns"><label>开始日期<input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label><label>目标日期<input type="date" value={dueDate} min={startDate || undefined} onChange={(event) => setDueDate(event.target.value)} /></label></div>
    <div className="form-columns"><label>当前阶段<input maxLength={200} value={currentStage} onChange={(event) => setCurrentStage(event.target.value)} /></label><label>项目状态<select value={status} onChange={(event) => setStatus(event.target.value)}><option value="active">进行中</option><option value="paused">已暂停</option><option value="completed">已完成</option></select></label></div>
    <label>下一里程碑<input maxLength={500} value={nextMilestone} onChange={(event) => setNextMilestone(event.target.value)} placeholder="例如：可交互原型" /></label>
    {error ? <p className="form-error" role="alert">{error}</p> : null}<div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>取消</button><button type="submit" className="primary-button" disabled={busy || !name.trim()}><Save size={15} />{busy ? '保存中…' : '保存项目'}</button></div>
  </form></section></div>
}

function PhaseForm({ phase, nextOrder, busy, error, onClose, onSubmit }) {
  const [name, setName] = useState(phase?.name || '')
  const [description, setDescription] = useState(phase?.description || '')
  const [startDate, setStartDate] = useState(isoDate(phase?.start_date))
  const [endDate, setEndDate] = useState(isoDate(phase?.end_date))
  const [status, setStatus] = useState(phase?.status || 'active')
  const [orderIndex, setOrderIndex] = useState(phase?.order_index ?? nextOrder ?? 0)
  return <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section className="record-dialog planner-form-dialog" role="dialog" aria-modal="true"><header><span className="dialog-icon"><Layers3 size={21} /></span><div><h2>{phase ? '编辑阶段' : '新建阶段'}</h2><p>阶段是一组有共同结果和时间范围的任务。</p></div><button type="button" className="dialog-close" onClick={onClose} aria-label="关闭"><X size={20} /></button></header><form onSubmit={(event) => { event.preventDefault(); onSubmit({ name: name.trim(), description: description.trim(), start_date: startDate || null, end_date: endDate || null, status, order_index: Number(orderIndex) }) }}>
    <label>阶段名称<input autoFocus required maxLength={160} value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：产品定义" /></label>
    <label>完成标准<textarea rows="3" maxLength={4000} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="这一阶段做到什么算完成？" /></label>
    <div className="form-columns"><label>开始日期<input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label><label>结束日期<input type="date" value={endDate} min={startDate || undefined} onChange={(event) => setEndDate(event.target.value)} /></label></div>
    <div className="form-columns"><label>阶段状态<select value={status} onChange={(event) => setStatus(event.target.value)}><option value="active">进行中</option><option value="paused">已暂停</option><option value="completed">已完成</option></select></label><label>显示顺序<input type="number" min="0" max="100000" value={orderIndex} onChange={(event) => setOrderIndex(event.target.value)} /></label></div>
    {error ? <p className="form-error" role="alert">{error}</p> : null}<div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>取消</button><button type="submit" className="primary-button" disabled={busy || !name.trim()}><Save size={15} />{busy ? '保存中…' : '保存阶段'}</button></div>
  </form></section></div>
}

function TaskForm({ task, projectName, phases, tasks, defaultPhaseId, busy, error, onClose, onSubmit, onDelete }) {
  const [title, setTitle] = useState(task?.title || '')
  const [phaseId, setPhaseId] = useState(task?.phase_id || defaultPhaseId || '')
  const [quadrant, setQuadrant] = useState(task?.quadrant || 'important_not_urgent')
  const [startDate, setStartDate] = useState(isoDate(task?.start_date))
  const [endDate, setEndDate] = useState(isoDate(task?.end_date))
  const [status, setStatus] = useState(task?.status || 'planned')
  const [progress, setProgress] = useState(task?.progress_percent || 0)
  const [milestone, setMilestone] = useState(Boolean(task?.is_milestone))
  const [note, setNote] = useState(task?.note || '')
  const [predecessors, setPredecessors] = useState(task?.predecessor_ids || [])
  const candidates = tasks.filter((item) => item.id !== task?.id && !item.deleted)

  function togglePredecessor(id) {
    setPredecessors((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])
  }

  return <div className="planner-drawer-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><aside className="planner-task-drawer" role="dialog" aria-modal="true" aria-labelledby="planner-task-title"><header><div><span className="planner-breadcrumb">{task?.project_name || projectName || '当前项目'} <ChevronRight size={12} /> {phases.find((item) => item.id === phaseId)?.name || '未分阶段'}</span><h2 id="planner-task-title">{task ? '编辑任务' : '新建任务'}</h2></div><button type="button" onClick={onClose} aria-label="关闭"><X size={21} /></button></header><form onSubmit={(event) => { event.preventDefault(); const normalizedProgress = status === 'completed' ? 100 : Number(progress); onSubmit({ title: title.trim(), quadrant, project_id: task?.project_id || undefined, phase_id: phaseId || null, start_date: startDate || null, end_date: endDate || null, status, progress_percent: normalizedProgress, is_milestone: milestone, note: note.trim(), recurrence: task?.recurrence || 'none', predecessor_ids: predecessors }) }}>
    <label>任务名称<input autoFocus={!task} required maxLength={160} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="写成一个可以完成的动作" /></label>
    <label>所属阶段<select value={phaseId} onChange={(event) => setPhaseId(event.target.value)}><option value="">未分阶段</option>{phases.filter((item) => !item.deleted).map((phase) => <option value={phase.id} key={phase.id}>{phase.name}</option>)}</select></label>
    <div className="form-columns"><label>开始日期<input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label><label>结束日期<input type="date" min={startDate || undefined} value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label></div>
    <div className="form-columns"><label>状态<select value={status} onChange={(event) => { const next = event.target.value; setStatus(next); if (next === 'completed') setProgress(100) }}><option value="planned">待开始</option><option value="in_progress">进行中</option><option value="blocked">受阻</option><option value="completed">已完成</option><option value="cancelled">已取消</option></select></label><label>四象限<select value={quadrant} onChange={(event) => setQuadrant(event.target.value)}><option value="important_urgent">重要 · 紧急</option><option value="important_not_urgent">重要 · 不紧急</option><option value="not_important_urgent">不重要 · 紧急</option><option value="not_important_not_urgent">不重要 · 不紧急</option></select></label></div>
    <label>完成进度<div className="planner-range-control"><input type="range" min="0" max="100" step="5" value={progress} disabled={status === 'completed'} onChange={(event) => { setProgress(event.target.value); if (Number(event.target.value) > 0 && status === 'planned') setStatus('in_progress') }} /><strong>{status === 'completed' ? 100 : progress}%</strong></div></label>
    <label className="planner-check"><input type="checkbox" checked={milestone} onChange={(event) => setMilestone(event.target.checked)} /><Diamond size={16} />这是里程碑</label>
    <label>说明<textarea rows="3" maxLength={4000} value={note} onChange={(event) => setNote(event.target.value)} placeholder="补充完成标准、交付物或注意事项" /></label>
    <fieldset className="planner-dependencies"><legend>前置任务</legend>{candidates.length ? candidates.map((item) => <label key={item.id}><input type="checkbox" checked={predecessors.includes(item.id)} onChange={() => togglePredecessor(item.id)} /><span>{item.title}</span><small>{item.phase_name || '未分阶段'}</small></label>) : <p>还没有可作为前置条件的其他任务。</p>}</fieldset>
    {error ? <p className="form-error" role="alert">{error}</p> : null}<div className="planner-drawer-actions"><button type="submit" className="primary-button" disabled={busy || !title.trim()}><Save size={15} />{busy ? '保存中…' : task ? '保存修改' : '创建任务'}</button>{task ? <button type="button" className="text-danger-button" onClick={onDelete}><Trash2 size={15} />删除任务</button> : null}</div>
  </form></aside></div>
}

function RecycleDialog({ projects, plan, busyId, error, onClose, onRestoreProject, onRestorePhase, onRestoreTask }) {
  const deletedProjects = projects.filter((item) => item.deleted)
  const deletedPhases = (plan?.phases || []).filter((item) => item.deleted)
  const deletedTasks = (plan?.tasks || []).filter((item) => item.deleted)
  const empty = !deletedProjects.length && !deletedPhases.length && !deletedTasks.length
  return <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section className="record-dialog recycle-dialog planner-recycle" role="dialog" aria-modal="true"><header><div><span className="eyebrow">RECYCLE BIN</span><h2>项目回收站</h2><p>恢复后会回到原来的层级和排期位置。</p></div><button type="button" className="dialog-close" onClick={onClose} aria-label="关闭"><X size={20} /></button></header><div className="recycle-dialog__body">{empty ? <div className="health-empty"><Trash2 size={25} /><h3>回收站是空的</h3><p>项目、阶段和任务删除后会出现在这里。</p></div> : <>
    {deletedProjects.length ? <section><h3>项目</h3>{deletedProjects.map((item) => <article key={item.id}><div><b>{item.name}</b><span>{item.description || '未填写说明'}</span></div><button type="button" className="secondary-button" disabled={busyId === item.id} onClick={() => onRestoreProject(item)}><RotateCcw size={14} />恢复</button></article>)}</section> : null}
    {deletedPhases.length ? <section><h3>当前项目的阶段</h3>{deletedPhases.map((item) => <article key={item.id}><div><b>{item.name}</b><span>{formatDate(item.start_date)} — {formatDate(item.end_date)}</span></div><button type="button" className="secondary-button" disabled={busyId === item.id} onClick={() => onRestorePhase(item)}><RotateCcw size={14} />恢复</button></article>)}</section> : null}
    {deletedTasks.length ? <section><h3>当前项目的任务</h3>{deletedTasks.map((item) => <article key={item.id}><div><b>{item.title}</b><span>{item.phase_name || '未分阶段'}</span></div><button type="button" className="secondary-button" disabled={busyId === item.id} onClick={() => onRestoreTask(item)}><RotateCcw size={14} />恢复</button></article>)}</section> : null}
  </>}{error ? <p className="form-error">{error}</p> : null}</div></section></div>
}

function PlannerSummary({ project }) {
  return <section className="planner-summary"><div className="planner-progress-ring" style={{ '--planner-progress': `${project.progress_percent * 3.6}deg` }}><span>{project.progress_percent}%</span></div><div><small>整体进度</small><strong>{project.progress_percent}%</strong></div><div><CalendarDays size={23} /><span><small>目标日期</small><strong>{project.due_date ? formatDate(project.due_date, true) : '暂未设置'}</strong></span></div><div><Flag size={23} /><span><small>下一里程碑</small><strong>{project.next_milestone || '暂未设置'}</strong></span></div></section>
}

function buildPlannerRows(plan) {
  if (!plan?.project) return []
  const activePhases = plan.phases.filter((item) => !item.deleted)
  const activeTasks = plan.tasks.filter((item) => !item.deleted && item.status !== 'cancelled')
  const tasksByPhase = new Map()
  activeTasks.forEach((task) => {
    const key = task.phase_id || 'unphased'
    if (!tasksByPhase.has(key)) tasksByPhase.set(key, [])
    tasksByPhase.get(key).push(task)
  })
  const rows = [{ kind: 'project', id: plan.project.id, data: plan.project, range: { start: plan.project.start_date || plan.date_range?.start_date, end: plan.project.due_date || plan.date_range?.end_date } }]
  activePhases.forEach((phase) => {
    const tasks = tasksByPhase.get(phase.id) || []
    const derived = rangeFromTasks(tasks)
    rows.push({ kind: 'phase', id: phase.id, data: phase, range: { start: phase.start_date || derived.start, end: phase.end_date || derived.end } })
    tasks.forEach((task) => rows.push({ kind: 'task', id: task.id, data: task, range: taskRange(task) }))
  })
  const unphased = tasksByPhase.get('unphased') || []
  if (unphased.length) {
    rows.push({ kind: 'unphased', id: 'unphased', data: { name: `未分阶段 ${unphased.length}`, progress_percent: 0 }, range: rangeFromTasks(unphased) })
    unphased.forEach((task) => rows.push({ kind: 'task', id: task.id, data: task, range: taskRange(task) }))
  }
  return rows
}

function Timeline({ rows, scale, rangeStart, rangeEnd, selectedTaskId, onSelectTask }) {
  const meta = scaleMeta[scale]
  const totalDays = Math.max(1, dateDiff(rangeStart, rangeEnd) + 1)
  const width = Math.max(720, Math.ceil(totalDays * meta.pixelsPerDay))
  const ticks = Array.from({ length: Math.floor(totalDays / meta.step) + 1 }, (_, index) => {
    const day = addDays(rangeStart, index * meta.step)
    return { day, left: (dateDiff(rangeStart, day) / totalDays) * 100 }
  })
  const today = new Date(); today.setHours(12, 0, 0, 0)
  const todayLeft = (dateDiff(rangeStart, today) / totalDays) * 100
  return <div className="planner-timeline-scroll"><div className="planner-timeline" style={{ width }}><header>{ticks.map(({ day, left }) => <span key={day.toISOString()} style={{ left: `${left}%` }}>{scale === 'day' ? `${day.getMonth() + 1}/${day.getDate()}` : new Intl.DateTimeFormat('zh-CN', scale === 'quarter' ? { year: 'numeric', month: 'short' } : { month: 'short', day: 'numeric' }).format(day)}</span>)}</header><div className="planner-timeline-grid">{ticks.map(({ day, left }) => <i key={day.toISOString()} style={{ left: `${left}%` }} />)}{todayLeft >= 0 && todayLeft <= 100 ? <b className="planner-today-line" style={{ left: `${todayLeft}%` }}><em>今天</em></b> : null}</div>{rows.map((row) => {
    const start = parseDate(row.range.start)
    const end = parseDate(row.range.end || row.range.start)
    const left = start ? Math.max(0, (dateDiff(rangeStart, start) / totalDays) * 100) : 0
    const barWidth = start && end ? Math.max(row.data.is_milestone ? 0 : .65, ((dateDiff(start, end) + 1) / totalDays) * 100) : 0
    const progress = row.kind === 'task' ? row.data.progress_percent : row.data.progress_percent || 0
    return <div className={`planner-timeline-row planner-timeline-row--${row.kind} ${selectedTaskId === row.id ? 'is-selected' : ''}`} key={`${row.kind}-${row.id}`} onClick={() => row.kind === 'task' && onSelectTask(row.data)}>{start ? row.data.is_milestone ? <span className="planner-milestone" style={{ left: `${left}%` }}><Diamond size={15} fill="currentColor" /></span> : <span className={`planner-bar planner-bar--${row.kind}`} style={{ left: `${left}%`, width: `${barWidth}%` }}><i style={{ width: `${progress}%` }} />{row.kind === 'task' && barWidth > 5 ? <em>{progress}%</em> : null}</span> : <span className="planner-unscheduled-label">未排期</span>}{row.kind === 'task' && row.data.predecessor_ids?.length ? <Link2 className="planner-dependency-mark" size={13} /> : null}</div>
  })}</div></div>
}

function DesktopPlanner({ plan, rows, scale, setScale, selectedTaskId, onSelectTask, onEditPhase, onDeletePhase, onCreatePhase, onCreateTask }) {
  const dates = rows.flatMap((row) => [parseDate(row.range.start), parseDate(row.range.end)]).filter(Boolean)
  const today = new Date(); today.setHours(12, 0, 0, 0)
  const rangeStart = dates.length ? addDays(new Date(Math.min(...dates)), -2) : addDays(today, -7)
  const rangeEnd = dates.length ? addDays(new Date(Math.max(...dates)), 3) : addDays(today, 28)
  return <section className="planner-canvas"><div className="planner-canvas-toolbar"><div><button type="button" className="secondary-button" onClick={onCreatePhase}><Plus size={15} />新建阶段</button><button type="button" className="secondary-button" onClick={() => onCreateTask('')}><Plus size={15} />新建任务</button></div><div className="planner-scale" aria-label="时间刻度">{Object.entries(scaleMeta).map(([id, item]) => <button type="button" className={scale === id ? 'is-active' : ''} onClick={() => setScale(id)} key={id}>{item.label}</button>)}</div></div><div className="planner-grid"><div className="planner-hierarchy"><header><span>名称</span><span>状态</span></header>{rows.map((row) => <div className={`planner-hierarchy-row planner-hierarchy-row--${row.kind} ${selectedTaskId === row.id ? 'is-selected' : ''}`} key={`${row.kind}-${row.id}`}>
    <button type="button" className="planner-row-main" onClick={() => row.kind === 'task' ? onSelectTask(row.data) : null}>{row.kind === 'project' ? <FolderKanban size={16} /> : row.kind === 'phase' ? <Flag size={16} /> : row.kind === 'unphased' ? <ListTodo size={15} /> : row.data.is_milestone ? <Diamond size={14} /> : <span className="planner-task-indent" /> }<span><strong>{row.data.name || row.data.title}</strong>{row.kind === 'task' ? <small>{row.data.start_date || row.data.end_date ? `${formatDate(row.data.start_date || row.data.end_date)} — ${formatDate(row.data.end_date || row.data.start_date)}` : '尚未安排日期'}</small> : null}</span></button>
    {row.kind === 'phase' ? <span className="planner-row-actions"><button type="button" onClick={() => onCreateTask(row.id)} aria-label={`在${row.data.name}中新建任务`}><Plus size={14} /></button><button type="button" onClick={() => onEditPhase(row.data)} aria-label={`编辑${row.data.name}`}><Edit3 size={13} /></button><button type="button" onClick={() => onDeletePhase(row.data)} aria-label={`删除${row.data.name}`}><Trash2 size={13} /></button></span> : row.kind === 'task' ? <StatusBadge status={row.data.status} /> : <span className="planner-row-percent">{row.data.progress_percent || 0}%</span>}
  </div>)}</div><Timeline rows={rows} scale={scale} rangeStart={rangeStart} rangeEnd={rangeEnd} selectedTaskId={selectedTaskId} onSelectTask={onSelectTask} /></div></section>
}

function MobilePlanner({ plan, onSelectTask, onEditPhase, onDeletePhase, onCreateTask, onOpenTimeline }) {
  const [tab, setTab] = useState('phases')
  const activeTasks = plan.tasks.filter((item) => !item.deleted && item.status !== 'cancelled')
  const now = new Date()
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  const visiblePhases = plan.phases.filter((item) => !item.deleted)
  const todayTasks = activeTasks.filter((task) => taskRange(task).start === today || taskRange(task).end === today || (taskRange(task).start <= today && taskRange(task).end >= today))
  const backlog = activeTasks.filter((task) => !task.start_date && !task.end_date)
  return <section className="planner-mobile"><div className="planner-mobile-tabs"><button type="button" className={tab === 'phases' ? 'is-active' : ''} onClick={() => setTab('phases')}><Layers3 size={17} />阶段</button><button type="button" className={tab === 'today' ? 'is-active' : ''} onClick={() => setTab('today')}><CalendarDays size={17} />今日</button><button type="button" className={tab === 'backlog' ? 'is-active' : ''} onClick={() => setTab('backlog')}><ListTodo size={17} />未排期</button></div><div className="planner-mobile-tools"><span>本月</span><button type="button" className="secondary-button" onClick={onOpenTimeline}><Link2 size={15} />查看时间轴</button></div>
    {tab === 'phases' ? <div className="planner-phase-list">{visiblePhases.map((phase) => { const tasks = activeTasks.filter((item) => item.phase_id === phase.id); return <article key={phase.id}><header><span className="planner-phase-dot" /><div><strong>{phase.name}</strong><small>{phase.progress_percent}% · {tasks.length} 个任务</small></div><div className="planner-phase-mini"><i style={{ width: `${phase.progress_percent}%` }} /></div><button type="button" onClick={() => onCreateTask(phase.id)} aria-label={`在${phase.name}中新建任务`}><Plus size={18} /></button><button type="button" onClick={() => onEditPhase(phase)} aria-label={`编辑${phase.name}`}><MoreVertical size={18} /></button></header><div>{tasks.length ? tasks.map((task) => <button type="button" className="planner-mobile-task" onClick={() => onSelectTask(task)} key={task.id}><span><strong>{task.title}</strong><small><CalendarDays size={12} />{task.start_date || task.end_date ? `${formatDate(task.start_date || task.end_date)} — ${formatDate(task.end_date || task.start_date)}` : '未排期'}</small></span><StatusBadge status={task.status} /><em>{task.progress_percent}%</em><ChevronRight size={16} /></button>) : <button type="button" className="planner-phase-empty" onClick={() => onCreateTask(phase.id)}><Plus size={16} />添加这一阶段的第一个任务</button>}</div><footer><button type="button" onClick={() => onDeletePhase(phase)}><Trash2 size={14} />删除阶段</button></footer></article> })}</div> : <div className="planner-mobile-flat">{(tab === 'today' ? todayTasks : backlog).length ? (tab === 'today' ? todayTasks : backlog).map((task) => <button type="button" className="planner-mobile-task" onClick={() => onSelectTask(task)} key={task.id}><span><small className="planner-task-context">{task.project_name} ＞ {task.phase_name || '未分阶段'}</small><strong>{task.title}</strong><small>{task.start_date || task.end_date ? `${formatDate(task.start_date || task.end_date)} — ${formatDate(task.end_date || task.start_date)}` : '未排期'}</small></span><StatusBadge status={task.status} /><ChevronRight size={16} /></button>) : <div className="planner-mobile-empty"><Check size={21} /><strong>{tab === 'today' ? '今天没有项目任务' : '没有未排期任务'}</strong><p>{tab === 'today' ? '可以去阶段里安排任务日期。' : '所有任务都已经放进时间脉络。'}</p></div>}</div>}
  </section>
}

function MobileTimeline({ plan, onClose, onSelectTask }) {
  const phases = plan.phases.filter((item) => !item.deleted)
  const tasks = plan.tasks.filter((item) => !item.deleted && item.status !== 'cancelled')
  const allRange = rangeFromTasks(tasks)
  const start = parseDate(allRange.start) || addDays(new Date(), -7)
  const end = parseDate(allRange.end) || addDays(new Date(), 30)
  const total = Math.max(1, dateDiff(start, end) + 1)
  const ticks = timelineTicks(start, end)
  return <div className="mobile-timeline-overlay" role="dialog" aria-modal="true"><header><button type="button" onClick={onClose}><ArrowLeft size={21} />返回阶段</button><div><strong>项目时间轴</strong><small>{formatDate(start, true)} — {formatDate(end, true)}</small></div></header><div className="mobile-timeline-body"><div className="mobile-timeline-axis" aria-label="项目时间刻度"><span>任务时间</span><div>{ticks.map((tick) => <time dateTime={isoDate(tick)} key={tick.toISOString()}>{formatDate(tick)}</time>)}</div></div>{phases.map((phase) => { const phaseTasks = tasks.filter((task) => task.phase_id === phase.id); return <section key={phase.id}><h3>{phase.name}<span>{phase.progress_percent}%</span></h3>{phaseTasks.map((task) => { const range = taskRange(task); const taskStart = parseDate(range.start); const taskEnd = parseDate(range.end); const left = taskStart ? Math.max(0, dateDiff(start, taskStart) / total * 100) : 0; const width = taskStart && taskEnd ? Math.max(3, (dateDiff(taskStart, taskEnd) + 1) / total * 100) : 0; return <button type="button" onClick={() => { onClose(); onSelectTask(task) }} key={task.id}><span><strong>{task.title}</strong><small>{taskStart ? `${formatDate(range.start)} — ${formatDate(range.end)}` : '未排期'}</small></span><i>{taskStart ? <b style={{ marginLeft: `${left}%`, width: `${width}%` }}><em style={{ width: `${task.progress_percent}%` }} /></b> : <small>未排期</small>}</i></button> })}</section> })}</div></div>
}

export function ProjectPlannerDetail({ initialProjectId, onBack, onDashboardReload, onToast }) {
  const initialScale = new URLSearchParams(window.location.search).get('scale')
  const [projects, setProjects] = useState([])
  const [selectedProjectId, setSelectedProjectId] = useState(initialProjectId || '')
  const [plan, setPlan] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [scale, setScale] = useState(scaleMeta[initialScale] ? initialScale : 'week')
  const [form, setForm] = useState(null)
  const [confirm, setConfirm] = useState(null)
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState('')
  const [recycleOpen, setRecycleOpen] = useState(false)
  const [recyclePlan, setRecyclePlan] = useState(null)
  const [recycleBusyId, setRecycleBusyId] = useState('')
  const [timelineOpen, setTimelineOpen] = useState(false)

  const loadProjects = useCallback(async (preferredId = '') => {
    const records = await api.projects(true)
    setProjects(records)
    const active = records.filter((item) => !item.deleted)
    const nextId = preferredId && active.some((item) => item.id === preferredId) ? preferredId : active[0]?.id || ''
    setSelectedProjectId(nextId)
    return nextId
  }, [])

  const loadPlan = useCallback(async (projectId) => {
    if (!projectId) { setPlan(null); return }
    setPlan(await api.projectPlan(projectId))
  }, [])

  const refresh = useCallback(async (preferredId = selectedProjectId) => {
    setError('')
    try {
      const records = await api.projects(true)
      const active = records.filter((item) => !item.deleted)
      const nextId = preferredId && active.some((item) => item.id === preferredId) ? preferredId : active[0]?.id || ''
      const nextPlan = nextId ? await api.projectPlan(nextId) : null
      setProjects(records)
      setSelectedProjectId(nextId)
      setPlan(nextPlan)
      await onDashboardReload?.()
    } catch (requestError) {
      setError(requestError.message)
    }
  }, [onDashboardReload, selectedProjectId])

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        const nextId = await loadProjects(initialProjectId)
        if (active) await loadPlan(nextId)
      } catch (requestError) {
        if (active) setError(requestError.message)
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => { active = false }
  }, [initialProjectId, loadPlan, loadProjects])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    params.set('detail', 'project-plan')
    if (selectedProjectId) params.set('project', selectedProjectId)
    params.set('scale', scale)
    window.history.replaceState({ detail: 'project-plan', project: selectedProjectId }, '', `${window.location.pathname}?${params.toString()}`)
  }, [scale, selectedProjectId])

  const rows = useMemo(() => buildPlannerRows(plan), [plan])
  const activeProjects = projects.filter((item) => !item.deleted)

  async function selectProject(id) {
    setSelectedProjectId(id)
    setLoading(true)
    setError('')
    try { await loadPlan(id) } catch (requestError) { setError(requestError.message) } finally { setLoading(false) }
  }

  async function submitForm(payload) {
    setBusy(true); setFormError('')
    try {
      if (form.type === 'project') {
        const saved = form.item ? await api.updateProject(form.item.id, payload) : await api.createProject(payload)
        setForm(null); await refresh(saved.id); onToast?.(form.item ? '项目已更新' : '项目已创建')
      } else if (form.type === 'phase') {
        if (form.item) await api.updateProjectPhase(form.item.id, payload)
        else await api.createProjectPhase(selectedProjectId, payload)
        setForm(null); await refresh(); onToast?.(form.item ? '阶段已更新' : '阶段已创建')
      } else if (form.type === 'task') {
        const taskPayload = { ...payload, project_id: selectedProjectId }
        if (form.item) await api.updateTask(form.item.id, taskPayload)
        else await api.createTask(taskPayload)
        setForm(null); await refresh(); onToast?.(form.item ? '任务已更新' : '任务已创建')
      }
    } catch (requestError) { setFormError(requestError.message) } finally { setBusy(false) }
  }

  async function confirmDelete() {
    setBusy(true)
    try {
      if (confirm.type === 'project') { await api.deleteProject(confirm.item.id); setConfirm(null); await refresh(''); onToast?.('项目已移入回收站') }
      if (confirm.type === 'phase') { await api.deleteProjectPhase(confirm.item.id); setConfirm(null); await refresh(); onToast?.('阶段已移入回收站') }
      if (confirm.type === 'task') { await api.deleteTask(confirm.item.id); setConfirm(null); setForm(null); await refresh(); onToast?.('任务已移入回收站') }
    } catch (requestError) { setFormError(requestError.message) } finally { setBusy(false) }
  }

  async function openRecycle() {
    setRecycleOpen(true); setFormError('')
    try { setRecyclePlan(selectedProjectId ? await api.projectPlan(selectedProjectId, true) : null) }
    catch (requestError) { setFormError(requestError.message) }
  }

  async function restore(kind, item) {
    setRecycleBusyId(item.id); setFormError('')
    try {
      if (kind === 'project') await api.restoreProject(item.id)
      if (kind === 'phase') await api.restoreProjectPhase(item.id)
      if (kind === 'task') await api.restoreTask(item.id)
      const preferred = kind === 'project' ? item.id : selectedProjectId
      await refresh(preferred)
      setRecyclePlan(preferred ? await api.projectPlan(preferred, true) : null)
      onToast?.('已从回收站恢复')
    } catch (requestError) { setFormError(requestError.message) } finally { setRecycleBusyId('') }
  }

  function leavePlanner() {
    const params = new URLSearchParams(window.location.search)
    ;['detail', 'project', 'scale'].forEach((key) => params.delete(key))
    window.history.replaceState({}, '', `${window.location.pathname}${params.size ? `?${params.toString()}` : ''}`)
    onBack()
  }

  if (loading && !plan) return <div className="screen-state"><LoaderCircle className="spin" size={28} /><span>正在展开项目全景…</span></div>

  return <div className="project-planner-page"><header className="planner-hero"><div className="planner-hero-top"><button type="button" className="planner-back" onClick={leavePlanner}><ArrowLeft size={18} />返回首页</button><div className="planner-hero-actions"><button type="button" className="secondary-button" onClick={openRecycle}><Trash2 size={15} />回收站</button><button type="button" className="primary-button" onClick={() => { setFormError(''); setForm({ type: 'project', item: null }) }}><Plus size={16} />新建项目</button></div></div><div className="planner-title-row"><div><h1>项目全景</h1><p>从目标看到阶段，也看到今天该做什么。</p></div>{activeProjects.length ? <label className="planner-project-switch"><span>项目</span><select value={selectedProjectId} onChange={(event) => selectProject(event.target.value)}>{activeProjects.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label> : null}</div></header>

    {!plan ? <section className="planner-empty"><FolderKanban size={32} /><h2>还没有项目</h2><p>新建项目后，可以继续拆成阶段和任务；AI Agent 也会使用同一套结构。</p><button type="button" className="primary-button" onClick={() => setForm({ type: 'project', item: null })}><Plus size={16} />新建第一个项目</button></section> : <><div className="planner-project-actions"><div><StatusBadge status={plan.project.status} /><span>{plan.project.description || '还没有填写项目说明'}</span></div><button type="button" onClick={() => { setFormError(''); setForm({ type: 'project', item: plan.project }) }}><Edit3 size={15} />编辑项目</button><button type="button" className="is-danger" onClick={() => setConfirm({ type: 'project', item: plan.project })}><Trash2 size={15} />删除项目</button></div><PlannerSummary project={plan.project} /><DesktopPlanner plan={plan} rows={rows} scale={scale} setScale={setScale} selectedTaskId={form?.type === 'task' ? form.item?.id : ''} onSelectTask={(task) => { setFormError(''); setForm({ type: 'task', item: task }) }} onEditPhase={(phase) => { setFormError(''); setForm({ type: 'phase', item: phase }) }} onDeletePhase={(phase) => setConfirm({ type: 'phase', item: phase })} onCreatePhase={() => { setFormError(''); setForm({ type: 'phase', item: null }) }} onCreateTask={(phaseId) => { setFormError(''); setForm({ type: 'task', item: null, phaseId }) }} /><MobilePlanner plan={plan} onSelectTask={(task) => { setFormError(''); setForm({ type: 'task', item: task }) }} onEditPhase={(phase) => { setFormError(''); setForm({ type: 'phase', item: phase }) }} onDeletePhase={(phase) => setConfirm({ type: 'phase', item: phase })} onCreateTask={(phaseId) => { setFormError(''); setForm({ type: 'task', item: null, phaseId }) }} onOpenTimeline={() => setTimelineOpen(true)} />{timelineOpen ? <MobileTimeline plan={plan} onClose={() => setTimelineOpen(false)} onSelectTask={(task) => setForm({ type: 'task', item: task })} /> : null}</>}

    {error ? <div className="inline-error">{error}</div> : null}
    {form?.type === 'project' ? <ProjectForm project={form.item} busy={busy} error={formError} onClose={() => setForm(null)} onSubmit={submitForm} /> : null}
    {form?.type === 'phase' ? <PhaseForm phase={form.item} nextOrder={(plan?.phases?.length || 0) * 10} busy={busy} error={formError} onClose={() => setForm(null)} onSubmit={submitForm} /> : null}
    {form?.type === 'task' ? <TaskForm task={form.item} projectName={plan?.project?.name} phases={plan?.phases || []} tasks={plan?.tasks || []} defaultPhaseId={form.phaseId} busy={busy} error={formError} onClose={() => setForm(null)} onSubmit={submitForm} onDelete={() => setConfirm({ type: 'task', item: form.item })} /> : null}
    {confirm ? <ConfirmDialog title={`删除${confirm.type === 'project' ? '项目' : confirm.type === 'phase' ? '阶段' : '任务'}“${confirm.item.name || confirm.item.title}”？`} description={confirm.type === 'project' ? '该项目下的阶段与任务会暂时从日历和首页隐藏。' : confirm.type === 'phase' ? '该阶段下的任务会暂时隐藏，恢复阶段后重新出现。' : '这项任务会从项目全景和今日任务中隐藏。'} busy={busy} onCancel={() => setConfirm(null)} onConfirm={confirmDelete} /> : null}
    {recycleOpen ? <RecycleDialog projects={projects} plan={recyclePlan} busyId={recycleBusyId} error={formError} onClose={() => setRecycleOpen(false)} onRestoreProject={(item) => restore('project', item)} onRestorePhase={(item) => restore('phase', item)} onRestoreTask={(item) => restore('task', item)} /> : null}
  </div>
}
