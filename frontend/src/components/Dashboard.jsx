import {
  BookOpen,
  BrainCircuit,
  Camera,
  Check,
  CheckSquare2,
  ChevronRight,
  Dumbbell,
  Flame,
  Flag,
  GlassWater,
  HeartPulse,
  Lightbulb,
  LoaderCircle,
  Newspaper,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Scale,
  Settings2,
  Sparkles,
  Trash2,
  Upload,
  Utensils,
  Video,
  Weight,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { api } from '../api.js'
import { SystemPanel } from './SystemPanel.jsx'

const quadrantMeta = {
  important_urgent: { title: '重要 · 紧急', tone: 'urgent', hint: '优先完成' },
  important_not_urgent: { title: '重要 · 不紧急', tone: 'important', hint: '安排时间' },
  not_important_urgent: { title: '不重要 · 紧急', tone: 'delegable', hint: '尽快处理' },
  not_important_not_urgent: { title: '不重要 · 不紧急', tone: 'later', hint: '有空再做' },
}

const taskStatusMeta = {
  planned: { label: '待处理', tone: 'planned' },
  in_progress: { label: '进行中', tone: 'active' },
  blocked: { label: '受阻', tone: 'blocked' },
  completed: { label: '已完成', tone: 'completed' },
  cancelled: { label: '已取消', tone: 'cancelled' },
}

function taskStatus(task) {
  return taskStatusMeta[task.done ? 'completed' : task.status] || taskStatusMeta.planned
}

function Greeting({ date, profile, greeting, onSettings }) {
  const hour = new Date().getHours()
  const phrase = hour < 11 ? '上午好' : hour < 13 ? '中午好' : hour < 18 ? '下午好' : '晚上好'
  const displayDate = new Intl.DateTimeFormat('zh-CN', {
    month: 'long', day: 'numeric', weekday: 'long',
  }).format(date ? new Date(`${date}T12:00:00`) : new Date())
  return (
    <header className="greeting">
      <div>
        <span className="eyebrow">{displayDate}</span>
        <h1>{phrase}，{profile?.nickname || '朋友'}</h1>
        <p>{greeting?.message || '今天不用一次做好所有事，先把眼前这一件放稳。'}</p>
      </div>
      <button type="button" className="greeting__seal" onClick={() => onSettings('profile')} aria-label="设置称呼与寄语"><Sparkles size={24} /></button>
    </header>
  )
}

function QuickActions({ onAction }) {
  const actions = [
    { id: 'task', label: '添加任务', icon: CheckSquare2 },
    { id: 'meal', label: '拍照记饮食', icon: Camera },
    { id: 'water', label: '记录饮水', icon: HeartPulse },
    { id: 'exercise', label: '上传运动', icon: Dumbbell },
  ]
  return (
    <section className="mobile-quick" aria-label="快速记录">
      {actions.map(({ id, label, icon: Icon }) => (
        <button key={id} type="button" onClick={() => onAction(id)}>
          <span><Icon size={20} aria-hidden="true" /></span>{label}
        </button>
      ))}
    </section>
  )
}

function EmptyRow({ children }) {
  return <p className="empty-row">{children}</p>
}

function LearningPlanRecycleDialog({ plans, loading, busyId, error, onClose, onRestore }) {
  return <div className="dialog-backdrop" role="presentation"><section className="record-dialog recycle-dialog" role="dialog" aria-modal="true" aria-labelledby="plan-trash-title"><header><div><span className="eyebrow">RECYCLE BIN</span><h2 id="plan-trash-title">学习计划回收站</h2></div><button type="button" onClick={onClose} aria-label="关闭"><X size={19} /></button></header><div className="recycle-dialog__body">{loading ? <div className="detail-state"><LoaderCircle className="spin" size={22} />正在读取…</div> : plans.length ? plans.map((plan) => <article key={plan.id}><div><b>{plan.name}</b><span>{plan.goal || '未填写学习目标'}</span></div><button type="button" className="secondary-button" disabled={busyId === plan.id} onClick={() => onRestore(plan)}><RotateCcw size={14} />{busyId === plan.id ? '恢复中' : '恢复'}</button></article>) : <div className="health-empty"><Trash2 size={24} /><h3>回收站是空的</h3><p>删除的学习计划会安全保留在这里。</p></div>}{error ? <p className="form-error">{error}</p> : null}</div></section></div>
}

function ProjectProgress({ projects, onOpenProjects }) {
  const active = (projects || []).filter((project) => project.status === 'active').slice(0, 3)
  return (
    <div className="project-strip">
      {active.length ? active.map((project) => <button type="button" className="project-card" key={project.id} onClick={() => onOpenProjects(project.id)}>
        <div><span><Flag size={14} />{project.name}</span><strong>{project.current_stage}</strong><small>{project.next_milestone || 'AI Agent 会根据进展补充下一里程碑'}</small></div>
        <div className="project-progress"><span>{project.progress_percent}%</span><div><i style={{ width: `${project.progress_percent}%` }} /></div></div>
      </button>) : <button type="button" className="project-empty" onClick={() => onOpenProjects()}><Flag size={18} /><span><strong>把正在推进的项目放到这里</strong><small>你和 AI Agent 都能继续拆阶段、排任务</small></span></button>}
      {active.length ? <button type="button" className="project-add" onClick={() => onOpenProjects()}><Plus size={15} />项目全景</button> : null}
    </div>
  )
}

function TaskBoard({ tasks, progress, projects, upcomingTasks, onAction, onOpenProjects, onOpenCalendar, onReload, onToast }) {
  const total = progress?.total || 0
  const completed = progress?.completed || 0
  const percent = total ? Math.round((completed / total) * 100) : 0

  async function toggleTask(task) {
    const nextDone = !task.done
    const occurrence = task.recurrence === 'yearly' ? { occurrence_date: task.occurrence_date } : {}
    try {
      await api.updateTask(task.id, { done: nextDone, ...occurrence })
      await onReload()
      onToast?.({
        message: nextDone ? `已完成“${task.title}”` : `已将“${task.title}”恢复为待处理`,
        actionLabel: '撤销',
        onAction: async () => {
          await api.updateTask(task.id, { done: task.done, ...occurrence })
          await onReload()
          onToast?.('操作已撤销')
        },
      })
    } catch (requestError) {
      onToast?.({ message: requestError.message || '任务状态更新失败', tone: 'error' })
    }
  }

  return (
    <section className="content-section task-section" aria-labelledby="task-heading">
      <div className="section-heading">
        <button type="button" className="section-title-button" onClick={onOpenCalendar}><span className="eyebrow">TODAY</span><h2 id="task-heading">今日任务 <ChevronRight size={17} /></h2></button>
        <div className="task-progress"><span>{completed}/{total} 完成</span><div><i style={{ width: `${percent}%` }} /></div></div>
        <div className="section-heading__actions"><button type="button" className="text-action" onClick={onOpenCalendar}>年 / 月 / 周日历</button><button type="button" className="secondary-button" onClick={() => onAction('task')}><Plus size={16} />添加任务</button></div>
      </div>
      <ProjectProgress projects={projects} onOpenProjects={onOpenProjects} />
      <div className="quadrant-grid">
        {Object.entries(quadrantMeta).map(([key, meta]) => (
          <article className={`quadrant quadrant--${meta.tone}`} key={key}>
            <header><span className="quadrant__dot" /><div><h3>{meta.title}</h3><span>{meta.hint}</span></div></header>
            <div className="task-list">
              {(tasks?.[key] || []).length ? tasks[key].slice(0, 4).map((task) => {
                const status = taskStatus(task)
                return <div className={`task-row ${task.done ? 'is-done' : ''}`} key={task.id}>
                  <label className="task-row__toggle" aria-label={task.done ? `重新打开${task.title}` : `完成${task.title}`}><input type="checkbox" checked={task.done} onChange={() => toggleTask(task)} /><span className="task-check"><Check size={13} /></span></label>
                  <button type="button" className="task-row__content" onClick={() => onOpenCalendar(task)}><span>{task.title}</span>{task.project_name ? <small>{task.project_name}{task.phase_name ? ` ＞ ${task.phase_name}` : ''}</small> : null}</button>
                  <span className={`task-status-chip task-status-chip--${status.tone}`}>{status.label}</span>
                  <button type="button" className="task-row__edit" onClick={() => onOpenCalendar(task)} aria-label={`编辑${task.title}`}><Pencil size={12} /></button>
                </div>
              }) : <EmptyRow>这里还没有任务</EmptyRow>}
            </div>
          </article>
        ))}
      </div>
      {upcomingTasks?.length ? <div className="upcoming-tasks"><span>之后的安排</span>{upcomingTasks.slice(0, 3).map((task) => <strong key={task.id}>{new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(new Date(task.due_at))} · {task.title}</strong>)}</div> : null}
    </section>
  )
}

function Ring({ value, children }) {
  return <div className="progress-ring" style={{ '--value': `${Math.min(value, 100) * 3.6}deg` }}><div>{children}</div></div>
}

const healthAdviceIcons = {
  overall: Sparkles,
  diet: Utensils,
  hydration: GlassWater,
  exercise: Dumbbell,
}

function conciseAdvice(value, maxLength = 190) {
  const clean = String(value || '').replace(/\*\*/g, '').replace(/\s*•\s*/g, ' · ').replace(/\s+/g, ' ').trim()
  return clean.length > maxLength ? `${clean.slice(0, maxLength).trim()}…` : clean
}

function HealthAdvicePanel({ health, onOpenHealth }) {
  const dailyAdvice = health?.daily_advice || {}
  const sections = dailyAdvice.sections?.length
    ? dailyAdvice.sections
    : dailyAdvice.summary ? [{ key: 'overall', label: '今日结论', content: dailyAdvice.summary }] : []
  const mealAdvice = (health?.recommendations || []).filter((item) => item.kind === 'meal')
  const exerciseAdvice = (health?.recommendations || []).filter((item) => item.kind === 'exercise')
  const hasContent = sections.length || mealAdvice.length || exerciseAdvice.length

  return (
    <div className={`health-advice health-advice--${dailyAdvice.status || 'neutral'}`}>
      <span className="health-advice__icon"><Sparkles size={18} /></span>
      <div className="health-advice__content">
        <div className="health-advice__header"><strong>今日针对性建议</strong><button type="button" onClick={onOpenHealth}>查看全天记录 <ChevronRight size={14} /></button></div>
        {hasContent ? <>
          {sections.length ? <div className="health-advice__sections">{sections.map((section) => {
            const AdviceIcon = healthAdviceIcons[section.key] || Sparkles
            return <article key={section.key}><span><AdviceIcon size={15} /></span><div><b>{section.label}</b><p>{conciseAdvice(section.content)}</p></div></article>
          })}</div> : null}
          {mealAdvice.length ? <div className="meal-advice-list"><span>每餐建议</span>{mealAdvice.slice(0, 5).map((item) => <article key={`${item.record_date}-${item.meal_slot || item.title}`}><b>{item.title}</b><p>{conciseAdvice(item.advice, 150)}</p></article>)}</div> : null}
          {exerciseAdvice.length && !sections.some((section) => section.key === 'exercise') ? <div className="meal-advice-list is-exercise"><span>运动提醒</span>{exerciseAdvice.slice(0, 2).map((item) => <article key={`${item.record_date}-${item.title}`}><b>{item.title}</b><p>{conciseAdvice(item.advice, 150)}</p></article>)}</div> : null}
        </> : <p className="health-advice__empty">上传饮食、体重或运动记录后，AI Agent 会分别给出每餐建议和全天总结。</p>}
      </div>
    </div>
  )
}

function HealthPanel({ health, onAction, onSettings, onOpenHealth }) {
  const caloriePercent = health?.calories_target_kcal
    ? Math.round((health.calories_kcal / health.calories_target_kcal) * 100)
    : 0
  const calorieTarget = health?.calories_target_min_kcal && health?.calories_target_max_kcal
    ? (health.calories_target_min_kcal === health.calories_target_max_kcal
      ? health.calories_target_min_kcal
      : `${health.calories_target_min_kcal}–${health.calories_target_max_kcal}`)
    : health?.calories_target_kcal || '--'
  return (
    <section className="content-section health-section" aria-labelledby="health-heading">
      <div className="section-heading compact">
        <div><span className="eyebrow">HEALTH</span><h2 id="health-heading">今日健康</h2></div>
        <button type="button" className="text-action" onClick={() => onSettings('health')}><Settings2 size={14} />目标设置</button>
        <button type="button" className="text-action" onClick={onOpenHealth}>查看历史 <ChevronRight size={15} /></button>
      </div>
      <div className="weight-goal-card">
        <div><span className="metric-label">减重目标</span><strong>{health?.weight_kg ?? '--'} <small>kg 当前</small><b>→</b> {health?.target_weight_kg ?? '--'} <small>kg 目标</small></strong><p>{health?.distance_to_goal_kg != null ? `距离目标还有 ${health.distance_to_goal_kg} kg` : '设置目标并记录体重后，这里会显示距离。'}</p></div>
        <div className="weight-goal-progress"><span>{health?.weight_goal_percent || 0}%</span><div><i style={{ width: `${health?.weight_goal_percent || 0}%` }} /></div></div>
      </div>
      <div className="health-grid">
        <article className="health-metric health-metric--water">
          <Ring value={health?.water_percent || 0}><strong>{health?.water_percent || 0}%</strong><span>饮水</span></Ring>
          <div><span className="metric-label">今日饮水</span><strong>{health?.water_ml || 0}<small> / {health?.water_target_ml || 2000} ml</small></strong><button type="button" onClick={() => onAction('water')}>+ 记录一杯</button></div>
        </article>
        <article className="health-metric">
          <div className="metric-icon"><Flame size={22} /></div>
          <div><span className="metric-label">今日热量</span><strong>{health?.calories_kcal || 0}<small> kcal</small></strong><span className="metric-sub">参考 {calorieTarget} · {caloriePercent}%</span></div>
          <button type="button" className="icon-action" aria-label="上传饮食图片" onClick={() => onAction('meal')}><Camera size={18} /></button>
        </article>
        <article className="health-metric">
          <div className="metric-icon"><Weight size={22} /></div>
          <div><span className="metric-label">当前体重</span><strong>{health?.weight_kg ?? '--'}<small> kg</small></strong><span className="metric-sub">拍照或手动记录</span></div>
          <button type="button" className="icon-action" aria-label="上传体重秤图片" onClick={() => onAction('weight')}><Scale size={18} /></button>
        </article>
        <article className="health-metric health-metric--exercise">
          <div className="metric-icon"><Dumbbell size={22} /></div>
          <div><span className="metric-label">今日运动记录</span><strong>{health?.exercise_kcal || 0}<small> kcal</small></strong><span className="metric-sub">每周 {health?.exercise_target_minutes_week || 150} 分钟 · 力量 {health?.strength_target_days_week || 2} 天</span></div>
          <button type="button" className="icon-action" aria-label="上传运动报告" onClick={() => onAction('exercise')}><Upload size={18} /></button>
        </article>
      </div>
      <HealthAdvicePanel health={health} onOpenHealth={onOpenHealth} />
    </section>
  )
}

function ContentItem({ item, icon: Icon, onOpen }) {
  const body = (
    <>
      <span className="content-item__icon"><Icon size={18} aria-hidden="true" /></span>
      <span className="content-item__body"><strong>{item.title}</strong><small>{item.summary || '点击查看来源详情'}</small></span>
      {!String(item.id || '').startsWith('legacy_') ? <ChevronRight size={17} aria-hidden="true" /> : <span className="awaiting">待补详情</span>}
    </>
  )
  return !String(item.id || '').startsWith('legacy_') ? <button type="button" className="content-item" onClick={() => onOpen(item.id)}>{body}</button> : <div className="content-item">{body}</div>
}

function ContentCollection({ items, icon, onOpen, empty }) {
  const [expanded, setExpanded] = useState(false)
  if (!items.length) return <EmptyRow>{empty}</EmptyRow>
  const visibleItems = expanded ? items : items.slice(0, 3)
  return (
    <>
      <div className="content-collection" aria-live="polite">
        {visibleItems.map((item) => <ContentItem key={item.id} item={item} icon={icon} onOpen={onOpen} />)}
      </div>
      {items.length > 3 ? <button type="button" className="content-expand" aria-expanded={expanded} onClick={() => setExpanded((current) => !current)}>{expanded ? '收起' : `查看全部 ${items.length} 条`}</button> : null}
    </>
  )
}

function PersonalIPPanel({ content, preferences, onSettings, onOpenContent }) {
  const videoItems = content?.video_trend || []
  const newsItems = content?.ai_news || []
  return (
    <section className="content-section ip-section" aria-labelledby="ip-heading">
      <div className="section-heading compact"><div><span className="eyebrow">DAILY BRIEF</span><h2 id="ip-heading">今日资讯与短视频热点</h2></div><span className="updated-note">由 AI Agent 写入后实时出现</span><button type="button" className="text-action" onClick={() => onSettings('ip')}><Settings2 size={14} />关注设置</button></div>
      <div className="topic-chips">{[...(preferences?.video_topics || []), ...(preferences?.ai_topics || [])].slice(0, 8).map((topic) => <span key={topic}>{topic}</span>)}</div>
      <div className="ip-columns">
        <article>
          <header><Video size={19} /><h3>短视频热点</h3>{videoItems.length ? <span className="content-count">{videoItems.length} 条</span> : null}</header>
          <ContentCollection items={videoItems} icon={Video} onOpen={onOpenContent} empty="等待 AI Agent 抓取今日热点" />
        </article>
        <article>
          <header><Newspaper size={19} /><h3>今日资讯</h3>{newsItems.length ? <span className="content-count">{newsItems.length} 条</span> : null}</header>
          <ContentCollection items={newsItems} icon={BrainCircuit} onOpen={onOpenContent} empty="等待 AI Agent 写入今日资讯" />
        </article>
      </div>
    </section>
  )
}

function GrowthPanel({ plans, library, onAction, onOpenPlan, onOpenLibrary, onReload }) {
  const planItems = plans || []
  const libraryItems = library || []
  const recommended = libraryItems.filter((item) => item.source === 'hermes')
  const documentaries = libraryItems.filter((item) => item.source !== 'hermes' && item.kind === 'documentary')
  const myList = libraryItems.filter((item) => item.source !== 'hermes' && item.kind !== 'documentary')
  const groups = [
    { id: 'recommended', label: 'AI Agent 推荐', icon: Sparkles, items: recommended, empty: 'AI Agent 推荐的书和影片会出现在这里' },
    { id: 'my-list', label: '我的书影单', icon: BookOpen, items: myList, empty: '把想看的书或电影加入清单' },
    { id: 'documentaries', label: '纪录片', icon: Video, items: documentaries, empty: '还没有加入纪录片' },
  ]
  const kindLabel = { book: '书籍', movie: '电影', documentary: '纪录片' }
  const [trashOpen, setTrashOpen] = useState(false)
  const [trashPlans, setTrashPlans] = useState([])
  const [trashLoading, setTrashLoading] = useState(false)
  const [trashError, setTrashError] = useState('')
  const [restoringId, setRestoringId] = useState('')

  async function openTrash() {
    setTrashOpen(true)
    setTrashLoading(true)
    setTrashError('')
    try { setTrashPlans(await api.deletedLearningPlans()) }
    catch (requestError) { setTrashError(requestError.message) }
    finally { setTrashLoading(false) }
  }

  async function restorePlan(plan) {
    setRestoringId(plan.id)
    setTrashError('')
    try {
      await api.restoreLearningPlan(plan.id)
      setTrashPlans((current) => current.filter((item) => item.id !== plan.id))
      await onReload()
    } catch (requestError) {
      setTrashError(requestError.message)
    } finally {
      setRestoringId('')
    }
  }

  return (
    <><section className="content-section growth-section" aria-labelledby="growth-heading">
      <div className="section-heading compact"><div><span className="eyebrow">GROWTH</span><h2 id="growth-heading">个人成长</h2></div><span className="updated-note">先选目录，再进入详情学习或记录</span></div>
      <div className="growth-browser">
        <article className="growth-column growth-column--plans">
          <header><div><span className="growth-column__icon"><Lightbulb size={18} /></span><div><h3>我的学习计划</h3><p>{planItems.length} 个计划</p></div></div><span className="growth-column__actions"><button type="button" className="text-action" onClick={openTrash}><Trash2 size={14} />回收站</button><button type="button" className="text-action" onClick={() => onAction('growth')}><Plus size={14} />添加</button></span></header>
          <div className="growth-directory" aria-label="我的学习计划">
            {planItems.length ? planItems.map((plan) => {
              const percent = plan.total_lessons ? Math.round((plan.completed_lessons / plan.total_lessons) * 100) : 0
              return <button type="button" className="growth-directory-row" key={plan.id} onClick={() => onOpenPlan(plan.id)}>
                <span className="growth-row-mark"><Lightbulb size={16} /></span>
                <span className="growth-row-body"><strong>{plan.name}</strong><small>{plan.status === 'waiting_for_hermes' ? 'AI Agent 正在制定计划' : `${plan.completed_lessons}/${plan.total_lessons || '--'} 课 · ${percent}%`}</small><i><b style={{ width: `${percent}%` }} /></i></span>
                <ChevronRight size={17} />
              </button>
            }) : <button type="button" className="growth-directory-empty" onClick={() => onAction('growth')}><Plus size={18} /><span><strong>添加第一个学习计划</strong><small>围棋、吉他或任何想学的技能</small></span></button>}
          </div>
        </article>
        <article className="growth-column growth-column--library">
          <header><div><span className="growth-column__icon"><BookOpen size={18} /></span><div><h3>最近的书影音</h3><p>{libraryItems.length} 个条目</p></div></div><button type="button" className="text-action" onClick={() => onAction('library')}><Plus size={14} />添加</button></header>
          <div className="library-groups">
            {groups.map(({ id, label, icon: GroupIcon, items, empty }) => <section className="library-group" key={id}>
              <div className="library-group__heading"><span><GroupIcon size={14} />{label}</span><small>{items.length}</small></div>
              {items.length ? items.map((item) => <button type="button" className="library-directory-row" key={item.id} onClick={() => onOpenLibrary(item.id)}>
                <span><strong>{item.title}</strong><small>{kindLabel[item.kind] || '书影音'} · {item.current_position || (item.status === 'done' ? '已完成' : '还未开始')}</small><i><b style={{ width: `${item.progress_percent || 0}%` }} /></i></span>
                <em>{item.progress_percent || 0}%</em><ChevronRight size={16} />
              </button>) : <p className="library-group__empty">{empty}</p>}
            </section>)}
          </div>
        </article>
      </div>
    </section>{trashOpen ? <LearningPlanRecycleDialog plans={trashPlans} loading={trashLoading} busyId={restoringId} error={trashError} onClose={() => setTrashOpen(false)} onRestore={restorePlan} /> : null}</>
  )
}

function AgentSection({ data }) {
  return (
    <section className="focused-page hermes-page">
      <span className="focused-page__icon"><Sparkles size={25} /></span>
      <span className="eyebrow">AI AGENT</span>
      <h2>{data?.hermes?.connected ? 'AI Agent 已连接工作台' : '等待 AI Agent 首次连接'}</h2>
      <p>{data?.suggestion?.content || '完成 MCP 配置后，AI Agent 可以读取工作台、创建任务、保存资讯、更新健康记录，并留下每天的建议。'}</p>
      <div className="connection-card"><span className={`status-dot ${data?.hermes?.connected ? 'is-online' : ''}`} /><div><strong>{data?.hermes?.label || 'AI Agent 等待接入'}</strong><span>所有 Agent 写入都会留下审计记录</span></div></div>
    </section>
  )
}

function ProfileSection({ data, onAction }) {
  return (
    <div className="profile-page-wrap"><section className="focused-page profile-page">
        <span className="focused-page__icon"><HeartPulse size={25} /></span>
        <span className="eyebrow">MY WORKBENCH</span>
        <h2>{data?.profile?.nickname || '朋友'}的个人工作台</h2>
        <p>数据与图片独立于程序保存；可以随时导出为 Markdown、JSON、CSV 和原始附件。</p>
        <div className="profile-actions"><button type="button" className="primary-button" onClick={() => onAction('weight')}>记录体重</button><button type="button" className="secondary-button" onClick={() => onAction('growth')}>新建计划</button></div>
        <div className="profile-stat"><strong>{data?.index?.documents || 0}</strong><span>份已索引的工作台文档</span></div>
      </section><SystemPanel /></div>
  )
}

export function Dashboard({ section, data, loading, error, onAction, onSettings, onOpenPlan, onOpenLibrary, onOpenContent, onOpenHealth, onOpenCalendar, onOpenProjects, onReload, onToast }) {
  if (loading && !data) return <div className="screen-state"><LoaderCircle className="spin" size={28} /><span>正在打开你的工作台…</span></div>
  if (error && !data) return <div className="screen-state is-error"><span>{error}</span><button type="button" onClick={onReload}><RefreshCw size={16} />重新加载</button></div>

  if (section === 'hermes') return <div className="page-wrap"><Greeting date={data?.date} profile={data?.profile} greeting={data?.greeting} onSettings={onSettings} /><AgentSection data={data} /></div>
  if (section === 'profile') return <div className="page-wrap"><Greeting date={data?.date} profile={data?.profile} greeting={data?.greeting} onSettings={onSettings} /><ProfileSection data={data} onAction={onAction} /></div>

  const show = (name) => section === 'workbench' || section === name
  return (
    <div className="page-wrap">
      <Greeting date={data?.date} profile={data?.profile} greeting={data?.greeting} onSettings={onSettings} />
      <QuickActions onAction={onAction} />
      {show('tasks') ? <TaskBoard tasks={data?.tasks} progress={data?.task_progress} projects={data?.projects} upcomingTasks={data?.upcoming_tasks} onAction={onAction} onOpenProjects={onOpenProjects} onOpenCalendar={onOpenCalendar} onReload={onReload} onToast={onToast} /> : null}
      {show('health') ? <HealthPanel health={data?.health} onAction={onAction} onSettings={onSettings} onOpenHealth={onOpenHealth} /> : null}
      {show('ip') ? <PersonalIPPanel content={data?.content} preferences={data?.preferences?.ip} onSettings={onSettings} onOpenContent={onOpenContent} /> : null}
      {show('growth') ? <GrowthPanel plans={data?.growth} library={data?.library} onAction={onAction} onOpenPlan={onOpenPlan} onOpenLibrary={onOpenLibrary} onReload={onReload} /> : null}
      {error ? <div className="inline-error">实时更新暂时中断：{error}</div> : null}
    </div>
  )
}
