import {
  ArrowDownLeft,
  ArrowLeft,
  ArrowUpRight,
  BarChart3,
  Building2,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  CirclePlus,
  CreditCard,
  Landmark,
  LoaderCircle,
  Pencil,
  PiggyBank,
  RefreshCw,
  Search,
  Sparkles,
  Tag,
  Trash2,
  WalletCards,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'

const rangeOptions = [
  ['day', '日'],
  ['week', '周'],
  ['month', '月'],
  ['quarter', '季度'],
  ['year', '年'],
  ['custom', '自定义'],
]

const typeMeta = {
  income: { label: '收入', sign: '+', tone: 'income', icon: ArrowDownLeft },
  expense: { label: '支出', sign: '-', tone: 'expense', icon: ArrowUpRight },
  transfer: { label: '转账', sign: '', tone: 'transfer', icon: CreditCard },
  refund: { label: '退款', sign: '+', tone: 'refund', icon: RefreshCw },
}

const accountTypes = [
  ['cash', '现金'], ['wechat', '微信'], ['alipay', '支付宝'], ['bank', '银行卡'], ['other', '其他'],
]

const accountIconByType = {
  bank: CreditCard,
  cash: WalletCards,
  wechat: WalletCards,
  alipay: WalletCards,
  other: Building2,
}

function localISO(value = new Date()) {
  const date = new Date(value)
  date.setHours(12, 0, 0, 0)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function offsetDate(days) {
  const value = new Date()
  value.setDate(value.getDate() + days)
  return localISO(value)
}

function rangeFor(mode, custom) {
  const today = new Date()
  today.setHours(12, 0, 0, 0)
  const start = new Date(today)
  if (mode === 'day') return { startDate: localISO(today), endDate: localISO(today) }
  if (mode === 'week') start.setDate(today.getDate() - 6)
  if (mode === 'month') start.setDate(1)
  if (mode === 'quarter') start.setMonth(Math.floor(today.getMonth() / 3) * 3, 1)
  if (mode === 'year') start.setMonth(0, 1)
  if (mode === 'custom') return custom
  return { startDate: localISO(start), endDate: localISO(today) }
}

function formatMoney(value) {
  const numeric = Number(value || 0)
  return new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY' }).format(numeric)
}

function formatDate(value) {
  return new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric' }).format(new Date(`${value}T12:00:00`))
}

function formatFullDate(value) {
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' }).format(new Date(`${value}T12:00:00`))
}

function moveISODate(value, days) {
  const target = new Date(`${value}T12:00:00`)
  target.setDate(target.getDate() + days)
  return localISO(target)
}

function accountTypeLabel(value) {
  return accountTypes.find(([type]) => type === value)?.[1] || '其他'
}

function transactionFlow(item, meta) {
  const account = item.account?.name || '未指定账户'
  if (item.type === 'transfer') return `${account} → ${item.to_account?.name || '未指定账户'}`
  if (item.type === 'income') return `${item.merchant || item.category?.name || '收入来源'} → ${account}`
  if (item.type === 'refund') return `${item.category?.name || '退款'} → ${account}`
  return `${account} → ${item.category?.name || item.purpose || meta.label}`
}

function DialogShell({ title, eyebrow, children, onClose, alert = false, wide = false }) {
  const titleId = `finance-dialog-${title.replace(/\s+/g, '-')}`
  return <div className="dialog-backdrop" role="presentation"><section className={`record-dialog finance-dialog ${wide ? 'finance-dialog--wide' : ''}`} role={alert ? 'alertdialog' : 'dialog'} aria-modal="true" aria-labelledby={titleId}>
    <header><div><span className="eyebrow">{eyebrow}</span><h2 id={titleId}>{title}</h2></div><button type="button" onClick={onClose} aria-label="关闭"><X size={19} /></button></header>
    {children}
  </section></div>
}

function FinanceRangeControls({ mode, custom, customOpen, error, onMode, onCustom, onApply }) {
  return <div className="finance-range-controls">
    <div className="finance-range-tabs" aria-label="财务统计范围">{rangeOptions.map(([value, label]) => <button type="button" key={value} className={mode === value ? 'is-active' : ''} aria-pressed={mode === value} onClick={() => onMode(value)}>{label}</button>)}</div>
    {customOpen ? <form className="custom-range-form" onSubmit={onApply}>
      <label><span>开始日期</span><input type="date" name="start_date" min={offsetDate(-3660)} max={custom.endDate || localISO()} value={custom.startDate} onChange={(event) => onCustom('startDate', event.target.value)} /></label>
      <label><span>结束日期</span><input type="date" name="end_date" min={custom.startDate || offsetDate(-3660)} max={localISO()} value={custom.endDate} onChange={(event) => onCustom('endDate', event.target.value)} /></label>
      <button type="submit" className="primary-button">应用区间</button>
      {error ? <p>{error}</p> : null}
    </form> : null}
  </div>
}

function FinanceTrendChart({ timeline }) {
  const values = timeline || []
  const width = 760
  const height = 250
  const margin = { top: 28, right: 20, bottom: 40, left: 58 }
  const plotWidth = width - margin.left - margin.right
  const plotHeight = height - margin.top - margin.bottom
  const maximum = Math.max(100, ...values.flatMap((item) => [Number(item.income_yuan || 0), Number(item.expense_yuan || 0)]))
  const groupWidth = plotWidth / Math.max(values.length, 1)
  const barWidth = Math.min(22, groupWidth * 0.28)
  const y = (value) => margin.top + plotHeight - (Number(value || 0) / maximum) * plotHeight
  return <div className="finance-chart-wrap">
    <svg className="finance-trend-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="所选周期的收入和支出趋势">
      {[0, 0.5, 1].map((ratio) => <g key={ratio}><line className="chart-grid" x1={margin.left} x2={width - margin.right} y1={margin.top + plotHeight * ratio} y2={margin.top + plotHeight * ratio} /><text className="chart-axis-label" x={margin.left - 9} y={margin.top + plotHeight * ratio + 4} textAnchor="end">{Math.round(maximum * (1 - ratio)).toLocaleString('zh-CN')}</text></g>)}
      {values.map((item, index) => {
        const center = margin.left + groupWidth * index + groupWidth / 2
        const incomeY = y(item.income_yuan)
        const expenseY = y(item.expense_yuan)
        return <g key={item.month}>
          <rect x={center - barWidth - 2} y={incomeY} width={barWidth} height={margin.top + plotHeight - incomeY} rx="5" className="finance-bar finance-bar--income" />
          <rect x={center + 2} y={expenseY} width={barWidth} height={margin.top + plotHeight - expenseY} rx="5" className="finance-bar finance-bar--expense" />
          <text className="chart-axis-label" x={center} y={height - 12} textAnchor="middle">{item.month.slice(5)}月</text>
        </g>
      })}
      {!values.length ? <text x={width / 2} y={height / 2} textAnchor="middle" className="chart-empty">这个区间还没有收支记录</text> : null}
    </svg>
    <div className="finance-chart-key"><span><i className="is-income" />收入</span><span><i className="is-expense" />支出</span></div>
  </div>
}

function CategoryBreakdown({ items }) {
  const maximum = Math.max(1, ...(items || []).map((item) => Number(item.amount_minor || 0)))
  return <section className="finance-category-chart" aria-label="支出分类构成">
    <div className="detail-section-heading"><div><span className="eyebrow">COMPOSITION</span><h2>钱花在了哪里</h2></div><span>{items?.length || 0} 个分类</span></div>
    {items?.length ? <div className="finance-category-bars">{items.slice(0, 8).map((item) => <div key={item.category.id}>
      <header><span><i style={{ background: item.category.color || '#8ca195' }} />{item.category.name}</span><strong>{formatMoney(item.amount_yuan)}</strong></header>
      <div><i style={{ width: `${Math.max(2, Number(item.amount_minor || 0) / maximum * 100)}%`, background: item.category.color || '#8ca195' }} /></div>
      <small>{Math.round(Number(item.share || 0) * 100)}%</small>
    </div>)}</div> : <div className="finance-empty"><Tag size={22} /><p>这个区间还没有支出分类数据。</p></div>}
  </section>
}

function TransactionDialog({ transaction, defaultAccountId = '', categories, accounts, busy, error, onClose, onSave }) {
  const editing = Boolean(transaction?.id)
  const [transactionType, setTransactionType] = useState(transaction?.type || 'expense')
  const selectableCategories = categories.filter((item) => item.type === transactionType)
  const accountLabel = transactionType === 'transfer' ? '从哪个账户转出' : transactionType === 'income' ? '收入进入哪个账户' : '从哪个账户扣款'
  const accountPlaceholder = transactionType === 'transfer' ? '请选择转出账户' : transactionType === 'income' ? '请选择入账账户' : '请选择扣款账户'
  return <DialogShell title={editing ? '编辑这笔流水' : '记一笔'} eyebrow="MONEY FLOW" onClose={onClose} wide>
    <form onSubmit={(event) => {
      event.preventDefault()
      const values = new FormData(event.currentTarget)
      const payload = {
        amount_yuan: values.get('amount_yuan'),
        local_date: values.get('local_date'),
        account_id: values.get('account_id') || null,
        merchant: values.get('merchant') || '',
        purpose: values.get('purpose') || '',
        note: values.get('note') || '',
        tags: String(values.get('tags') || '').split(/[,，]/).map((item) => item.trim()).filter(Boolean),
        is_fixed: values.get('is_fixed') === 'on',
        is_necessary: values.get('is_necessary') === 'on',
      }
      if (transactionType !== 'transfer') payload.category_id = values.get('category_id') || null
      if (!editing) {
        payload.transaction_type = transactionType
        if (transactionType === 'transfer') payload.to_account_id = values.get('to_account_id') || null
      }
      onSave(payload)
    }}>
      <div className="finance-entry-types" role="group" aria-label="收支类型">{['expense', 'income', 'transfer'].map((type) => <button type="button" key={type} className={transactionType === type ? 'is-active' : ''} aria-pressed={transactionType === type} disabled={editing} onClick={() => setTransactionType(type)}>{typeMeta[type].label}</button>)}</div>
      <p className="finance-dialog-explainer">{transactionType === 'expense' ? '支出会从所选账户余额中扣除。' : transactionType === 'income' ? '收入会进入所选账户并增加余额。' : '转账只改变两个账户的余额，不计入收入或支出。'}</p>
      <div className="form-columns"><label><span>金额（元）</span><input type="number" inputMode="decimal" name="amount_yuan" min="0.01" step="0.01" defaultValue={transaction?.amount_yuan || ''} placeholder="0.00" required autoFocus /></label><label><span>日期</span><input type="date" name="local_date" max={localISO()} defaultValue={transaction?.local_date || localISO()} required /></label></div>
      {transactionType !== 'transfer' ? <label><span>{transactionType === 'income' ? '收入分类' : '支出分类'}</span><select name="category_id" defaultValue={transaction?.category?.id || ''} required><option value="">请选择分类</option>{selectableCategories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label> : null}
      <div className="form-columns"><label><span>{accountLabel}</span><select name="account_id" defaultValue={transaction?.account?.id || defaultAccountId} required disabled={editing && transactionType === 'transfer'}><option value="">{accountPlaceholder}</option>{accounts.map((item) => <option key={item.id} value={item.id}>{item.name} · 余额 {formatMoney(item.current_balance_yuan)}</option>)}</select></label>{transactionType === 'transfer' && !editing ? <label><span>转入哪个账户</span><select name="to_account_id" defaultValue={transaction?.to_account?.id || ''} required><option value="">请选择转入账户</option>{accounts.map((item) => <option key={item.id} value={item.id}>{item.name} · 余额 {formatMoney(item.current_balance_yuan)}</option>)}</select></label> : <label><span>{transactionType === 'income' ? '收入来源' : '商户'}</span><input name="merchant" maxLength="160" defaultValue={transaction?.merchant || ''} placeholder={transactionType === 'income' ? '例如：公司发薪' : '例如：超市、餐厅'} /></label>}</div>
      <label><span>用途</span><input name="purpose" maxLength="240" defaultValue={transaction?.purpose || ''} placeholder="这笔钱用于什么" /></label>
      <label><span>标签</span><input name="tags" defaultValue={(transaction?.tags || []).join('，')} placeholder="用逗号分隔，例如：家庭，固定开销" /></label>
      <label><span>备注</span><textarea name="note" rows="3" maxLength="4000" defaultValue={transaction?.note || ''} /></label>
      <div className="finance-checks"><label><input type="checkbox" name="is_fixed" defaultChecked={transaction?.is_fixed} />固定收支</label><label><input type="checkbox" name="is_necessary" defaultChecked={transaction?.is_necessary} />必要支出</label></div>
      {editing && transactionType === 'transfer' ? <p className="dialog-helper">转账双方账户不能在编辑时更换；如需更换，请删除后重新记录。</p> : null}
      {error ? <p className="form-error">{error}</p> : null}
      {!accounts.length ? <p className="form-error">还没有可用账户，请先创建银行卡、微信、支付宝或现金账户。</p> : null}
      <div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>取消</button><button type="submit" className="primary-button" disabled={busy || !accounts.length}>{busy ? '正在保存…' : '保存流水'}</button></div>
    </form>
  </DialogShell>
}

function DeleteTransactionDialog({ transaction, busy, error, onClose, onConfirm }) {
  return <DialogShell title="移入财务回收状态？" eyebrow="CONFIRM DELETE" onClose={onClose} alert>
    <div className="confirm-dialog-body"><p>这笔“{transaction.purpose || transaction.merchant || typeMeta[transaction.type]?.label}”记录会从统计、预算和普通明细中隐藏，之后仍可通过已删除筛选恢复。</p>{error ? <p className="form-error">{error}</p> : null}<div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>取消</button><button type="button" className="danger-button" disabled={busy} onClick={onConfirm}>{busy ? '正在处理…' : '确认删除'}</button></div></div>
  </DialogShell>
}

function DeleteBudgetDialog({ budget, busy, error, onClose, onConfirm }) {
  const label = budget.category?.name || '总支出'
  return <DialogShell title="删除这项预算？" eyebrow="CONFIRM DELETE" onClose={onClose} alert>
    <div className="confirm-dialog-body"><p>“{label}”预算（{formatDate(budget.period_start)}—{formatDate(budget.period_end)}，{formatMoney(budget.amount_yuan)}）将停止参与预算进度和财务统计。已有流水不会被删除；以后重新设置相同周期和分类即可再次启用。</p>{error ? <p className="form-error">{error}</p> : null}<div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>取消</button><button type="button" className="danger-button" disabled={busy} onClick={onConfirm}>{busy ? '正在删除…' : '确认删除预算'}</button></div></div>
  </DialogShell>
}

function FinanceSetupDialog({ categories, accounts, busy, error, onClose, onCreateCategory, onUpdateCategory, onCreateAccount, onUpdateAccount }) {
  const [tab, setTab] = useState('accounts')
  const visibleAccounts = accounts.filter((item) => !item.is_placeholder)
  return <DialogShell title="账户与收支分类" eyebrow="FINANCE SETUP" onClose={onClose} wide>
    <div className="finance-dialog-body">
      <div className="finance-dialog-tabs"><button type="button" aria-pressed={tab === 'accounts'} className={tab === 'accounts' ? 'is-active' : ''} onClick={() => setTab('accounts')}>账户</button><button type="button" aria-pressed={tab === 'categories'} className={tab === 'categories' ? 'is-active' : ''} onClick={() => setTab('categories')}>收支分类</button></div>
      {tab === 'accounts' ? <><p className="finance-setup-explainer"><b>账户</b>是钱实际存放的位置，例如银行卡、微信、支付宝或现金。每笔收支选择账户后，当前余额会自动变化。</p><form className="finance-inline-form" onSubmit={(event) => { event.preventDefault(); const values = new FormData(event.currentTarget); onCreateAccount({ name: values.get('name'), account_type: values.get('account_type'), opening_balance_yuan: values.get('opening_balance_yuan') || '0' }, event.currentTarget) }}><label><span>账户名称</span><input name="name" maxLength="80" placeholder="例如：工资卡" required /></label><label><span>账户类型</span><select name="account_type">{accountTypes.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label><label><span>开始记账时余额</span><input type="number" step="0.01" name="opening_balance_yuan" defaultValue="0" /><small>只填首次启用时已有的钱</small></label><button type="submit" className="primary-button" disabled={busy}><CirclePlus size={15} />添加账户</button></form><div className="finance-setup-list">{visibleAccounts.length ? visibleAccounts.map((item) => { const AccountIcon = accountIconByType[item.type] || Building2; return <article key={item.id}><span><AccountIcon size={16} /></span><div><b>{item.name}</b><strong>当前 {formatMoney(item.current_balance_yuan)}</strong><small>{accountTypeLabel(item.type)} · 起点 {formatMoney(item.opening_balance_yuan)} · {item.transaction_count || 0} 笔流水</small></div><button type="button" className="secondary-button" disabled={busy} onClick={() => onUpdateAccount(item.id, { status: item.status === 'active' ? 'archived' : 'active' })}>{item.status === 'active' ? '停用' : '启用'}</button></article> }) : <div className="finance-empty"><WalletCards size={22} /><p>还没有真实账户。添加后，收入和支出才有明确的入账与扣款位置。</p></div>}</div></> : <><p className="finance-setup-explainer"><b>分类</b>表示钱的用途或来源，例如餐饮、交通和工资；它用于分析和预算，不保存余额。</p><form className="finance-inline-form finance-inline-form--category" onSubmit={(event) => { event.preventDefault(); const values = new FormData(event.currentTarget); onCreateCategory({ name: values.get('name'), category_type: values.get('category_type'), color: values.get('color') }, event.currentTarget) }}><label><span>分类名称</span><input name="name" maxLength="80" placeholder="例如：旅行" required /></label><label><span>类型</span><select name="category_type"><option value="expense">支出</option><option value="income">收入</option></select></label><label><span>颜色</span><input type="color" name="color" defaultValue="#557b69" /></label><button type="submit" className="primary-button" disabled={busy}><CirclePlus size={15} />添加分类</button></form><div className="finance-setup-list">{categories.map((item) => <article key={item.id}><span className="finance-category-dot" style={{ background: item.color || '#82958a' }} /><div><b>{item.name}</b><small>{item.type === 'income' ? '收入' : '支出'}{item.system_key ? ' · 系统分类' : ' · 自定义分类'}</small></div><button type="button" className="secondary-button" disabled={busy} onClick={() => onUpdateCategory(item.id, { active: !item.active })}>{item.active ? '停用' : '启用'}</button></article>)}</div></>}
      {error ? <p className="form-error">{error}</p> : null}
    </div>
  </DialogShell>
}

function BudgetGoalDialog({ mode, item, categories, range, busy, error, onClose, onSaveBudget, onSaveGoal }) {
  const editingGoal = mode === 'goal' && item?.id
  return <DialogShell title={mode === 'budget' ? '设置预算' : editingGoal ? '更新储蓄目标' : '新建储蓄目标'} eyebrow={mode === 'budget' ? 'BUDGET' : 'SAVINGS GOAL'} onClose={onClose}>
    {mode === 'budget' ? <form onSubmit={(event) => { event.preventDefault(); const values = new FormData(event.currentTarget); onSaveBudget({ period_start: values.get('period_start'), period_end: values.get('period_end'), amount_yuan: values.get('amount_yuan'), category_id: values.get('category_id') || null, rollover: values.get('rollover') === 'on' }) }}>
      <div className="form-columns"><label><span>开始日期</span><input type="date" name="period_start" defaultValue={range.startDate} required /></label><label><span>结束日期</span><input type="date" name="period_end" defaultValue={range.endDate} required /></label></div>
      <label><span>预算金额（元）</span><input type="number" name="amount_yuan" min="0.01" step="0.01" placeholder="3000.00" required autoFocus /></label>
      <label><span>预算分类</span><select name="category_id"><option value="">总支出预算</option>{categories.filter((category) => category.type === 'expense' && category.active).map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
      <label className="finance-checkbox"><input type="checkbox" name="rollover" />允许结余滚入下一周期</label>
      {error ? <p className="form-error">{error}</p> : null}<div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>取消</button><button type="submit" className="primary-button" disabled={busy}>{busy ? '正在保存…' : '保存预算'}</button></div>
    </form> : <form onSubmit={(event) => { event.preventDefault(); const values = new FormData(event.currentTarget); onSaveGoal({ name: values.get('name'), target_amount_yuan: values.get('target_amount_yuan'), current_amount_yuan: values.get('current_amount_yuan') || '0', target_date: values.get('target_date') || null, ...(editingGoal ? { status: values.get('status') } : {}) }) }}>
      <label><span>目标名称</span><input name="name" maxLength="160" defaultValue={item?.name || ''} placeholder="例如：旅行基金" required autoFocus /></label>
      <div className="form-columns"><label><span>目标金额</span><input type="number" name="target_amount_yuan" min="0.01" step="0.01" defaultValue={item?.target_amount_yuan || ''} required /></label><label><span>当前金额</span><input type="number" name="current_amount_yuan" min="0" step="0.01" defaultValue={item?.current_amount_yuan || '0'} /></label></div>
      <label><span>目标日期</span><input type="date" name="target_date" defaultValue={item?.target_date || ''} /></label>
      {editingGoal ? <label><span>状态</span><select name="status" defaultValue={item.status}><option value="active">进行中</option><option value="paused">已暂停</option><option value="completed">已完成</option></select></label> : null}
      {error ? <p className="form-error">{error}</p> : null}<div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>取消</button><button type="submit" className="primary-button" disabled={busy}>{busy ? '正在保存…' : '保存目标'}</button></div>
    </form>}
  </DialogShell>
}

function Pagination({ page, totalPages, total, onPage }) {
  return <nav className="server-pagination" aria-label="明细分页"><button type="button" disabled={page <= 1} onClick={() => onPage(page - 1)}><ChevronLeft size={15} />上一页</button><span>第 {page} / {totalPages} 页 · 共 {total} 条</span><button type="button" disabled={page >= totalPages} onClick={() => onPage(page + 1)}>下一页<ChevronRight size={15} /></button></nav>
}

function FinanceAccountDetail({ account, refreshKey, onBack, onNewTransaction, onEdit, onDelete }) {
  const [selectedDate, setSelectedDate] = useState(localISO)
  const [page, setPage] = useState(1)
  const [detail, setDetail] = useState(null)
  const [transactions, setTransactions] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async ({ quiet = false } = {}) => {
    if (!quiet) setLoading(true)
    try {
      const [nextDetail, nextTransactions] = await Promise.all([
        api.financeAccountDetail(account.id, selectedDate),
        api.financeTransactions({ accountId: account.id, startDate: selectedDate, endDate: selectedDate, page, pageSize: 12 }),
      ])
      setDetail(nextDetail)
      setTransactions(nextTransactions)
      setError('')
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      if (!quiet) setLoading(false)
    }
  }, [account.id, selectedDate, page, refreshKey])

  useEffect(() => { load() }, [load])

  function chooseDate(value) {
    setSelectedDate(value)
    setPage(1)
    setDetail(null)
    setTransactions(null)
    setError('')
  }

  const summary = detail?.day_summary
  const inflow = Number(summary?.income_yuan || 0) + Number(summary?.refund_yuan || 0) + Number(summary?.transfer_in_yuan || 0)
  const outflow = Number(summary?.expense_yuan || 0) + Number(summary?.transfer_out_yuan || 0)
  const totalPages = transactions?.total_pages || 1
  const AccountIcon = accountIconByType[account.type] || Building2
  return <div className="detail-page finance-account-page">
    <header className="detail-toolbar"><button type="button" onClick={onBack}><ArrowLeft size={18} />返回全部账户</button><div><button type="button" className="primary-button" onClick={() => onNewTransaction(account.id)}><CirclePlus size={16} />记入此账户</button></div></header>
    <section className="finance-account-hero">
      <div className="finance-account-identity"><span><AccountIcon size={24} /></span><div><small>{accountTypeLabel(account.type)} · {account.currency}</small><h1>{account.name}</h1><p>{account.status === 'active' ? '正在使用' : '已停用'} · 共 {account.transaction_count || 0} 笔流水</p></div></div>
      <div className="finance-account-balance"><span>当前余额</span><strong>{formatMoney(account.current_balance_yuan)}</strong><small>开始记账余额 {formatMoney(account.opening_balance_yuan)}</small></div>
    </section>
    <section className="finance-day-browser">
      <div className="finance-day-heading"><div><span className="eyebrow">DAILY ACCOUNT LOG</span><h2>{formatFullDate(selectedDate)}</h2><p>只显示“{account.name}”在这一天发生的收入、支出、退款和转账。</p></div><div className="finance-day-navigation"><button type="button" aria-label="前一天" onClick={() => chooseDate(moveISODate(selectedDate, -1))}><ChevronLeft size={17} /></button><input type="date" value={selectedDate} max={localISO()} onChange={(event) => chooseDate(event.target.value)} /><button type="button" disabled={selectedDate >= localISO()} aria-label="后一天" onClick={() => chooseDate(moveISODate(selectedDate, 1))}><ChevronRight size={17} /></button><button type="button" className="secondary-button" disabled={selectedDate === localISO()} onClick={() => chooseDate(localISO())}>今天</button></div></div>
      {loading && !detail ? <div className="finance-account-loading"><LoaderCircle className="spin" size={22} />正在读取账户明细…</div> : null}
      {error && !detail ? <div className="finance-empty finance-empty--large"><p>{error}</p><button type="button" className="secondary-button" onClick={() => load()}><RefreshCw size={15} />重试</button></div> : null}
      {detail ? <div className="finance-day-summary"><article><span>当日流入</span><strong className="is-positive">+{formatMoney(inflow)}</strong><small>收入、退款与转入</small></article><article><span>当日流出</span><strong className="is-negative">-{formatMoney(outflow)}</strong><small>支出与转出</small></article><article><span>当日变化</span><strong className={Number(summary.net_change_yuan) >= 0 ? 'is-positive' : 'is-negative'}>{Number(summary.net_change_yuan) >= 0 ? '+' : ''}{formatMoney(summary.net_change_yuan)}</strong><small>{summary.transaction_count} 笔流水</small></article><article><span>当日结束余额</span><strong>{formatMoney(detail.balance_on_date_yuan)}</strong><small>含开始记账余额</small></article></div> : null}
      {transactions?.items?.length ? <div className="finance-transaction-list finance-account-transactions">{transactions.items.map((item) => { const baseMeta = typeMeta[item.type] || typeMeta.expense; const transferIn = item.type === 'transfer' && item.to_account?.id === account.id; const tone = item.type === 'transfer' ? (transferIn ? 'income' : 'expense') : baseMeta.tone; const sign = item.type === 'transfer' ? (transferIn ? '+' : '-') : baseMeta.sign; const TypeIcon = baseMeta.icon; return <article className={`finance-transaction finance-transaction--${tone}`} key={item.id}><span className="finance-transaction__icon"><TypeIcon size={18} /></span><div><header><b>{item.purpose || item.merchant || baseMeta.label}</b><strong>{sign}{formatMoney(item.amount_yuan)}</strong></header><p className="finance-transaction__flow">{transactionFlow(item, baseMeta)}</p><small><CalendarDays size={12} />{item.local_date}{item.merchant && item.purpose ? ` · ${item.merchant}` : ''}{item.tags?.length ? ` · ${item.tags.join(' · ')}` : ''}</small></div><div className="finance-transaction__actions"><button type="button" aria-label={`编辑${item.purpose || item.merchant || '财务记录'}`} onClick={() => onEdit(item)}><Pencil size={14} /></button><button type="button" aria-label={`删除${item.purpose || item.merchant || '财务记录'}`} onClick={() => onDelete(item)}><Trash2 size={14} /></button></div></article> })}</div> : detail && !loading ? <div className="finance-empty finance-empty--large"><CalendarDays size={25} /><h3>这一天没有账户流水</h3><p>切换前后日期，或记录一笔属于“{account.name}”的收支。</p><button type="button" className="primary-button" onClick={() => onNewTransaction(account.id)}><CirclePlus size={15} />记入此账户</button></div> : null}
      {transactions ? <Pagination page={transactions.page || page} totalPages={totalPages} total={transactions.total || 0} onPage={setPage} /> : null}
      {error && detail ? <div className="inline-error">账户明细刷新暂时中断：{error}</div> : null}
    </section>
  </div>
}

export function FinanceDetail({ onBack, onDashboardReload }) {
  const [rangeMode, setRangeMode] = useState('month')
  const [custom, setCustom] = useState(() => ({ startDate: offsetDate(-89), endDate: localISO() }))
  const [customOpen, setCustomOpen] = useState(false)
  const [rangeError, setRangeError] = useState('')
  const activeRange = useMemo(() => rangeFor(rangeMode, custom), [rangeMode, custom])
  const [categories, setCategories] = useState([])
  const [accounts, setAccounts] = useState([])
  const [goals, setGoals] = useState([])
  const [insights, setInsights] = useState([])
  const [summary, setSummary] = useState(null)
  const [archive, setArchive] = useState([])
  const [transactions, setTransactions] = useState(null)
  const [filters, setFilters] = useState({ type: '', accountId: '', categoryId: '', search: '', includeDeleted: false })
  const [draftFilters, setDraftFilters] = useState({ type: '', accountId: '', categoryId: '', search: '', includeDeleted: false })
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState(false)
  const [editor, setEditor] = useState(null)
  const [deleting, setDeleting] = useState(null)
  const [setupOpen, setSetupOpen] = useState(false)
  const [budgetGoal, setBudgetGoal] = useState(null)
  const [deletingBudget, setDeletingBudget] = useState(null)
  const [selectedAccountId, setSelectedAccountId] = useState('')
  const [accountRefreshKey, setAccountRefreshKey] = useState(0)

  const loadReference = useCallback(async () => {
    const [categoryRows, accountRows, goalRows, insightRows] = await Promise.all([
      api.financeCategories(true), api.financeAccounts(true), api.financeGoals(), api.financeInsights(20),
    ])
    setCategories(categoryRows)
    setAccounts(accountRows)
    setGoals(goalRows)
    setInsights(insightRows)
  }, [])

  const loadRange = useCallback(async ({ quiet = false } = {}) => {
    if (!quiet) setLoading(true)
    try {
      const [summaryResult, transactionResult, archiveResult] = await Promise.all([
        api.financeSummary(activeRange.startDate, activeRange.endDate),
        api.financeTransactions({ ...filters, ...activeRange, page, pageSize: 12 }),
        api.financeArchive(activeRange.startDate, activeRange.endDate),
      ])
      setSummary(summaryResult)
      setTransactions(transactionResult)
      setArchive(archiveResult)
      setError('')
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      if (!quiet) setLoading(false)
    }
  }, [activeRange.startDate, activeRange.endDate, filters, page])

  useEffect(() => { loadReference().catch((requestError) => setError(requestError.message)) }, [loadReference])
  useEffect(() => { loadRange() }, [loadRange])

  function chooseRange(mode) {
    if (mode === 'custom') {
      setCustomOpen(true)
      setRangeMode('custom')
      return
    }
    setRangeMode(mode)
    setCustomOpen(false)
    setPage(1)
    setRangeError('')
  }

  function applyCustom(event) {
    event.preventDefault()
    const start = new Date(`${custom.startDate}T12:00:00`)
    const end = new Date(`${custom.endDate}T12:00:00`)
    const days = Math.round((end - start) / 86400000) + 1
    if (!custom.startDate || !custom.endDate || Number.isNaN(days) || days < 1) return setRangeError('请选择有效的开始和结束日期。')
    if (days > 3661) return setRangeError('自定义区间最长为十年。')
    setRangeMode('custom')
    setCustomOpen(false)
    setPage(1)
    setRangeError('')
  }

  async function afterMutation(message) {
    await Promise.all([loadReference(), loadRange({ quiet: true }), onDashboardReload?.()])
    setAccountRefreshKey((current) => current + 1)
    setActionError('')
    return message
  }

  async function saveTransaction(payload) {
    setBusy(true); setActionError('')
    try {
      if (editor?.id) await api.updateFinanceTransaction(editor.id, payload)
      else await api.createFinanceTransaction(payload)
      setEditor(null); setPage(1); await afterMutation()
    } catch (requestError) { setActionError(requestError.message) }
    finally { setBusy(false) }
  }

  async function deleteTransaction() {
    setBusy(true); setActionError('')
    try { await api.deleteFinanceTransaction(deleting.id); setDeleting(null); await afterMutation() }
    catch (requestError) { setActionError(requestError.message) }
    finally { setBusy(false) }
  }

  async function restoreTransaction(item) {
    setBusy(true); setActionError('')
    try { await api.restoreFinanceTransaction(item.id); await afterMutation() }
    catch (requestError) { setActionError(requestError.message) }
    finally { setBusy(false) }
  }

  async function mutateReference(action, resetForm) {
    setBusy(true); setActionError('')
    try { await action(); resetForm?.reset(); await afterMutation() }
    catch (requestError) { setActionError(requestError.message) }
    finally { setBusy(false) }
  }

  async function saveBudget(payload) {
    setBusy(true); setActionError('')
    try { await api.upsertFinanceBudget(payload); setBudgetGoal(null); await afterMutation() }
    catch (requestError) { setActionError(requestError.message) }
    finally { setBusy(false) }
  }

  async function deleteBudget() {
    setBusy(true); setActionError('')
    try { await api.deleteFinanceBudget(deletingBudget.id); setDeletingBudget(null); await afterMutation() }
    catch (requestError) { setActionError(requestError.message) }
    finally { setBusy(false) }
  }

  async function saveGoal(payload) {
    setBusy(true); setActionError('')
    try {
      if (budgetGoal?.item?.id) await api.updateFinanceGoal(budgetGoal.item.id, payload)
      else await api.createFinanceGoal(payload)
      setBudgetGoal(null); await afterMutation()
    } catch (requestError) { setActionError(requestError.message) }
    finally { setBusy(false) }
  }

  if (loading && !summary) return <div className="detail-state"><LoaderCircle className="spin" size={28} />正在整理财务数据…</div>
  if (error && !summary) return <div className="detail-state is-error"><p>{error}</p><button type="button" className="secondary-button" onClick={() => loadRange()}><RefreshCw size={16} />重新加载</button></div>

  const effectiveAccounts = accounts.filter((item) => item.status === 'active' && !item.is_placeholder)
  const effectiveCategories = categories.filter((item) => item.active)
  const totalPages = transactions?.total_pages || 1
  const totalBalance = effectiveAccounts.reduce((total, item) => total + Number(item.current_balance_yuan || 0), 0)
  const periodLabel = rangeMode === 'month' ? '本月' : rangeMode === 'year' ? '本年' : '本期'
  const selectedAccount = effectiveAccounts.find((item) => item.id === selectedAccountId)
  if (selectedAccount) return <>
    <FinanceAccountDetail
      account={selectedAccount}
      refreshKey={accountRefreshKey}
      onBack={() => setSelectedAccountId('')}
      onNewTransaction={(accountId) => { setActionError(''); setEditor({ defaultAccountId: accountId }) }}
      onEdit={(item) => { setActionError(''); setEditor(item) }}
      onDelete={(item) => { setActionError(''); setDeleting(item) }}
    />
    {editor ? <TransactionDialog transaction={editor.id ? editor : null} defaultAccountId={editor.defaultAccountId} categories={effectiveCategories} accounts={effectiveAccounts} busy={busy} error={actionError} onClose={() => setEditor(null)} onSave={saveTransaction} /> : null}
    {deleting ? <DeleteTransactionDialog transaction={deleting} busy={busy} error={actionError} onClose={() => setDeleting(null)} onConfirm={deleteTransaction} /> : null}
  </>
  return <div className="detail-page finance-page">
    <header className="detail-toolbar"><button type="button" onClick={onBack}><ArrowLeft size={18} />返回工作台</button><div><button type="button" className="secondary-button" onClick={() => { setActionError(''); setSetupOpen(true) }}><Landmark size={15} />管理账户</button><button type="button" className="secondary-button" onClick={() => { setActionError(''); setBudgetGoal({ mode: 'budget' }) }}><PiggyBank size={15} />预算与目标</button><button type="button" className="primary-button" onClick={() => { setActionError(''); effectiveAccounts.length ? setEditor({}) : setSetupOpen(true) }}><CirclePlus size={16} />记一笔</button></div></header>

    <section className="finance-hero"><div><span className="eyebrow">PERSONAL FINANCE</span><h1>财务</h1><p>看清钱在哪里，也看清钱花到哪里。</p></div><FinanceRangeControls mode={rangeMode} custom={custom} customOpen={customOpen} error={rangeError} onMode={chooseRange} onCustom={(key, value) => { setCustom((current) => ({ ...current, [key]: value })); setRangeError('') }} onApply={applyCustom} /></section>

    <section className="finance-assets-overview" aria-label="账户总资产和所选周期收支"><div className="finance-assets-total"><span>总资产</span><strong>{formatMoney(totalBalance)}</strong><small>全部启用账户的当前余额 · 人民币 CNY</small></div><div className="finance-cashflow-summary"><article className="is-income"><span>{periodLabel}收入</span><strong>{formatMoney(summary.income_yuan)}</strong><small>{summary.transaction_count} 笔流水</small></article><article className="is-expense"><span>{periodLabel}支出</span><strong>{formatMoney(summary.expense_yuan)}</strong><small>退款 {formatMoney(summary.refund_yuan)}</small></article><article className="is-net"><span>{periodLabel}结余</span><strong>{formatMoney(summary.net_yuan)}</strong><small>储蓄率 {summary.savings_rate == null ? '--' : `${Math.round(summary.savings_rate * 100)}%`}</small></article></div></section>

    <section className="finance-accounts-panel"><div className="detail-section-heading finance-account-heading"><div><span className="eyebrow">MY ACCOUNTS</span><h2>我的账户</h2><p>账户 = 钱实际存放的位置；点击账户进入独立详情页，按天查看专属流水。</p></div><button type="button" className="text-action" onClick={() => { setActionError(''); setSetupOpen(true) }}><Landmark size={14} />管理账户</button></div>{effectiveAccounts.length ? <div className="finance-account-grid">{effectiveAccounts.map((item) => { const AccountIcon = accountIconByType[item.type] || Building2; return <article className="finance-account-card" role="button" tabIndex="0" aria-label={`打开${item.name}账户详情`} key={item.id} onClick={() => setSelectedAccountId(item.id)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedAccountId(item.id) } }}><header><span><AccountIcon size={19} /></span><div><b>{item.name}</b><small>{accountTypeLabel(item.type)}</small></div><span className="finance-account-card__arrow"><ChevronRight size={17} /></span></header><strong>{formatMoney(item.current_balance_yuan)}</strong><p>当前余额</p><footer><span>累计流入 {formatMoney(Number(item.income_yuan || 0) + Number(item.refund_yuan || 0) + Number(item.transfer_in_yuan || 0))}</span><span>累计流出 {formatMoney(Number(item.expense_yuan || 0) + Number(item.transfer_out_yuan || 0))}</span></footer></article> })}</div> : <div className="finance-empty finance-empty--accounts"><WalletCards size={26} /><h3>先告诉工作台，你的钱放在哪里</h3><p>创建银行卡、微信、支付宝或现金账户，并填写开始记账时的余额。</p><button type="button" className="primary-button" onClick={() => setSetupOpen(true)}><CirclePlus size={15} />创建第一个账户</button></div>}
      {summary.unassigned_transaction_count ? <div className="finance-unassigned-notice"><span>待归类</span><p>所选周期有 {summary.unassigned_transaction_count} 笔旧流水未关联账户，不计入账户余额；编辑后选择实际账户即可补齐。</p><button type="button" onClick={() => { const next = { type: '', accountId: '', categoryId: '', search: '', includeDeleted: false }; setDraftFilters(next); setFilters(next); setPage(1) }}>查看流水<ChevronRight size={14} /></button></div> : null}
    </section>

    <section className="finance-transactions" id="finance-transactions"><div className="detail-section-heading"><div><span className="eyebrow">MONEY FLOW</span><h2>最近流水</h2><p>每一行都显示钱从哪里来、到哪里去。</p></div><span>服务端分页 · 每页 12 条</span></div><form className="finance-filters" onSubmit={(event) => { event.preventDefault(); setFilters(draftFilters); setPage(1) }}><label><span>类型</span><select value={draftFilters.type} onChange={(event) => setDraftFilters((current) => ({ ...current, type: event.target.value }))}><option value="">全部类型</option>{Object.entries(typeMeta).map(([value, item]) => <option key={value} value={value}>{item.label}</option>)}</select></label><label><span>账户</span><select value={draftFilters.accountId} onChange={(event) => setDraftFilters((current) => ({ ...current, accountId: event.target.value }))}><option value="">全部账户</option>{effectiveAccounts.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><label><span>分类</span><select value={draftFilters.categoryId} onChange={(event) => setDraftFilters((current) => ({ ...current, categoryId: event.target.value }))}><option value="">全部分类</option>{effectiveCategories.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><label className="finance-search"><span>搜索</span><div><Search size={15} /><input value={draftFilters.search} onChange={(event) => setDraftFilters((current) => ({ ...current, search: event.target.value }))} placeholder="商户、用途或备注" /></div></label><label className="finance-deleted-filter"><input type="checkbox" checked={draftFilters.includeDeleted} onChange={(event) => setDraftFilters((current) => ({ ...current, includeDeleted: event.target.checked }))} />包含已删除</label><button type="submit" className="secondary-button">应用筛选</button></form>
      {transactions?.items?.length ? <div className="finance-transaction-list">{transactions.items.map((item) => { const meta = typeMeta[item.type] || typeMeta.expense; const TypeIcon = meta.icon; return <article className={`finance-transaction finance-transaction--${meta.tone} ${item.deleted ? 'is-deleted' : ''}`} key={item.id}><span className="finance-transaction__icon"><TypeIcon size={18} /></span><div><header><b>{item.purpose || item.merchant || meta.label}</b><strong>{meta.sign}{formatMoney(item.amount_yuan)}</strong></header><p className="finance-transaction__flow">{transactionFlow(item, meta)}</p><small><CalendarDays size={12} />{item.local_date}{item.merchant && item.purpose ? ` · ${item.merchant}` : ''}{item.tags?.length ? ` · ${item.tags.join(' · ')}` : ''}{item.source === 'user' ? '' : ` · ${item.source}`}</small></div><div className="finance-transaction__actions">{item.deleted ? <button type="button" className="secondary-button" disabled={busy} onClick={() => restoreTransaction(item)}><RefreshCw size={13} />恢复</button> : <><button type="button" aria-label={`编辑${item.purpose || item.merchant || '财务记录'}`} onClick={() => { setActionError(''); setEditor(item) }}><Pencil size={14} /></button><button type="button" aria-label={`删除${item.purpose || item.merchant || '财务记录'}`} onClick={() => { setActionError(''); setDeleting(item) }}><Trash2 size={14} /></button></>}</div></article> })}</div> : <div className="finance-empty finance-empty--large"><WalletCards size={26} /><h3>没有符合条件的流水</h3><p>调整筛选条件，或记录第一笔收入和支出。</p></div>}
      <Pagination page={transactions?.page || page} totalPages={totalPages} total={transactions?.total || 0} onPage={setPage} />
    </section>

    <div className="finance-visual-grid"><section className="finance-trend-panel"><div className="detail-section-heading"><div><span className="eyebrow">CASH FLOW</span><h2>收支趋势</h2></div><span>{rangeMode === 'year' ? '年度 · 按月' : '所选周期'}</span></div><FinanceTrendChart timeline={summary.timeline} /></section><CategoryBreakdown items={summary.category_breakdown} /></div>

    <div className="finance-plan-grid"><section><div className="detail-section-heading"><div><span className="eyebrow">BUDGET</span><h2>预算进度</h2></div><button type="button" className="text-action" onClick={() => setBudgetGoal({ mode: 'budget' })}>设置预算</button></div>{summary.budgets?.length ? <div className="finance-budget-list">{summary.budgets.map((item) => <article className={item.over_budget ? 'is-over' : ''} key={item.id}><header><div><span>{item.category?.name || '总支出'}</span><small>{formatDate(item.period_start)}—{formatDate(item.period_end)}</small></div><strong>{Math.round(item.progress * 100)}%</strong><button type="button" disabled={busy} onClick={() => { setActionError(''); setDeletingBudget(item) }} aria-label={`删除${item.category?.name || '总支出'}预算`}><Trash2 size={14} /></button></header><div><i style={{ width: `${Math.min(100, item.progress * 100)}%` }} /></div><small>已用 {formatMoney(item.spent_yuan)} / {formatMoney(item.amount_yuan)}</small></article>)}</div> : <div className="finance-empty"><PiggyBank size={22} /><p>这个周期还没有预算，设置后会自动跟踪进度。</p></div>}</section><section><div className="detail-section-heading"><div><span className="eyebrow">GOALS</span><h2>储蓄目标</h2></div><button type="button" className="text-action" onClick={() => setBudgetGoal({ mode: 'goal' })}>新建目标</button></div>{goals.length ? <div className="finance-goal-list">{goals.map((item) => <article key={item.id}><header><div><b>{item.name}</b><small>{item.target_date || '未设截止日期'} · {item.status === 'active' ? '进行中' : item.status === 'paused' ? '已暂停' : '已完成'}</small></div><button type="button" onClick={() => setBudgetGoal({ mode: 'goal', item })} aria-label={`编辑${item.name}`}><Pencil size={14} /></button></header><div><i style={{ width: `${Math.min(100, item.progress * 100)}%` }} /></div><small>{formatMoney(item.current_amount_yuan)} / {formatMoney(item.target_amount_yuan)}</small></article>)}</div> : <div className="finance-empty"><PiggyBank size={22} /><p>创建一个储蓄目标，进度会长期保留。</p></div>}</section></div>

    <section className="finance-archive"><div className="detail-section-heading"><div><span className="eyebrow">MONTHLY ARCHIVE</span><h2>按月归档</h2></div><span>{archive.length} 个月</span></div>{archive.length ? <div className="finance-archive-grid">{archive.map((item) => <article key={item.month}><header><b>{item.month.replace('-', ' 年 ')} 月</b><span className={Number(item.net) >= 0 ? 'is-positive' : 'is-negative'}>{Number(item.net) >= 0 ? '结余' : '超支'} {formatMoney(item.net_yuan)}</span></header><div><span>收入 <b>{formatMoney(item.income_yuan)}</b></span><span>支出 <b>{formatMoney(item.expense_yuan)}</b></span><span>退款 <b>{formatMoney(item.refund_yuan)}</b></span></div></article>)}</div> : <div className="finance-empty"><BarChart3 size={22} /><p>所选区间还没有可归档的月份。</p></div>}</section>

    <section className="finance-insights"><div className="detail-section-heading"><div><span className="eyebrow">AI AGENT</span><h2>财务建议</h2></div><span>{insights.length} 条历史建议</span></div>{insights.length ? <div className="finance-insight-list">{insights.map((item) => <article key={item.id}><span><Sparkles size={17} /></span><div><small>{item.period_start}—{item.period_end} · {item.source === 'hermes' ? 'AI Agent' : '手动记录'}</small><h3>{item.finding}</h3><p><b>依据：</b>{item.evidence}</p>{item.risk ? <p><b>风险：</b>{item.risk}</p> : null}<p className="is-action"><b>下一步：</b>{item.action}</p>{item.next_goal ? <em>{item.next_goal}</em> : null}</div></article>)}</div> : <div className="finance-empty finance-empty--large"><Sparkles size={25} /><h3>AI Agent 还没有生成财务建议</h3><p>持续记录收支后，AI Agent 可以通过现有财务工具保存分析、风险和下一步目标。</p></div>}</section>

    {error ? <div className="inline-error">数据刷新暂时中断：{error}</div> : null}
    {actionError && !editor && !deleting && !deletingBudget && !setupOpen && !budgetGoal ? <div className="inline-error">{actionError}</div> : null}
    {editor ? <TransactionDialog transaction={editor.id ? editor : null} defaultAccountId={editor.defaultAccountId} categories={effectiveCategories} accounts={effectiveAccounts} busy={busy} error={actionError} onClose={() => setEditor(null)} onSave={saveTransaction} /> : null}
    {deleting ? <DeleteTransactionDialog transaction={deleting} busy={busy} error={actionError} onClose={() => setDeleting(null)} onConfirm={deleteTransaction} /> : null}
    {deletingBudget ? <DeleteBudgetDialog budget={deletingBudget} busy={busy} error={actionError} onClose={() => setDeletingBudget(null)} onConfirm={deleteBudget} /> : null}
    {setupOpen ? <FinanceSetupDialog categories={categories} accounts={accounts} busy={busy} error={actionError} onClose={() => setSetupOpen(false)} onCreateCategory={(payload, form) => mutateReference(() => api.createFinanceCategory(payload), form)} onUpdateCategory={(id, payload) => mutateReference(() => api.updateFinanceCategory(id, payload))} onCreateAccount={(payload, form) => mutateReference(() => api.createFinanceAccount(payload), form)} onUpdateAccount={(id, payload) => mutateReference(() => api.updateFinanceAccount(id, payload))} /> : null}
    {budgetGoal ? <BudgetGoalDialog mode={budgetGoal.mode} item={budgetGoal.item} categories={categories} range={activeRange} busy={busy} error={actionError} onClose={() => setBudgetGoal(null)} onSaveBudget={saveBudget} onSaveGoal={saveGoal} /> : null}
  </div>
}
