import { BookOpen, Camera, CheckSquare2, Dumbbell, GlassWater, GraduationCap, Scale, Upload, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'

const dialogMeta = {
  task: { title: '添加今日任务', description: '按重要和紧急程度放入四象限。', icon: CheckSquare2 },
  water: { title: '记录饮水', description: '按实际毫升记录，不强制按 8 杯计算。', icon: GlassWater },
  meal: { title: '拍照记录饮食', description: '图片会保存到你的私有空间，等待 AI Agent 估算热量。', icon: Camera },
  weight: { title: '记录体重', description: '可以手动输入，也可以上传电子秤照片。', icon: Scale },
  exercise: { title: '上传运动报告', description: '支持小米运动或其他运动报告截图。', icon: Dumbbell },
  growth: { title: '新建学习计划', description: 'AI Agent 会据此补充入门路径和每日计划。', icon: GraduationCap },
  library: { title: '加入书单或影单', description: '读完或看完后，可以继续补充心得和状态。', icon: BookOpen },
}

const mealSlotOptions = [
  { value: 'breakfast', label: '早餐' },
  { value: 'lunch', label: '午餐' },
  { value: 'afternoon_tea', label: '下午茶' },
  { value: 'dinner', label: '晚餐' },
  { value: 'snack', label: '零食' },
  { value: 'late_night', label: '夜宵' },
]

function localDateValue() {
  const now = new Date()
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}

function defaultMealSlot() {
  const hour = new Date().getHours()
  if (hour < 10) return 'breakfast'
  if (hour < 15) return 'lunch'
  if (hour < 18) return 'afternoon_tea'
  if (hour < 21) return 'dinner'
  return 'late_night'
}

export function RecordDialog({ type, data, onClose, onComplete }) {
  const meta = dialogMeta[type]
  const Icon = meta.icon
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [file, setFile] = useState(null)
  const [title, setTitle] = useState('')
  const [quadrant, setQuadrant] = useState('important_not_urgent')
  const [dueAt, setDueAt] = useState('')
  const [recurrence, setRecurrence] = useState('none')
  const [water, setWater] = useState(data?.health?.cup_ml || 250)
  const [weight, setWeight] = useState('')
  const [goal, setGoal] = useState('')
  const [libraryKind, setLibraryKind] = useState('book')
  const [recordDate, setRecordDate] = useState(localDateValue)
  const [mealSlot, setMealSlot] = useState(defaultMealSlot)
  const preview = useMemo(() => file ? URL.createObjectURL(file) : '', [file])

  useEffect(() => () => preview && URL.revokeObjectURL(preview), [preview])
  useEffect(() => {
    const closeOnEscape = (event) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onClose])

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      let record = null
      if (type === 'task') record = await api.createTask({ title, quadrant, due_at: dueAt ? `${dueAt}:00` : null, note: '', recurrence })
      if (type === 'water') record = await api.recordWater(Number(water))
      if (type === 'meal' || type === 'exercise') record = await api.upload(type, file, { recordDate, mealSlot: type === 'meal' ? mealSlot : '' })
      if (type === 'weight') {
        if (weight) record = await api.recordWeight(Number(weight), recordDate)
        if (file) record = await api.upload('weight', file, { recordDate })
      }
      if (type === 'growth') record = await api.createLearningPlan({ name: title, goal })
      if (type === 'library') record = await api.createLibraryItem({ title, kind: libraryKind, reason: goal })
      const messages = {
        task: '任务已添加到四象限', water: `已记录 ${water} ml 饮水`, meal: `${recordDate} ${mealSlotOptions.find((item) => item.value === mealSlot)?.label || '饮食'}已保存`,
        weight: '体重记录已保存', exercise: '运动报告已保存', growth: '学习计划已创建', library: '已加入书单或影单',
      }
      await onComplete(messages[type], { type, record })
    } catch (submitError) {
      setError(submitError.message)
    } finally {
      setBusy(false)
    }
  }

  const requiresFile = type === 'meal' || type === 'exercise'
  const canSubmit = !busy && (
    type === 'task' ? title.trim() && (recurrence !== 'yearly' || dueAt) :
      type === 'water' ? Number(water) > 0 :
        requiresFile ? Boolean(file) :
          type === 'weight' ? Boolean(weight || file) :
            type === 'growth' || type === 'library' ? title.trim() : true
  )

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="record-dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title">
        <header>
          <span className="dialog-icon"><Icon size={22} /></span>
          <div><h2 id="dialog-title">{meta.title}</h2><p>{meta.description}</p></div>
          <button type="button" className="dialog-close" onClick={onClose} aria-label="关闭"><X size={20} /></button>
        </header>
        <form onSubmit={submit}>
          {type === 'task' ? <>
            <label>任务名称<input autoFocus required maxLength={160} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：完成短视频脚本初稿" /></label>
            <label>四象限<select value={quadrant} onChange={(event) => setQuadrant(event.target.value)}><option value="important_urgent">重要 · 紧急</option><option value="important_not_urgent">重要 · 不紧急</option><option value="not_important_urgent">不重要 · 紧急</option><option value="not_important_not_urgent">不重要 · 不紧急</option></select></label>
            <label>安排时间（可选）<input type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} /></label>
            <label>重复方式<select value={recurrence} onChange={(event) => setRecurrence(event.target.value)}><option value="none">仅这一次</option><option value="yearly">每年这一天</option></select></label>
            <p className="form-note">未来任务会先保存，到安排日期当天自动出现在“今日任务”。</p>
          </> : null}

          {type === 'water' ? <>
            <label>本次饮水量<div className="input-with-unit"><input autoFocus type="number" min="1" max="3000" value={water} onChange={(event) => setWater(event.target.value)} /><span>ml</span></div></label>
            <div className="amount-presets">{Array.from(new Set([data?.health?.cup_ml || 250, 200, 350, 500])).slice(0, 4).map((amount) => <button type="button" className={Number(water) === amount ? 'is-active' : ''} onClick={() => setWater(amount)} key={amount}>{amount} ml</button>)}</div>
          </> : null}

          {type === 'weight' ? <>
            <label>体重数值<div className="input-with-unit"><input autoFocus type="number" min="20" max="400" step="0.1" value={weight} onChange={(event) => setWeight(event.target.value)} placeholder="例如 62.5" /><span>kg</span></div></label>
            <label>记录日期<input type="date" required max={localDateValue()} value={recordDate} onChange={(event) => setRecordDate(event.target.value)} /></label>
          </> : null}

          {type === 'growth' ? <><label>想学习什么<input autoFocus required maxLength={120} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：围棋入门" /></label><label>你的目标<textarea maxLength={1000} rows="4" value={goal} onChange={(event) => setGoal(event.target.value)} placeholder="例如：30 天内掌握基本规则并能完成一盘棋" /></label></> : null}

          {type === 'library' ? <><label>类型<select value={libraryKind} onChange={(event) => setLibraryKind(event.target.value)}><option value="book">书籍</option><option value="movie">电影</option><option value="documentary">纪录片</option></select></label><label>名称<input autoFocus required maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="输入书名、电影名或纪录片名" /></label><label>加入理由<textarea maxLength={4000} rows="3" value={goal} onChange={(event) => setGoal(event.target.value)} placeholder="为什么想看，或是谁推荐的？" /></label></> : null}

          {type === 'meal' ? <div className="form-columns meal-record-fields">
            <label>哪一天<input type="date" required max={localDateValue()} value={recordDate} onChange={(event) => setRecordDate(event.target.value)} /></label>
            <label>哪一餐<select value={mealSlot} onChange={(event) => setMealSlot(event.target.value)}>{mealSlotOptions.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}</select></label>
          </div> : null}

          {type === 'exercise' ? <label>运动日期<input type="date" required max={localDateValue()} value={recordDate} onChange={(event) => setRecordDate(event.target.value)} /></label> : null}

          {['meal', 'weight', 'exercise'].includes(type) ? <label className={`upload-field ${preview ? 'has-preview' : ''}`}>
            {preview ? <img src={preview} alt="待上传图片预览" /> : <><span><Upload size={23} /></span><strong>{type === 'meal' ? '拍摄或选择食物照片' : type === 'weight' ? '可选：上传体重秤照片' : '拍摄或选择运动报告'}</strong><small>支持 JPG、PNG、WEBP、HEIC，最大 15MB</small></>}
            <input type="file" accept="image/*" capture="environment" required={requiresFile} onChange={(event) => setFile(event.target.files?.[0] || null)} />
          </label> : null}

          {error ? <p className="form-error" role="alert">{error}</p> : null}
          <div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>取消</button><button type="submit" className="primary-button" disabled={!canSubmit}>{busy ? '正在保存…' : '保存记录'}</button></div>
        </form>
      </section>
    </div>
  )
}
