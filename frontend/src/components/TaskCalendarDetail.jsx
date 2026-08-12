import {
  ArrowLeft,
  CalendarDays,
  Check,
  ChevronLeft,
  ChevronRight,
  CirclePlus,
  ExternalLink,
  LoaderCircle,
  Pencil,
  RefreshCw,
  Repeat2,
  RotateCcw,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'

const quadrants = [
  ['important_urgent', '重要且紧急'],
  ['important_not_urgent', '重要不紧急'],
  ['not_important_urgent', '不重要但紧急'],
  ['not_important_not_urgent', '不重要不紧急'],
]
const quadrantLabels = Object.fromEntries(quadrants)
const weekNames = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

function localISO(value) {
  const target = new Date(value)
  const year = target.getFullYear()
  const month = String(target.getMonth() + 1).padStart(2, '0')
  const day = String(target.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function fromISO(value) { return new Date(`${value}T12:00:00`) }
function addDays(value, amount) { const next = new Date(value); next.setDate(next.getDate() + amount); return next }
function startOfWeek(value) { const target = new Date(value); const offset = (target.getDay() + 6) % 7; return addDays(target, -offset) }
function endOfWeek(value) { return addDays(startOfWeek(value), 6) }

function visibleRange(anchor, view) {
  const year = anchor.getFullYear()
  if (view === 'year') return { start: new Date(year, 0, 1, 12), end: new Date(year, 11, 31, 12) }
  if (view === 'week') return { start: startOfWeek(anchor), end: endOfWeek(anchor) }
  const first = new Date(year, anchor.getMonth(), 1, 12)
  const last = new Date(year, anchor.getMonth() + 1, 0, 12)
  return { start: startOfWeek(first), end: endOfWeek(last) }
}

function shiftAnchor(anchor, view, direction) {
  const next = new Date(anchor)
  if (view === 'year') next.setFullYear(next.getFullYear() + direction)
  else if (view === 'week') next.setDate(next.getDate() + direction * 7)
  else next.setMonth(next.getMonth() + direction)
  return next
}

function pageTitle(anchor, view) {
  if (view === 'year') return `${anchor.getFullYear()}年`
  if (view === 'week') {
    const start = startOfWeek(anchor); const end = endOfWeek(anchor)
    return `${start.getMonth() + 1}月${start.getDate()}日—${end.getMonth() + 1}月${end.getDate()}日`
  }
  return `${anchor.getFullYear()}年${anchor.getMonth() + 1}月`
}

function taskDateTime(task) {
  const raw = String(task?.base_due_at || task?.due_at || '')
  return { date: raw.slice(0, 10), time: raw.includes('T') ? raw.slice(11, 16) : '09:00' }
}

function annotationLabels(day) {
  if (!day) return []
  return [
    ...(day.traditional_festivals || []).map((label) => ({ label, kind: 'festival' })),
    ...(day.solar_term ? [{ label: day.solar_term, kind: 'solar-term' }] : []),
    ...(day.official_holiday ? [{ label: day.official_holiday.label, kind: day.official_holiday.kind }] : []),
  ]
}

function DayAnnotations({ day, compact = false, limit = compact ? 1 : 3 }) {
  const labels = annotationLabels(day)
  if (!labels.length) return compact ? <span className="lunar-caption">{day.lunar_text}</span> : null
  const visible = labels.length > limit
    ? [...labels.slice(0, Math.max(0, limit - 1)), { label: `+${labels.length - limit + 1}`, kind: 'more' }]
    : labels.slice(0, limit)
  return <div className="calendar-annotations">{visible.map((item) => <span className={`calendar-label calendar-label--${item.kind}`} key={`${item.kind}-${item.label}`}>{item.label}</span>)}</div>
}

function TaskEvent({ task, compact = false, onEdit, onToggle }) {
  return <article className={`calendar-task calendar-task--${task.quadrant} ${task.done ? 'is-done' : ''}`}>
    <button type="button" className="calendar-task__check" onClick={(event) => { event.stopPropagation(); onToggle(task) }} aria-label={task.done ? '重新打开任务' : '完成任务'}><Check size={11} /></button>
    <button type="button" className="calendar-task__title" onClick={(event) => { event.stopPropagation(); onEdit(task) }}>{task.recurrence === 'yearly' ? <Repeat2 size={11} /> : null}<span>{task.title}</span>{compact ? null : <Pencil size={10} />}</button>
  </article>
}

function MonthView({ anchor, days, tasksByDate, onSelect, onEdit, onToggle }) {
  const range = visibleRange(anchor, 'month')
  const dates = []
  for (let cursor = range.start; cursor <= range.end; cursor = addDays(cursor, 1)) dates.push(new Date(cursor))
  return <div className="month-calendar">
    <div className="month-weekdays">{weekNames.map((name) => <span key={name}>{name}</span>)}</div>
    <div className="month-grid">{dates.map((value) => {
      const key = localISO(value); const day = days.get(key); const tasks = tasksByDate.get(key) || []
      const outside = value.getMonth() !== anchor.getMonth(); const today = key === localISO(new Date())
      return <section className={`calendar-day ${outside ? 'is-outside' : ''} ${today ? 'is-today' : ''} ${day?.official_holiday?.is_day_off ? 'is-day-off' : ''}`} key={key} onClick={() => onSelect(key)} onKeyDown={(event) => { if (event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) onSelect(key) }} role="button" tabIndex="0" aria-label={`查看${value.getMonth() + 1}月${value.getDate()}日完整信息`}>
        <header><strong>{value.getDate()}</strong><span>{day?.lunar_text}</span></header>
        <DayAnnotations day={day} limit={2} />
        <div className="calendar-day__tasks">{tasks.slice(0, 3).map((task) => <TaskEvent key={task.event_id} task={task} onEdit={onEdit} onToggle={onToggle} />)}{tasks.length > 3 ? <span className="more-events">还有 {tasks.length - 3} 项</span> : null}</div>
      </section>
    })}</div>
  </div>
}

function WeekView({ anchor, days, tasksByDate, onAdd, onEdit, onToggle }) {
  const start = startOfWeek(anchor)
  const dates = Array.from({ length: 7 }, (_, index) => addDays(start, index))
  return <div className="week-calendar">{dates.map((value, index) => {
    const key = localISO(value); const day = days.get(key); const tasks = tasksByDate.get(key) || []
    return <section className={key === localISO(new Date()) ? 'is-today' : ''} key={key}>
      <header><span>{weekNames[index]}</span><strong>{value.getMonth() + 1}月{value.getDate()}日</strong><small>{day?.lunar_text}</small></header>
      <DayAnnotations day={day} />
      <div className="week-calendar__tasks">{tasks.length ? tasks.map((task) => <TaskEvent key={task.event_id} task={task} onEdit={onEdit} onToggle={onToggle} />) : <button type="button" className="empty-day-action" onClick={() => onAdd(key)}><CirclePlus size={14} />添加安排</button>}</div>
      {tasks.length ? <button type="button" className="add-day-task" onClick={() => onAdd(key)}><CirclePlus size={13} />再添加</button> : null}
    </section>
  })}</div>
}

function MiniMonth({ year, month, days, tasksByDate, onSelect }) {
  const first = new Date(year, month, 1, 12); const start = startOfWeek(first)
  const dates = Array.from({ length: 42 }, (_, index) => addDays(start, index))
  return <article className="mini-month"><header><strong>{month + 1}月</strong></header><div className="mini-weekdays">{weekNames.map((name) => <span key={name}>{name.slice(1)}</span>)}</div><div className="mini-month-grid">{dates.map((value) => {
    const key = localISO(value); const day = days.get(key); const tasks = tasksByDate.get(key) || []
    return <button type="button" key={key} className={`${value.getMonth() !== month ? 'is-outside' : ''} ${key === localISO(new Date()) ? 'is-today' : ''} ${day?.official_holiday?.is_day_off ? 'is-day-off' : ''}`} onClick={() => onSelect(value)}><span>{value.getDate()}</span>{tasks.length ? <i /> : null}{(day?.traditional_festivals?.length || day?.solar_term) ? <em /> : null}</button>
  })}</div></article>
}

function YearView({ anchor, days, tasksByDate, onSelect }) {
  return <div className="year-calendar">{Array.from({ length: 12 }, (_, month) => <MiniMonth key={month} year={anchor.getFullYear()} month={month} days={days} tasksByDate={tasksByDate} onSelect={onSelect} />)}</div>
}

function DateDetailDialog({ dateValue, day, tasks, onClose, onAdd, onEdit, onToggle }) {
  const date = fromISO(dateValue)
  const labels = annotationLabels(day)
  const weekday = new Intl.DateTimeFormat('zh-CN', { weekday: 'long' }).format(date)
  return <div className="dialog-backdrop" role="presentation"><section className="record-dialog day-detail-dialog" role="dialog" aria-modal="true" aria-labelledby="day-detail-title">
    <header><div><span className="eyebrow">DAY DETAILS</span><h2 id="day-detail-title">{date.getMonth() + 1}月{date.getDate()}日 · {weekday}</h2><p>{day?.lunar_text || '农历信息加载中'}</p></div><button type="button" onClick={onClose} aria-label="关闭"><X size={19} /></button></header>
    <div className="day-detail-body">
      <section className="day-detail-annotations" aria-label="当天节日与假期信息">{labels.length ? labels.map((item) => <article className={`day-detail-label day-detail-label--${item.kind}`} key={`${item.kind}-${item.label}`}><strong>{item.label}</strong><span>{item.kind === 'festival' ? '传统节日' : item.kind === 'solar-term' ? '二十四节气' : item.kind === 'public_holiday' ? '法定放假' : '调休上班'}</span></article>) : <p>当天没有节日、节气或法定假期标签。</p>}</section>
      <section className="day-detail-tasks"><div className="day-detail-heading"><div><span className="eyebrow">SCHEDULE</span><h3>当天安排</h3></div><span>{tasks.length} 项</span></div>{tasks.length ? tasks.map((task) => {
        const timing = taskDateTime(task)
        return <article className={task.done ? 'is-done' : ''} key={task.event_id}><button type="button" className="day-detail-task-check" onClick={() => onToggle(task)} aria-label={task.done ? '重新打开任务' : '完成任务'}><Check size={13} /></button><button type="button" className="day-detail-task-main" onClick={() => onEdit(task)}><strong>{task.title}</strong><span>{timing.time} · {quadrantLabels[task.quadrant] || '未分类'}{task.recurrence === 'yearly' ? ' · 每年重复' : ''}</span>{task.note ? <small>{task.note}</small> : null}</button><Pencil size={14} /></article>
      }) : <div className="day-detail-empty"><CalendarDays size={20} /><p>当天还没有安排。</p></div>}</section>
      <button type="button" className="primary-button day-detail-add" onClick={() => onAdd(dateValue)}><CirclePlus size={16} />添加当天安排</button>
    </div>
  </section></div>
}

function TaskDialog({ task, selectedDate, busy, error, onClose, onSave, onDelete }) {
  const initial = taskDateTime(task)
  return <div className="dialog-backdrop" role="presentation"><section className="record-dialog task-editor-dialog" role="dialog" aria-modal="true" aria-labelledby="task-editor-title">
    <header><div><span className="eyebrow">LONG-TERM PLAN</span><h2 id="task-editor-title">{task ? '修改安排' : '添加安排'}</h2></div><button type="button" onClick={onClose} aria-label="关闭"><X size={19} /></button></header>
    <form onSubmit={(event) => { event.preventDefault(); const form = new FormData(event.currentTarget); const date = form.get('due_date'); const time = form.get('due_time') || '09:00'; onSave({ title: form.get('title'), quadrant: form.get('quadrant'), due_at: date ? `${date}T${time}:00` : null, recurrence: form.get('recurrence'), note: form.get('note') }) }}>
      <label><span>安排内容</span><input name="title" defaultValue={task?.title || ''} placeholder="例如：小雅生日，准备礼物" maxLength="160" required autoFocus /></label>
      <div className="form-columns"><label><span>日期</span><input type="date" name="due_date" defaultValue={initial.date || selectedDate || localISO(new Date())} required /></label><label><span>时间</span><input type="time" name="due_time" defaultValue={initial.time} /></label></div>
      <div className="form-columns"><label><span>重要程度</span><select name="quadrant" defaultValue={task?.quadrant || 'important_not_urgent'}>{quadrants.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label><span>重复方式</span><select name="recurrence" defaultValue={task?.recurrence || 'none'}><option value="none">仅这一次</option><option value="yearly">每年这一天</option></select></label></div>
      <label><span>备注</span><textarea name="note" defaultValue={task?.note || ''} placeholder="准备事项、地址或想让 AI Agent 记住的背景" rows="3" /></label>
      {task?.recurrence === 'yearly' ? <p className="dialog-helper"><Repeat2 size={13} />这是每年固定出现的安排，完成本次不会影响下一年。</p> : null}
      {error ? <p className="form-error">{error}</p> : null}
      <div className="dialog-actions task-dialog-actions">{task ? <button type="button" className="text-danger-button" onClick={onDelete}><Trash2 size={14} />移入回收站</button> : <span />}<button type="button" className="secondary-button" onClick={onClose}>取消</button><button type="submit" className="primary-button" disabled={busy}>{busy ? '正在保存…' : '保存安排'}</button></div>
    </form>
  </section></div>
}

function TaskDeleteConfirm({ task, busy, error, onCancel, onConfirm }) {
  return <div className="dialog-backdrop" role="presentation"><section className="record-dialog confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="task-delete-title">
    <header><div><span className="eyebrow">CONFIRM</span><h2 id="task-delete-title">删除“{task.title}”？</h2></div><button type="button" onClick={onCancel} aria-label="关闭"><X size={19} /></button></header>
    <div className="confirm-dialog-body"><p>删除后任务会进入回收站，可以随时恢复，不会立即永久清除。</p>{error ? <p className="form-error">{error}</p> : null}<div className="dialog-actions"><button type="button" className="secondary-button" onClick={onCancel}>取消</button><button type="button" className="primary-button is-danger" disabled={busy} onClick={onConfirm}>{busy ? '正在删除…' : '确认删除'}</button></div></div>
  </section></div>
}

function TaskRecycleDialog({ tasks, loading, busyId, error, onClose, onRestore }) {
  return <div className="dialog-backdrop" role="presentation"><section className="record-dialog recycle-dialog" role="dialog" aria-modal="true" aria-labelledby="task-trash-title"><header><div><span className="eyebrow">RECYCLE BIN</span><h2 id="task-trash-title">任务回收站</h2></div><button type="button" onClick={onClose} aria-label="关闭"><X size={19} /></button></header><div className="recycle-dialog__body">{loading ? <div className="detail-state"><LoaderCircle className="spin" size={22} />正在读取…</div> : tasks.length ? tasks.map((task) => <article key={task.id}><div><b>{task.title}</b><span>{String(task.due_at || '未指定日期').slice(0, 10)} · {task.recurrence === 'yearly' ? '每年重复' : task.quadrant_label}</span></div><button type="button" className="secondary-button" disabled={busyId === task.id} onClick={() => onRestore(task)}><RotateCcw size={14} />{busyId === task.id ? '恢复中' : '恢复'}</button></article>) : <div className="health-empty"><Trash2 size={24} /><h3>回收站是空的</h3><p>删除的任务会安全保留在这里。</p></div>}{error ? <p className="form-error">{error}</p> : null}</div></section></div>
}

export function TaskCalendarDetail({ initialTask = null, onBack, onDashboardReload, onToast }) {
  const [view, setView] = useState('month')
  const [anchor, setAnchor] = useState(() => taskDateTime(initialTask).date ? fromISO(taskDateTime(initialTask).date) : new Date())
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectedDate, setSelectedDate] = useState(() => taskDateTime(initialTask).date)
  const [detailDate, setDetailDate] = useState('')
  const [editingTask, setEditingTask] = useState(initialTask)
  const [deletingTask, setDeletingTask] = useState(null)
  const [busy, setBusy] = useState(false)
  const [dialogError, setDialogError] = useState('')
  const [trashOpen, setTrashOpen] = useState(false)
  const [trashTasks, setTrashTasks] = useState([])
  const [trashLoading, setTrashLoading] = useState(false)
  const [busyId, setBusyId] = useState('')
  const range = useMemo(() => visibleRange(anchor, view), [anchor, view])

  const load = useCallback(async ({ quiet = false } = {}) => {
    if (!quiet) setLoading(true)
    try { setData(await api.calendar(localISO(range.start), localISO(range.end))); setError('') }
    catch (requestError) { setError(requestError.message) }
    finally { if (!quiet) setLoading(false) }
  }, [range.start.getTime(), range.end.getTime()])

  useEffect(() => { load() }, [load])
  const days = useMemo(() => new Map((data?.days || []).map((day) => [day.date, day])), [data])
  const tasksByDate = useMemo(() => { const result = new Map(); for (const task of data?.tasks || []) { const list = result.get(task.occurrence_date) || []; list.push(task); result.set(task.occurrence_date, list) } return result }, [data])

  function selectDate(dateValue) { setDialogError(''); setDetailDate(dateValue) }
  function addTask(dateValue) { setDialogError(''); setDetailDate(''); setSelectedDate(dateValue); setEditingTask(null) }
  function editTask(task) { setDialogError(''); setDetailDate(''); setSelectedDate(task.occurrence_date); setEditingTask(task) }

  async function saveTask(payload) {
    setBusy(true); setDialogError('')
    try {
      if (editingTask) await api.updateTask(editingTask.id, payload)
      else await api.createTask(payload)
      setEditingTask(null); setSelectedDate(''); await Promise.all([load({ quiet: true }), onDashboardReload?.()])
      onToast?.(editingTask ? '任务已更新' : '任务已创建')
    } catch (requestError) { setDialogError(requestError.message) }
    finally { setBusy(false) }
  }

  async function toggleTask(task) {
    const nextDone = !task.done
    const occurrence = task.recurrence === 'yearly' ? { occurrence_date: task.occurrence_date } : {}
    try {
      await api.updateTask(task.id, { done: nextDone, ...occurrence })
      await Promise.all([load({ quiet: true }), onDashboardReload?.()])
      onToast?.({
        message: nextDone ? `已完成“${task.title}”` : `已将“${task.title}”恢复为待处理`,
        actionLabel: '撤销',
        onAction: async () => {
          await api.updateTask(task.id, { done: task.done, ...occurrence })
          await Promise.all([load({ quiet: true }), onDashboardReload?.()])
          onToast?.('操作已撤销')
        },
      })
    }
    catch (requestError) { setError(requestError.message) }
  }

  async function deleteTask() {
    setBusy(true); setDialogError('')
    const target = deletingTask || editingTask
    try {
      await api.deleteTask(target.id)
      setDeletingTask(null); setEditingTask(null); setSelectedDate('')
      await Promise.all([load({ quiet: true }), onDashboardReload?.()])
      onToast?.({
        message: `“${target.title}”已移入回收站`,
        actionLabel: '撤销删除',
        onAction: async () => {
          await api.restoreTask(target.id)
          await Promise.all([load({ quiet: true }), onDashboardReload?.()])
          onToast?.('任务已恢复')
        },
      })
    }
    catch (requestError) { setDialogError(requestError.message) }
    finally { setBusy(false) }
  }

  async function openTrash() {
    setTrashOpen(true); setTrashLoading(true); setDialogError('')
    try { setTrashTasks(await api.deletedTasks()) }
    catch (requestError) { setDialogError(requestError.message) }
    finally { setTrashLoading(false) }
  }

  async function restoreTask(task) {
    setBusyId(task.id); setDialogError('')
    try { await api.restoreTask(task.id); setTrashTasks((current) => current.filter((item) => item.id !== task.id)); await Promise.all([load({ quiet: true }), onDashboardReload?.()]); onToast?.('任务已恢复') }
    catch (requestError) { setDialogError(requestError.message) }
    finally { setBusyId('') }
  }

  if (loading && !data) return <div className="detail-state"><LoaderCircle className="spin" size={28} />正在整理日历…</div>
  if (error && !data) return <div className="detail-state is-error"><p>{error}</p><button type="button" className="secondary-button" onClick={() => load()}><RefreshCw size={16} />重新加载</button></div>

  return <div className="detail-page task-calendar-page">
    <header className="detail-toolbar"><button type="button" onClick={onBack}><ArrowLeft size={18} />返回工作台</button><div><button type="button" className="secondary-button" onClick={openTrash}><Trash2 size={15} />回收站</button><button type="button" className="primary-button" onClick={() => addTask(localISO(new Date()))}><CirclePlus size={16} />添加安排</button></div></header>
    <section className="calendar-hero"><div><span className="eyebrow">CALENDAR & PLANS</span><h1>长期计划</h1><p>按年、月、周安排重要事项；生日和纪念日可以设为每年重复。</p></div><div className="calendar-view-tabs" aria-label="日历视图">{[['year', '年'], ['month', '月'], ['week', '周']].map(([value, label]) => <button type="button" key={value} className={view === value ? 'is-active' : ''} aria-pressed={view === value} onClick={() => setView(value)}>{label}</button>)}</div></section>
    <section className="calendar-panel"><header className="calendar-navigation"><button type="button" onClick={() => setAnchor((current) => shiftAnchor(current, view, -1))} aria-label="上一个周期"><ChevronLeft size={18} /></button><div><h2>{pageTitle(anchor, view)}</h2><button type="button" onClick={() => setAnchor(new Date())}>回到今天</button></div><button type="button" onClick={() => setAnchor((current) => shiftAnchor(current, view, 1))} aria-label="下一个周期"><ChevronRight size={18} /></button></header>
      {view === 'month' ? <MonthView anchor={anchor} days={days} tasksByDate={tasksByDate} onSelect={selectDate} onEdit={editTask} onToggle={toggleTask} /> : view === 'week' ? <WeekView anchor={anchor} days={days} tasksByDate={tasksByDate} onAdd={addTask} onEdit={editTask} onToggle={toggleTask} /> : <YearView anchor={anchor} days={days} tasksByDate={tasksByDate} onSelect={(value) => { setAnchor(value); setView('month') }} />}
    </section>
    {data?.undated_tasks?.length ? <section className="calendar-backlog"><div><CalendarDays size={17} /><span><b>未指定日期</b><small>这些任务仍会保留在今日任务里</small></span></div>{data.undated_tasks.map((task) => <button type="button" key={task.id} onClick={() => editTask(task)}>{task.title}<Pencil size={13} /></button>)}</section> : null}
    <section className="holiday-source"><Sparkles size={17} /><div><b>中国日历说明</b><p>传统节日和二十四节气由本地历法计算；法定放假与调休按国务院办公厅逐年公布的数据展示。</p>{data?.holiday_notices?.map((notice) => notice.status === 'official' ? <a key={notice.year} href={notice.url} target="_blank" rel="noreferrer">{notice.year}年官方安排 · {notice.document_number}<ExternalLink size={12} /></a> : <span key={notice.year}>{notice.title}</span>)}</div></section>
    {error ? <div className="inline-error">实时更新暂时中断：{error}</div> : null}
    {detailDate ? <DateDetailDialog dateValue={detailDate} day={days.get(detailDate)} tasks={tasksByDate.get(detailDate) || []} onClose={() => setDetailDate('')} onAdd={addTask} onEdit={editTask} onToggle={toggleTask} /> : null}
    {(selectedDate || editingTask) ? <TaskDialog task={editingTask} selectedDate={selectedDate} busy={busy} error={dialogError} onClose={() => { setEditingTask(null); setSelectedDate('') }} onSave={saveTask} onDelete={() => setDeletingTask(editingTask)} /> : null}
    {deletingTask ? <TaskDeleteConfirm task={deletingTask} busy={busy} error={dialogError} onCancel={() => setDeletingTask(null)} onConfirm={deleteTask} /> : null}
    {trashOpen ? <TaskRecycleDialog tasks={trashTasks} loading={trashLoading} busyId={busyId} error={dialogError} onClose={() => setTrashOpen(false)} onRestore={restoreTask} /> : null}
  </div>
}
