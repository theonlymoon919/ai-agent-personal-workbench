import {
  ArrowDownRight,
  ArrowLeft,
  ArrowUpRight,
  CalendarDays,
  Camera,
  ChevronLeft,
  ChevronRight,
  Dumbbell,
  Flame,
  GlassWater,
  Image as ImageIcon,
  LoaderCircle,
  Pencil,
  RefreshCw,
  RotateCcw,
  Scale,
  Sparkles,
  Trash2,
  Utensils,
  Weight,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, workbenchAssetUrl } from '../api.js'

const rangeOptions = [
  { days: 1, label: '日' },
  { days: 7, label: '周' },
  { days: 30, label: '月' },
  { days: 90, label: '季度' },
  { days: 365, label: '年' },
]
const metricConfig = {
  weight_kg: { label: '体重', unit: 'kg', color: '#0d4a38', icon: Weight, type: 'line' },
  water_ml: { label: '饮水', unit: 'ml', color: '#5c8c78', icon: GlassWater, type: 'bar' },
  calories_kcal: { label: '热量', unit: 'kcal', color: '#c8754d', icon: Flame, type: 'bar' },
  exercise_kcal: { label: '运动', unit: 'kcal', color: '#6e7596', icon: Dumbbell, type: 'bar' },
}

function formatDay(value, short = false) {
  const target = new Date(`${value}T12:00:00`)
  return new Intl.DateTimeFormat('zh-CN', short ? { month: 'numeric', day: 'numeric' } : { month: 'long', day: 'numeric' }).format(target)
}

function localDateOffset(days = 0) {
  const target = new Date()
  target.setHours(12, 0, 0, 0)
  target.setDate(target.getDate() + days)
  const year = target.getFullYear()
  const month = String(target.getMonth() + 1).padStart(2, '0')
  const day = String(target.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function rangeDates(range) {
  if (range?.startDate && range?.endDate) return range
  return { startDate: localDateOffset(-Math.max(0, Number(range?.days || 30) - 1)), endDate: localDateOffset() }
}

function HealthRangeControls({ range, customDates, customOpen, error, onPreset, onToggleCustom, onCustomChange, onApplyCustom }) {
  return (
    <div className="range-controls">
      <div className="range-tabs" aria-label="历史范围">
        {rangeOptions.map((option) => <button type="button" key={option.days} aria-pressed={range.days === option.days} className={range.days === option.days ? 'is-active' : ''} onClick={() => onPreset(option.days)}>{option.label}</button>)}
        <button type="button" aria-expanded={customOpen} aria-pressed={!range.days} className={!range.days ? 'is-active' : ''} onClick={onToggleCustom}>自定义</button>
      </div>
      {customOpen ? <form className="custom-range-form" onSubmit={onApplyCustom}>
        <label><span>开始日期</span><input type="date" name="start_date" value={customDates.startDate} min={localDateOffset(-3660)} max={customDates.endDate || localDateOffset()} onChange={(event) => onCustomChange('startDate', event.target.value)} /></label>
        <label><span>结束日期</span><input type="date" name="end_date" value={customDates.endDate} min={customDates.startDate || localDateOffset(-3660)} max={localDateOffset()} onChange={(event) => onCustomChange('endDate', event.target.value)} /></label>
        <button type="submit" className="primary-button">应用周期</button>
        {error ? <p>{error}</p> : null}
      </form> : null}
    </div>
  )
}

function formatValue(value, metric) {
  if (value == null) return '--'
  return metric === 'weight_kg' ? Number(value).toFixed(1) : Math.round(value).toLocaleString('zh-CN')
}

function TrendChart({ points, metric }) {
  const config = metricConfig[metric]
  const width = 720
  const height = 235
  const margin = { top: 25, right: 32, bottom: 35, left: 48 }
  const plotWidth = width - margin.left - margin.right
  const plotHeight = height - margin.top - margin.bottom
  const numericValues = points.map((point) => point[metric]).filter((value) => value != null && Number(value) > 0).map(Number)
  const floor = metric === 'weight_kg' && numericValues.length ? Math.floor((Math.min(...numericValues) - 0.5) * 2) / 2 : 0
  const fallbackMax = metric === 'water_ml' ? 2000 : metric === 'calories_kcal' ? 1800 : metric === 'exercise_kcal' ? 300 : floor + 1
  const ceiling = numericValues.length ? Math.max(...numericValues, fallbackMax) : fallbackMax
  const top = metric === 'weight_kg' ? Math.ceil((ceiling + 0.5) * 2) / 2 : Math.ceil((ceiling * 1.12) / 100) * 100
  const range = Math.max(top - floor, 1)
  const x = (index) => margin.left + (points.length <= 1 ? plotWidth / 2 : (index / (points.length - 1)) * plotWidth)
  const y = (value) => margin.top + plotHeight - ((Number(value) - floor) / range) * plotHeight
  const validLinePoints = points.map((point, index) => ({ point, index })).filter(({ point }) => point[metric] != null && Number(point[metric]) > 0)
  const linePath = validLinePoints.map(({ point, index }, position) => `${position ? 'L' : 'M'} ${x(index)} ${y(point[metric])}`).join(' ')
  const barWidth = Math.max(3, Math.min(16, plotWidth / Math.max(points.length * 1.7, 1)))
  const labelIndexes = [...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])]
  const lastPoint = points.length ? points[points.length - 1] : undefined
  const ariaLabel = `${formatDay(points[0]?.date || new Date().toISOString().slice(0, 10))}至${formatDay(lastPoint?.date || new Date().toISOString().slice(0, 10))}的${config.label}趋势`

  return (
    <svg className="health-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel} preserveAspectRatio="none">
      {[0, 0.5, 1].map((ratio) => {
        const gridY = margin.top + plotHeight * ratio
        const gridValue = top - range * ratio
        return <g key={ratio}><line x1={margin.left} x2={width - margin.right} y1={gridY} y2={gridY} className="chart-grid" /><text x={margin.left - 10} y={gridY + 4} textAnchor="end" className="chart-axis-label">{formatValue(gridValue, metric)}</text></g>
      })}
      {config.type === 'bar' ? points.map((point, index) => {
        const value = Number(point[metric] || 0)
        const barY = y(value)
        return <rect key={point.date} x={x(index) - barWidth / 2} y={barY} width={barWidth} height={Math.max(0, margin.top + plotHeight - barY)} rx={barWidth / 2} fill={config.color} opacity={value ? 0.82 : 0.12} />
      }) : <>
        {linePath ? <path d={linePath} fill="none" stroke={config.color} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" /> : null}
        {validLinePoints.map(({ point, index }) => <circle key={point.date} cx={x(index)} cy={y(point[metric])} r="4" fill="#fffefc" stroke={config.color} strokeWidth="2.5" />)}
      </>}
      {labelIndexes.map((index) => <text key={index} x={x(index)} y={height - 10} textAnchor={index === 0 ? 'start' : index === points.length - 1 ? 'end' : 'middle'} className="chart-axis-label">{formatDay(points[index]?.date, true)}</text>)}
      {!numericValues.length ? <text x={width / 2} y={height / 2} textAnchor="middle" className="chart-empty">这个时间段还没有{config.label}记录</text> : null}
    </svg>
  )
}

function MetricSummary({ history }) {
  const metrics = history.metrics
  const change = metrics.weight_change_kg
  const ChangeIcon = change != null && change > 0 ? ArrowUpRight : ArrowDownRight
  return (
    <div className="health-summary-grid">
      <article><span>最新体重</span><strong>{metrics.latest_weight_kg ?? '--'}<small> kg</small></strong>{change != null ? <em className={change > 0 ? 'is-up' : 'is-down'}><ChangeIcon size={13} />{Math.abs(change).toFixed(1)} kg</em> : <em>需要至少2次记录</em>}</article>
      <article><span>日均饮水</span><strong>{metrics.average_water_ml.toLocaleString('zh-CN')}<small> ml</small></strong><em>按有记录的日期计算</em></article>
      <article><span>日均热量</span><strong>{metrics.average_calories_kcal.toLocaleString('zh-CN')}<small> kcal</small></strong><em>来自已分析饮食</em></article>
      <article><span>运动消耗</span><strong>{metrics.exercise_total_kcal.toLocaleString('zh-CN')}<small> kcal</small></strong><em>{history.range_days}天累计</em></article>
    </div>
  )
}

const adviceSectionIcons = {
  overall: Sparkles,
  diet: Utensils,
  hydration: GlassWater,
  exercise: Dumbbell,
}

function friendlyRecordTitle(record) {
  const title = String(record?.title || '').trim()
  if (!title || /^[a-f0-9]{24,}\.(?:jpe?g|png|webp|heic)$/i.test(title)) {
    return `${record?.meal_label || '健康'}记录`
  }
  return title
}

function RecordImage({ record }) {
  const title = friendlyRecordTitle(record)
  return (
    <a className="daily-record__image" href={workbenchAssetUrl(record.asset)} target="_blank" rel="noreferrer" aria-label={`打开${title}原图`}>
      <span><ImageIcon size={22} />查看原图</span>
      <img loading="lazy" src={workbenchAssetUrl(record.asset)} alt={title} onError={(event) => { event.currentTarget.style.display = 'none' }} />
    </a>
  )
}

function RecordActions({ record, onEdit, onDelete }) {
  return <div className="record-actions"><button type="button" onClick={() => onEdit(record)}><Pencil size={13} />修改</button><button type="button" className="is-danger" onClick={() => onDelete(record)}><Trash2 size={13} />删除</button></div>
}

function MealRecord({ record, onEdit, onDelete }) {
  const title = friendlyRecordTitle(record)
  return (
    <article className="daily-meal-record">
      <RecordImage record={record} />
      <div className="daily-record__body">
        <div className="daily-record__heading"><span><Utensils size={14} />{record.meal_label || '饮食记录'}</span>{record.calories_kcal != null ? <strong>{record.calories_kcal} kcal</strong> : <em>待估算</em>}</div>
        <h3>{title}</h3>
        <p>{record.analysis_summary || (record.analysis_status === 'queued' ? '等待 AI Agent 分析这餐的食物组成和热量。' : '暂无分析内容。')}</p>
        {record.analysis_advice ? <div className="meal-specific-advice"><b>这一餐的建议</b><p>{record.analysis_advice}</p></div> : null}
        <small>{record.analysis_status === 'analyzed' ? 'AI Agent 已分析' : '等待分析'} · 点击图片查看原图</small>
        <RecordActions record={record} onEdit={onEdit} onDelete={onDelete} />
      </div>
    </article>
  )
}

function DailyAdviceSummary({ advice, hasRecords }) {
  const sections = advice?.sections || []
  return (
    <section className={`daily-advice-summary daily-advice-summary--${advice?.status || 'neutral'}`}>
      <div className="daily-advice-summary__title"><span><Sparkles size={17} /></span><div><small>AI AGENT</small><h3>全天总结</h3></div></div>
      {sections.length ? <div className="daily-advice-sections">{sections.map((section) => {
        const AdviceIcon = adviceSectionIcons[section.key] || Sparkles
        return <article key={section.key}><span><AdviceIcon size={15} /></span><div><b>{section.label}</b><p>{section.content}</p></div></article>
      })}</div> : <p className="daily-advice-empty">{hasRecords ? '每餐分析完成后，AI Agent 会结合全天饮食、饮水和运动生成这里的总结。' : '这一天还没有可总结的健康记录。'}</p>}
    </section>
  )
}

function SupplementalRecords({ title, records, kind, onEdit, onDelete }) {
  if (!records?.length) return null
  const Icon = kind === 'exercise' ? Dumbbell : Scale
  return (
    <section className="supplemental-records">
      <h3><Icon size={16} />{title}</h3>
      {records.map((record) => <article key={record.id}><RecordImage record={record} /><div><b>{record.title}</b><p>{record.analysis_summary || (record.analysis_status === 'queued' ? '等待 AI Agent 分析。' : '暂无分析内容。')}</p>{record.analysis_advice ? <small>建议：{record.analysis_advice}</small> : null}<RecordActions record={record} onEdit={onEdit} onDelete={onDelete} /></div></article>)}
    </section>
  )
}

function DailyHealthCards({ cards, onEdit, onDelete }) {
  return (
    <section className="health-timeline daily-health-timeline">
      <div className="detail-section-heading"><div><span className="eyebrow">DAILY LOG</span><h2>每日饮食与运动</h2></div><span>{cards.length} 天</span></div>
      {cards.length ? <div className="daily-health-card-list">{cards.map((card) => <article className="daily-health-card" key={card.date}>
        <header>
          <div className="daily-health-card__date"><span><CalendarDays size={17} /></span><div><h3>{formatDay(card.date)}</h3><small>{new Intl.DateTimeFormat('zh-CN', { weekday: 'long' }).format(new Date(`${card.date}T12:00:00`))}</small></div></div>
          <div className="daily-health-card__metrics"><span>{card.meals.length} 餐</span><span>{card.calories_kcal || 0} kcal</span><span>饮水 {card.water_ml || 0} ml</span><span>运动 {card.exercise_kcal || 0} kcal</span></div>
        </header>
        <div className="daily-health-card__grid">
          <section className="daily-meals"><h3><Utensils size={16} />当天饮食</h3>{card.meals.length ? card.meals.map((record) => <MealRecord key={record.id} record={record} onEdit={onEdit} onDelete={onDelete} />) : <p className="daily-section-empty">这一天没有上传饮食照片。</p>}</section>
          <div className="daily-summary-column">
            <DailyAdviceSummary advice={card.daily_advice} hasRecords={Boolean(card.meals.length || card.exercise_records.length)} />
            <SupplementalRecords title="运动记录" records={card.exercise_records} kind="exercise" onEdit={onEdit} onDelete={onDelete} />
            <SupplementalRecords title="体重记录" records={card.other_records} kind="weight" onEdit={onEdit} onDelete={onDelete} />
          </div>
        </div>
      </article>)}</div> : <div className="health-empty"><ImageIcon size={25} /><h3>还没有每日记录</h3><p>上传饮食、体重秤或运动报告后，会按日期归入同一张卡片。</p></div>}
    </section>
  )
}

function MonthlyHealthArchive({ months }) {
  return <section className="health-monthly-archive">
    <div className="detail-section-heading"><div><span className="eyebrow">MONTHLY ARCHIVE</span><h2>较早记录按月归档</h2></div><span>{months?.length || 0} 个月</span></div>
    {months?.length ? <div className="health-month-grid">{months.map((item) => <article key={item.month}>
      <header><div><CalendarDays size={16} /><b>{item.month.replace('-', ' 年 ')} 月</b></div><span>{item.recorded_days} 个记录日</span></header>
      <div><span>饮食 <b>{item.meal_count}</b></span><span>运动 <b>{item.exercise_count}</b></span><span>图片 <b>{item.record_count}</b></span></div>
      <footer><span>饮水 {Number(item.water_ml || 0).toLocaleString('zh-CN')} ml</span><span>运动 {Number(item.exercise_kcal || 0).toLocaleString('zh-CN')} kcal</span>{item.latest_weight_kg != null ? <span>最近体重 {item.latest_weight_kg} kg</span> : null}</footer>
    </article>)}</div> : <div className="health-empty"><CalendarDays size={24} /><h3>还没有较早月份</h3><p>最近 14 天保留完整卡片，更早记录会在这里按月压缩显示。</p></div>}
  </section>
}

function HealthRecordPagination({ data, kind, onKind, onPage, onEdit, onDelete }) {
  const labels = { meal: '饮食', exercise: '运动', weight_photo: '体重' }
  return <section className="health-record-browser">
    <div className="detail-section-heading"><div><span className="eyebrow">PAGED DETAILS</span><h2>全部健康明细</h2></div><span>服务端分页 · 每页 {data?.page_size || 8} 条</span></div>
    <div className="health-record-filters" role="group" aria-label="健康明细类型"><button type="button" className={!kind ? 'is-active' : ''} aria-pressed={!kind} onClick={() => onKind('')}>全部</button>{Object.entries(labels).map(([value, label]) => <button type="button" key={value} className={kind === value ? 'is-active' : ''} aria-pressed={kind === value} onClick={() => onKind(value)}>{label}</button>)}</div>
    {data?.items?.length ? <div className="health-record-page-list">{data.items.map((record) => <article key={record.id}>
      <a href={workbenchAssetUrl(record.asset)} target="_blank" rel="noreferrer"><img loading="lazy" src={workbenchAssetUrl(record.thumbnail_asset)} alt={friendlyRecordTitle(record)} /></a>
      <div><header><b>{friendlyRecordTitle(record)}</b><span>{labels[record.kind] || '健康记录'}</span></header><p>{record.analysis_summary || (record.analysis_status === 'queued' ? '等待 AI Agent 分析。' : '暂无分析内容。')}</p><small>{record.record_date} · {record.analysis_status === 'analyzed' ? '已分析' : '处理中'}</small></div>
      <RecordActions record={record} onEdit={onEdit} onDelete={onDelete} />
    </article>)}</div> : <div className="health-empty"><ImageIcon size={24} /><h3>没有符合条件的健康明细</h3><p>调整时间范围或记录类型后再查看。</p></div>}
    <nav className="server-pagination" aria-label="健康明细分页"><button type="button" disabled={!data || data.page <= 1} onClick={() => onPage(data.page - 1)}><ChevronLeft size={15} />上一页</button><span>第 {data?.page || 1} / {data?.total_pages || 1} 页 · 共 {data?.total || 0} 条</span><button type="button" disabled={!data || data.page >= data.total_pages} onClick={() => onPage(data.page + 1)}>下一页<ChevronRight size={15} /></button></nav>
  </section>
}

const mealOptions = [
  ['breakfast', '早餐'], ['lunch', '午餐'], ['afternoon_tea', '下午茶'],
  ['dinner', '晚餐'], ['snack', '零食'], ['late_night', '夜宵'],
]

function HealthRecordEditDialog({ record, busy, error, onClose, onSave }) {
  return <div className="dialog-backdrop" role="presentation"><section className="record-dialog compact-dialog" role="dialog" aria-modal="true" aria-labelledby="edit-health-title">
    <header><div><span className="eyebrow">CORRECT RECORD</span><h2 id="edit-health-title">修改健康记录</h2></div><button type="button" onClick={onClose} aria-label="关闭"><X size={19} /></button></header>
    <form onSubmit={(event) => { event.preventDefault(); const values = new FormData(event.currentTarget); onSave({ record_date: values.get('record_date'), ...(record.kind === 'meal' ? { meal_slot: values.get('meal_slot') } : {}) }) }}>
      <p className="dialog-helper">修改后会立即刷新图表；AI Agent 会收到任务，重新整理受影响日期的全天建议。</p>
      <label><span>记录日期</span><input type="date" name="record_date" defaultValue={record.record_date} max={localDateOffset()} required /></label>
      {record.kind === 'meal' ? <label><span>餐次</span><select name="meal_slot" defaultValue={record.meal_slot || 'lunch'}>{mealOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label> : null}
      {error ? <p className="form-error">{error}</p> : null}
      <div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>取消</button><button type="submit" className="primary-button" disabled={busy}>{busy ? '正在保存…' : '保存修改'}</button></div>
    </form>
  </section></div>
}

function HealthDeleteDialog({ record, busy, error, onClose, onConfirm }) {
  return <div className="dialog-backdrop" role="presentation"><section className="record-dialog compact-dialog" role="alertdialog" aria-modal="true" aria-labelledby="delete-health-title">
    <header><div><span className="eyebrow">RECYCLE BIN</span><h2 id="delete-health-title">移入回收站？</h2></div><button type="button" onClick={onClose} aria-label="关闭"><X size={19} /></button></header>
    <div className="confirm-dialog-body"><p>“{friendlyRecordTitle(record)}”会从图表和每日卡片中隐藏，但记录和图片暂不会永久删除，之后可以恢复。</p>{error ? <p className="form-error">{error}</p> : null}<div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>取消</button><button type="button" className="danger-button" disabled={busy} onClick={onConfirm}>{busy ? '正在处理…' : '移入回收站'}</button></div></div>
  </section></div>
}

function HealthRecycleDialog({ records, loading, busyId, error, onClose, onRestore }) {
  return <div className="dialog-backdrop" role="presentation"><section className="record-dialog recycle-dialog" role="dialog" aria-modal="true" aria-labelledby="health-trash-title">
    <header><div><span className="eyebrow">RECYCLE BIN</span><h2 id="health-trash-title">健康记录回收站</h2></div><button type="button" onClick={onClose} aria-label="关闭"><X size={19} /></button></header>
    <div className="recycle-dialog__body">{loading ? <div className="detail-state"><LoaderCircle className="spin" size={22} />正在读取…</div> : records.length ? records.map((record) => <article key={record.id}><div><b>{friendlyRecordTitle(record)}</b><span>{record.record_date} · {record.meal_label || (record.kind === 'exercise' ? '运动' : '体重')}</span></div><button type="button" className="secondary-button" disabled={busyId === record.id} onClick={() => onRestore(record)}><RotateCcw size={14} />{busyId === record.id ? '恢复中' : '恢复'}</button></article>) : <div className="health-empty"><Trash2 size={24} /><h3>回收站是空的</h3><p>这里会保留你临时删除的健康记录。</p></div>}{error ? <p className="form-error">{error}</p> : null}</div>
  </section></div>
}

export function HealthHistoryDetail({ refreshToken, onBack, onRecord }) {
  const [range, setRange] = useState({ days: 30 })
  const [customDates, setCustomDates] = useState(() => ({ startDate: localDateOffset(-89), endDate: localDateOffset() }))
  const [customOpen, setCustomOpen] = useState(false)
  const [rangeError, setRangeError] = useState('')
  const [metric, setMetric] = useState('weight_kg')
  const [history, setHistory] = useState(null)
  const [recordDetails, setRecordDetails] = useState(null)
  const [recordPage, setRecordPage] = useState(1)
  const [recordKind, setRecordKind] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editingRecord, setEditingRecord] = useState(null)
  const [deletingRecord, setDeletingRecord] = useState(null)
  const [trashOpen, setTrashOpen] = useState(false)
  const [trashRecords, setTrashRecords] = useState([])
  const [trashLoading, setTrashLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [busyId, setBusyId] = useState('')
  const [actionError, setActionError] = useState('')

  const load = useCallback(async ({ quiet = false } = {}) => {
    if (!quiet) setLoading(true)
    try {
      setHistory(await api.healthHistory(range))
      setError('')
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      if (!quiet) setLoading(false)
    }
  }, [range])

  const loadDetails = useCallback(async () => {
    try {
      const dates = rangeDates(range)
      setRecordDetails(await api.healthRecordsPage({ ...dates, kind: recordKind, page: recordPage, pageSize: 8 }))
    } catch (requestError) {
      setError(requestError.message)
    }
  }, [range, recordKind, recordPage])

  useEffect(() => { load() }, [load])
  useEffect(() => { loadDetails() }, [loadDetails])
  useEffect(() => { if (history && refreshToken) Promise.all([load({ quiet: true }), loadDetails()]) }, [refreshToken])

  const recentRows = useMemo(() => history?.points.filter((point) => point.has_record).slice(-7).reverse() || [], [history])

  if (loading && !history) return <div className="detail-state"><LoaderCircle className="spin" size={28} />正在整理健康历史…</div>
  if (error && !history) return <div className="detail-state is-error"><p>{error}</p><button type="button" className="secondary-button" onClick={() => load()}><RefreshCw size={16} />重新加载</button></div>

  const config = metricConfig[metric]
  const Icon = config.icon
  const latestPoint = [...history.points].reverse().find((point) => Number(point[metric]) > 0)

  function choosePreset(days) {
    setRange({ days })
    setRecordPage(1)
    setCustomOpen(false)
    setRangeError('')
  }

  function updateCustomDate(key, value) {
    setCustomDates((current) => ({ ...current, [key]: value }))
    setRangeError('')
  }

  function applyCustomRange(event) {
    event.preventDefault()
    const submitted = new FormData(event.currentTarget)
    const startDate = String(submitted.get('start_date') || '')
    const endDate = String(submitted.get('end_date') || '')
    const start = new Date(`${startDate}T12:00:00`)
    const end = new Date(`${endDate}T12:00:00`)
    const inclusiveDays = Math.round((end - start) / 86400000) + 1
    if (!startDate || !endDate || Number.isNaN(inclusiveDays)) {
      setRangeError('请选择完整的开始和结束日期。')
      return
    }
    if (inclusiveDays < 1) {
      setRangeError('开始日期不能晚于结束日期。')
      return
    }
    if (inclusiveDays > 3661) {
      setRangeError('一次最多查看十年（3661天）。')
      return
    }
    setCustomDates({ startDate, endDate })
    setRange({ startDate, endDate })
    setRecordPage(1)
    setCustomOpen(false)
    setRangeError('')
  }

  async function saveRecord(payload) {
    setBusy(true); setActionError('')
    try { await api.updateHealthRecord(editingRecord.id, payload); setEditingRecord(null); await Promise.all([load({ quiet: true }), loadDetails()]) }
    catch (requestError) { setActionError(requestError.message) }
    finally { setBusy(false) }
  }

  async function deleteRecord() {
    setBusy(true); setActionError('')
    try { await api.deleteHealthRecord(deletingRecord.id); setDeletingRecord(null); await Promise.all([load({ quiet: true }), loadDetails()]) }
    catch (requestError) { setActionError(requestError.message) }
    finally { setBusy(false) }
  }

  async function openTrash() {
    setTrashOpen(true); setTrashLoading(true); setActionError('')
    try { setTrashRecords(await api.deletedHealthRecords()) }
    catch (requestError) { setActionError(requestError.message) }
    finally { setTrashLoading(false) }
  }

  async function restoreRecord(record) {
    setBusyId(record.id); setActionError('')
    try { await api.restoreHealthRecord(record.id); setTrashRecords((current) => current.filter((item) => item.id !== record.id)); await Promise.all([load({ quiet: true }), loadDetails()]) }
    catch (requestError) { setActionError(requestError.message) }
    finally { setBusyId('') }
  }

  return (
    <div className="detail-page health-history-page">
      <header className="detail-toolbar">
        <button type="button" onClick={onBack}><ArrowLeft size={18} />返回健康追踪</button>
        <div><button type="button" className="secondary-button" onClick={openTrash}><Trash2 size={16} />回收站</button><button type="button" className="secondary-button" onClick={() => onRecord('meal')}><Camera size={16} />拍照记录</button></div>
      </header>

      <section className="health-history-hero">
        <div><span className="eyebrow">HEALTH HISTORY</span><h1>健康变化</h1><p>所有数值和图片都保存在你的私有空间，AI Agent 的分析结果会自动同步到这里。</p></div>
        <HealthRangeControls
          range={range}
          customDates={customDates}
          customOpen={customOpen}
          error={rangeError}
          onPreset={choosePreset}
          onToggleCustom={() => { setCustomOpen((current) => !current); setRangeError('') }}
          onCustomChange={updateCustomDate}
          onApplyCustom={applyCustomRange}
        />
      </section>

      <MetricSummary history={history} />

      <section className="health-chart-panel">
        <div className="metric-tabs" aria-label="健康指标">{Object.entries(metricConfig).map(([key, item]) => { const TabIcon = item.icon; return <button type="button" key={key} aria-pressed={metric === key} className={metric === key ? 'is-active' : ''} onClick={() => setMetric(key)}><TabIcon size={16} />{item.label}</button> })}</div>
        <div className="chart-insight"><span className="chart-insight__icon" style={{ color: config.color }}><Icon size={21} /></span><div><span>{config.label}趋势</span><strong>{latestPoint ? `${formatValue(latestPoint[metric], metric)} ${config.unit}` : '暂无记录'}</strong></div><small>{history.start_date} 至 {history.end_date}</small></div>
        <TrendChart points={history.points} metric={metric} />
        <div className="recent-health-values" aria-label="最近健康数值">{recentRows.length ? recentRows.map((point) => <div key={point.date}><strong>{formatDay(point.date)}</strong><span>{formatValue(point[metric], metric)} {point[metric] ? config.unit : ''}</span></div>) : <p>这个时间段还没有记录。</p>}</div>
      </section>

      <DailyHealthCards cards={history.daily_cards || []} onEdit={(record) => { setActionError(''); setEditingRecord(record) }} onDelete={(record) => { setActionError(''); setDeletingRecord(record) }} />
      <MonthlyHealthArchive months={history.monthly_archive || []} />
      <HealthRecordPagination data={recordDetails} kind={recordKind} onKind={(value) => { setRecordKind(value); setRecordPage(1) }} onPage={setRecordPage} onEdit={(record) => { setActionError(''); setEditingRecord(record) }} onDelete={(record) => { setActionError(''); setDeletingRecord(record) }} />
      {error ? <div className="inline-error">实时更新暂时中断：{error}</div> : null}
      {editingRecord ? <HealthRecordEditDialog record={editingRecord} busy={busy} error={actionError} onClose={() => setEditingRecord(null)} onSave={saveRecord} /> : null}
      {deletingRecord ? <HealthDeleteDialog record={deletingRecord} busy={busy} error={actionError} onClose={() => setDeletingRecord(null)} onConfirm={deleteRecord} /> : null}
      {trashOpen ? <HealthRecycleDialog records={trashRecords} loading={trashLoading} busyId={busyId} error={actionError} onClose={() => setTrashOpen(false)} onRestore={restoreRecord} /> : null}
    </div>
  )
}
