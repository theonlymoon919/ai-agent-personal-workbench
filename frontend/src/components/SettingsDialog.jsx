import { Flag, HeartPulse, Settings2, Sparkles, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'

const meta = {
  profile: { title: '称呼与每日寄语', description: '设置 AI Agent 对你的称呼，以及每天寄语的语气。', icon: Sparkles },
  health: { title: '设置减重目标', description: '填写身体信息，热量、运动和饮水建议由系统自动估算。', icon: HeartPulse },
  ip: { title: '设置关注方向', description: 'AI Agent 会按这些方向筛选今日资讯与短视频热点。', icon: Settings2 },
  project: { title: '添加项目进度', description: 'AI Agent 可以继续维护项目阶段，并据此安排每日任务。', icon: Flag },
}

function topicsToText(values) {
  return (values || []).join('、')
}

function textToTopics(value) {
  return value.split(/[、,，\n]/).map((item) => item.trim()).filter(Boolean)
}

const activityFactors = { sedentary: 1.2, light: 1.375, moderate: 1.55, active: 1.725 }

function roundTo50(value) {
  return Math.round(value / 50) * 50
}

function estimateHealthPlan({ gender, height, currentWeight, targetWeight, cupMl, age, activityLevel }) {
  if (!gender || !height || !currentWeight || !targetWeight || !cupMl) return null
  const ages = age ? [Number(age)] : [25, 55]
  const factors = activityLevel ? [activityFactors[activityLevel]] : [1.2, 1.375]
  const estimates = ages.flatMap((candidateAge) => factors.map((factor) => {
    const resting = (10 * Number(currentWeight)) + (6.25 * Number(height)) - (5 * candidateAge) + (gender === 'male' ? 5 : -161)
    const maintenance = resting * factor
    const deficit = Number(currentWeight) > Number(targetWeight) ? Math.min(500, Math.max(200, maintenance * 0.15)) : 0
    return roundTo50(Math.max(resting, maintenance - deficit))
  }))
  const water = roundTo50(Math.max(1500, Math.min(4000, Number(currentWeight) * 35)))
  return {
    caloriesMin: Math.min(...estimates),
    caloriesMax: Math.max(...estimates),
    water,
    cups: (water / Number(cupMl)).toFixed(1),
    personalized: Boolean(age && activityLevel),
  }
}

export function SettingsDialog({ type, data, onClose, onComplete }) {
  const config = meta[type]
  const Icon = config.icon
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [nickname, setNickname] = useState(data?.profile?.nickname || '朋友')
  const [messageStyle, setMessageStyle] = useState(data?.profile?.daily_message_style || 'mixed')
  const health = data?.preferences?.health || {}
  const [gender, setGender] = useState(health.gender || '')
  const [height, setHeight] = useState(health.height_cm || '')
  const [targetWeight, setTargetWeight] = useState(health.target_weight_kg || '')
  const [currentWeight, setCurrentWeight] = useState(data?.health?.weight_kg || health.current_weight_kg || health.start_weight_kg || '')
  const [cupMl, setCupMl] = useState(health.cup_ml || 250)
  const [age, setAge] = useState(health.age || '')
  const [activityLevel, setActivityLevel] = useState(health.activity_level || '')
  const [videoTopics, setVideoTopics] = useState(topicsToText(data?.preferences?.ip?.video_topics))
  const [aiTopics, setAiTopics] = useState(topicsToText(data?.preferences?.ip?.ai_topics))
  const [projectName, setProjectName] = useState('')
  const [projectStage, setProjectStage] = useState('准备中')
  const [projectProgress, setProjectProgress] = useState(0)
  const [nextMilestone, setNextMilestone] = useState('')
  const [dueDate, setDueDate] = useState('')
  const healthEstimate = useMemo(() => estimateHealthPlan({
    gender, height, currentWeight, targetWeight, cupMl, age, activityLevel,
  }), [gender, height, currentWeight, targetWeight, cupMl, age, activityLevel])

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
      if (type === 'profile') await api.updateProfile({ nickname: nickname.trim(), daily_message_style: messageStyle })
      if (type === 'health') await api.updateHealthGoals({
        gender,
        height_cm: Number(height),
        current_weight_kg: Number(currentWeight),
        target_weight_kg: Number(targetWeight),
        cup_ml: Number(cupMl),
        age: age ? Number(age) : null,
        activity_level: activityLevel || null,
      })
      if (type === 'ip') await api.updateIPPreferences({
        video_topics: textToTopics(videoTopics), ai_topics: textToTopics(aiTopics),
      })
      if (type === 'project') await api.createProject({
        name: projectName.trim(), current_stage: projectStage.trim(), progress_percent: Number(projectProgress),
        next_milestone: nextMilestone.trim(), due_date: dueDate || null,
      })
      const messages = { profile: '称呼和寄语偏好已保存', health: '减重目标和智能建议已更新', ip: '关注方向已保存，AI Agent 会按新方向刷新', project: '项目已加入工作台' }
      await onComplete(messages[type])
    } catch (submitError) {
      setError(submitError.message)
    } finally {
      setBusy(false)
    }
  }

  const canSubmit = !busy && (
    type === 'profile' ? nickname.trim() : type === 'health' ? Boolean(gender) && Number(height) >= 120 && Number(currentWeight) > 20 && Number(targetWeight) > 20 && Number(cupMl) >= 50 :
      type === 'ip' ? Boolean(videoTopics.trim() || aiTopics.trim()) : projectName.trim()
  )

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="record-dialog" role="dialog" aria-modal="true" aria-labelledby="settings-dialog-title">
        <header>
          <span className="dialog-icon"><Icon size={22} /></span>
          <div><h2 id="settings-dialog-title">{config.title}</h2><p>{config.description}</p></div>
          <button type="button" className="dialog-close" onClick={onClose} aria-label="关闭"><X size={20} /></button>
        </header>
        <form onSubmit={submit}>
          {type === 'profile' ? <>
            <label>希望 AI 怎么称呼你<input autoFocus required maxLength={30} value={nickname} onChange={(event) => setNickname(event.target.value)} placeholder="例如：小名、名字或喜欢的称呼" /></label>
            <label>每日寄语风格<select value={messageStyle} onChange={(event) => setMessageStyle(event.target.value)}><option value="mixed">鼓励与安慰交替</option><option value="encouraging">更有行动力</option><option value="comforting">更温柔安慰</option></select></label>
            <p className="form-note">AI Agent 每天会生成一句新话；当天还没生成时，页面会显示温和的备用句。</p>
          </> : null}

          {type === 'health' ? <>
            <div className="form-columns">
              <label>性别<select autoFocus required value={gender} onChange={(event) => setGender(event.target.value)}><option value="" disabled>请选择</option><option value="female">女性</option><option value="male">男性</option></select></label>
              <label>身高<div className="input-with-unit"><input required type="number" min="120" max="230" step="0.1" value={height} onChange={(event) => setHeight(event.target.value)} placeholder="例如 165" /><span>cm</span></div></label>
            </div>
            <div className="form-columns">
              <label>当前体重<div className="input-with-unit"><input required type="number" min="20" max="400" step="0.1" value={currentWeight} onChange={(event) => setCurrentWeight(event.target.value)} /><span>kg</span></div></label>
              <label>目标体重<div className="input-with-unit"><input required type="number" min="20" max="400" step="0.1" value={targetWeight} onChange={(event) => setTargetWeight(event.target.value)} /><span>kg</span></div></label>
            </div>
            <label>我的杯子容量<div className="input-with-unit"><input required type="number" min="50" max="2000" value={cupMl} onChange={(event) => setCupMl(event.target.value)} /><span>ml</span></div></label>
            <details className="health-precision">
              <summary>提高准确度（可选）</summary>
              <div className="form-columns">
                <label>年龄<input type="number" min="18" max="100" value={age} onChange={(event) => setAge(event.target.value)} placeholder="例如 30" /></label>
                <label>日常活动量<select value={activityLevel} onChange={(event) => setActivityLevel(event.target.value)}><option value="">暂不填写</option><option value="sedentary">久坐，很少运动</option><option value="light">轻量，每周 1–3 次</option><option value="moderate">中等，每周 3–5 次</option><option value="active">活跃，每周 6–7 次</option></select></label>
              </div>
            </details>
            {healthEstimate ? <section className="health-plan-preview" aria-label="系统估算结果">
              <div><span>每日热量参考</span><strong>{healthEstimate.caloriesMin === healthEstimate.caloriesMax ? healthEstimate.caloriesMin : `${healthEstimate.caloriesMin}–${healthEstimate.caloriesMax}`} <small>kcal</small></strong></div>
              <div><span>每周运动</span><strong>150 <small>分钟 + 力量 2 天</small></strong></div>
              <div><span>每日饮水</span><strong>{healthEstimate.water} <small>ml · 约 {healthEstimate.cups} 杯</small></strong></div>
              <p>{healthEstimate.personalized ? '已结合年龄与活动量，保存后 AI Agent 会继续给出执行建议。' : '这是基础参考区间；可选填年龄和活动量后会更准确。'}</p>
            </section> : null}
            <p className="form-note">这里给的是可调整的起始参考，不是医疗诊断；后续会结合你的体重趋势和记录逐步修正。</p>
          </> : null}

          {type === 'ip' ? <>
            <label>短视频热点方向<textarea autoFocus rows="3" value={videoTopics} onChange={(event) => setVideoTopics(event.target.value)} placeholder="例如：AI效率、女性成长、个人IP" /></label>
            <label>今日资讯关注方向<textarea rows="3" value={aiTopics} onChange={(event) => setAiTopics(event.target.value)} placeholder="例如：人工智能、跨境电商、养老服务、消费品牌" /></label>
            <p className="form-note">用顿号或逗号分隔。保存后会进入 AI Agent 的刷新队列。</p>
          </> : null}

          {type === 'project' ? <>
            <label>项目名称<input autoFocus required maxLength={160} value={projectName} onChange={(event) => setProjectName(event.target.value)} placeholder="例如：个人工作台正式上线" /></label>
            <div className="form-columns"><label>当前阶段<input maxLength={200} value={projectStage} onChange={(event) => setProjectStage(event.target.value)} /></label><label>完成进度<div className="input-with-unit"><input type="number" min="0" max="100" value={projectProgress} onChange={(event) => setProjectProgress(event.target.value)} /><span>%</span></div></label></div>
            <label>下一里程碑<textarea rows="3" value={nextMilestone} onChange={(event) => setNextMilestone(event.target.value)} placeholder="下一步要到达什么结果？" /></label>
            <label>目标日期（可选）<input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} /></label>
          </> : null}

          {error ? <p className="form-error" role="alert">{error}</p> : null}
          <div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>取消</button><button type="submit" className="primary-button" disabled={!canSubmit}>{busy ? '正在保存…' : '保存设置'}</button></div>
        </form>
      </section>
    </div>
  )
}
