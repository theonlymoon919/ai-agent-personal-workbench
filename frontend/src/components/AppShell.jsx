import {
  BookOpen,
  Bot,
  CheckSquare2,
  CircleUserRound,
  HeartPulse,
  Home,
  LogOut,
  Menu,
  Newspaper,
  Plus,
  Sparkles,
  WalletCards,
} from 'lucide-react'

const desktopNavigation = [
  { id: 'workbench', label: '工作台', icon: Home },
  { id: 'ip', label: '今日资讯', icon: Newspaper },
  { id: 'health', label: '健康追踪', icon: HeartPulse },
  { id: 'finance', label: '财务管理', icon: WalletCards },
  { id: 'growth', label: '个人成长', icon: BookOpen },
  { id: 'tasks', label: '今日任务', icon: CheckSquare2 },
  { id: 'hermes', label: 'AI Agent', icon: Bot },
  { id: 'profile', label: '我的', icon: CircleUserRound },
]

const mobileNavigation = [
  { id: 'workbench', label: '首页', icon: Home },
  { id: 'tasks', label: '任务', icon: CheckSquare2 },
  { id: 'ip', label: '资讯', icon: Newspaper },
  { id: 'growth', label: '成长', icon: BookOpen },
  { id: 'finance', label: '财务', icon: WalletCards },
  { id: 'profile', label: '我的', icon: CircleUserRound },
]

function NavigationButton({ item, active, onClick, compact = false }) {
  const Icon = item.icon
  return (
    <button
      type="button"
      className={`${compact ? 'mobile-nav__item' : 'side-nav__item'} ${active ? 'is-active' : ''}`}
      onClick={onClick}
      aria-current={active ? 'page' : undefined}
    >
      <Icon size={compact ? 21 : 18} strokeWidth={1.9} aria-hidden="true" />
      <span>{item.label}</span>
    </button>
  )
}

function formatActivity(item) {
  const labels = {
    create_task: '新增了任务',
    update_task: '更新了任务',
    record_water: '记录了饮水',
    record_weight: '记录了体重',
    create_learning_plan: '创建了学习计划',
    create_library_item: '加入了书影单',
    analyze_health_record: '完成了健康分析',
    save_content_item: '保存了专栏内容',
    save_suggestion: '留下了一条建议',
    upload_record: '收到了一张打卡图片',
    'agent_job.queued': '已进入 AI Agent 队列',
    'agent_job.started': 'AI Agent 开始处理',
    'agent_job.completed': 'AI Agent 已完成处理',
    'agent_job.failed': 'AI Agent 处理失败',
    'health.record_analyzed': '完成了健康分析',
    'health.daily_summary_updated': '更新了健康总结',
    'finance.transaction_created': '新增了财务记录',
    'finance.insight_created': '生成了财务建议',
    'growth.plan_generated': '完成了学习计划',
    'content.item_saved': '更新了专栏内容',
  }
  return `${labels[item.action] || item.action} · ${item.summary}`
}

function activityTime(value) {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return String(value || '').slice(0, 5)
  return parsed.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function AgentRail({ hermes, activity, suggestion, onSectionChange }) {
  return (
    <aside className="hermes-rail" aria-label="AI Agent 动态">
      <div className="hermes-rail__top">
        <span className={`status-dot ${hermes?.connected ? 'is-online' : ''}`} aria-hidden="true" />
        <div>
          <strong>AI Agent</strong>
          <span>{hermes?.processing_jobs ? '正在处理你的记录' : hermes?.pending_jobs ? '已有任务等待处理' : hermes?.connected ? '在线并可操作' : '等待首次接入'}</span>
        </div>
        <Bot size={22} aria-hidden="true" />
      </div>

      <section className="rail-section">
        <div className="section-kicker">最近动态</div>
        <div className="activity-list">
          {activity.length ? activity.slice(0, 3).map((item, index) => (
            <article className="activity-item" key={`${item.time}-${index}`}>
              <span className="activity-item__time">{activityTime(item.time)}</span>
              <p>{formatActivity(item)}</p>
            </article>
          )) : (
            <p className="quiet-copy">AI Agent 接入后，它的每次写入都会显示在这里。</p>
          )}
        </div>
      </section>

      <section className="rail-suggestion">
        <div className="rail-suggestion__icon"><Sparkles size={17} aria-hidden="true" /></div>
        <div className="section-kicker">AI Agent 建议</div>
        <h3>{suggestion?.title || '先从今天最重要的一件事开始'}</h3>
        <p>{suggestion?.content || '完成工作台的首次记录后，AI Agent 会结合你的任务、饮食和计划给出建议。'}</p>
        <button type="button" className="text-action" onClick={() => onSectionChange('hermes')}>
          查看建议记录 <span aria-hidden="true">→</span>
        </button>
      </section>

      <div className="rail-note">
        <span>数据保存在</span>
        <strong>私有数据 · 可独立导出</strong>
      </div>
    </aside>
  )
}

export function AppShell({ section, onSectionChange, hermes, activity, suggestion, onQuickRecord, onLogout, focusWide = false, children }) {
  return (
    <div className={`app-frame ${focusWide ? 'is-focus-wide' : ''}`}>
      <aside className="sidebar">
        <div className="brand">
          <div className="brand__mark"><Sparkles size={18} aria-hidden="true" /></div>
          <div><strong>AI Agent 个人工作台</strong><span>USER-OWNED AI OS</span></div>
        </div>
        <nav className="side-nav" aria-label="主导航">
          {desktopNavigation.map((item) => (
            <NavigationButton key={item.id} item={item} active={section === item.id} onClick={() => onSectionChange(item.id)} />
          ))}
        </nav>
        <button type="button" className="quick-record" onClick={onQuickRecord}>
          <Plus size={17} aria-hidden="true" />快速记录
        </button>
        <div className="sidebar__footer">
          <span className={`status-dot ${hermes?.connected ? 'is-online' : ''}`} aria-hidden="true" />
          <span>{hermes?.connected ? 'AI Agent 已连接' : 'AI Agent 等待接入'}</span>
          <button type="button" className="logout-button" onClick={onLogout} aria-label="退出登录"><LogOut size={15} /></button>
        </div>
      </aside>

      <main className="main-column">
        <div className="mobile-topbar">
          <div className="brand__mark"><Sparkles size={17} aria-hidden="true" /></div>
          <strong>AI Agent 个人工作台</strong>
          <div className="mobile-topbar__actions">
            <button type="button" aria-label="切换到个人页面" onClick={() => onSectionChange('profile')}>
              <Menu size={22} aria-hidden="true" />
            </button>
            <button type="button" className="mobile-logout" aria-label="退出登录" onClick={onLogout}>
              <LogOut size={18} aria-hidden="true" />
            </button>
          </div>
        </div>
        {children}
      </main>

      <AgentRail hermes={hermes} activity={activity} suggestion={suggestion} onSectionChange={onSectionChange} />

      <nav className="mobile-nav" aria-label="手机端导航">
        {mobileNavigation.map((item) => (
          <NavigationButton compact key={item.id} item={item} active={section === item.id} onClick={() => onSectionChange(item.id)} />
        ))}
      </nav>
    </div>
  )
}
