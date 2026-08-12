import { useEffect, useState } from 'react'
import { ArrowLeft, Eye, EyeOff, LoaderCircle, LockKeyhole, Sparkles, UserRoundPlus } from 'lucide-react'
import { api } from '../api.js'

function PasswordField({ value, onChange, visible, onToggle, autoComplete = 'current-password', placeholder = '输入密码' }) {
  return <div className="password-field">
    <input
      autoComplete={autoComplete}
      type={visible ? 'text' : 'password'}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      maxLength={256}
    />
    <button type="button" onClick={onToggle} aria-label={visible ? '隐藏密码' : '显示密码'}>
      {visible ? <EyeOff size={17} /> : <Eye size={17} />}
    </button>
  </div>
}

export function LoginScreen({ checking = false, onLogin }) {
  const initialInvite = new URLSearchParams(window.location.search).get('invite') || ''
  const [mode, setMode] = useState(initialInvite ? 'register' : 'login')
  const [setupRequired, setSetupRequired] = useState(false)
  const [setupChecking, setSetupChecking] = useState(true)
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [confirmedPassword, setConfirmedPassword] = useState('')
  const [inviteCode, setInviteCode] = useState(initialInvite)
  const [showPassword, setShowPassword] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    api.setupStatus()
      .then((result) => { if (active) setSetupRequired(Boolean(result.setup_required)) })
      .catch(() => { if (active) setSetupRequired(false) })
      .finally(() => { if (active) setSetupChecking(false) })
    return () => { active = false }
  }, [])

  function switchMode(nextMode) {
    setMode(nextMode)
    setPassword('')
    setConfirmedPassword('')
    setError('')
  }

  async function submitLogin(event) {
    event.preventDefault()
    if (!username.trim() || !password) return
    setBusy(true)
    setError('')
    try {
      const identity = await api.login(username.trim(), password)
      onLogin(identity)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy(false)
    }
  }

  async function submitRegistration(event) {
    event.preventDefault()
    if (password.length < 12) return setError('密码至少需要 12 个字符。')
    if (password !== confirmedPassword) return setError('两次输入的密码不一致。')
    setBusy(true)
    setError('')
    try {
      const identity = await api.register({
        invite_code: inviteCode.trim(),
        username: username.trim(),
        display_name: displayName.trim(),
        password,
      })
      window.history.replaceState({}, '', `${window.location.pathname}${window.location.hash}`)
      onLogin(identity)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy(false)
    }
  }

  async function submitInitialSetup(event) {
    event.preventDefault()
    if (password.length < 12) return setError('密码至少需要 12 个字符。')
    if (password !== confirmedPassword) return setError('两次输入的密码不一致。')
    setBusy(true)
    setError('')
    try {
      const identity = await api.setup({
        username: username.trim(),
        display_name: displayName.trim(),
        password,
      })
      onLogin(identity)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy(false)
    }
  }

  const initializing = setupRequired
  const registering = !initializing && mode === 'register'
  const showingLongForm = initializing || registering
  return (
    <main className="login-screen">
      <section className={`login-card ${showingLongForm ? 'is-registration' : ''}`} aria-labelledby="login-title">
        <div className="login-brand">
          <div className="brand__mark"><Sparkles size={20} aria-hidden="true" /></div>
          <div><strong>AI Agent 个人工作台</strong><span>USER-OWNED AI OS</span></div>
        </div>
        <div className="login-copy">
          <span className="eyebrow">{initializing ? 'FIRST-RUN SETUP' : registering ? 'INVITED REGISTRATION' : 'WELCOME BACK'}</span>
          <h1 id="login-title">{initializing ? '创建首位管理员' : registering ? '创建你的独立工作空间' : '回到你的工作空间'}</h1>
          <p>{initializing ? '这是一次性入口。请自行设置管理员用户名、昵称和高强度密码。' : registering ? '使用一次性邀请码，自行设置好记的登录名、昵称和密码。' : '每个账号都有独立的数据、图片和 AI Agent 连接。'}</p>
        </div>
        {checking || setupChecking ? (
          <div className="login-checking"><LoaderCircle className="spin" size={23} />正在确认登录状态…</div>
        ) : initializing ? (
          <form className="login-form registration-form" onSubmit={submitInitialSetup}>
            <div className="registration-columns"><label><span>管理员用户名</span><input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} placeholder="3–80 个字符，不能有空格" maxLength={80} required /></label><label><span>显示昵称</span><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="工作台如何称呼你" maxLength={80} required /></label></div>
            <label><span>管理员密码</span><PasswordField value={password} onChange={setPassword} visible={showPassword} onToggle={() => setShowPassword((value) => !value)} autoComplete="new-password" placeholder="至少 12 个字符" /></label>
            <label><span>再次输入密码</span><input type="password" autoComplete="new-password" value={confirmedPassword} onChange={(event) => setConfirmedPassword(event.target.value)} placeholder="再次输入密码" maxLength={256} required /></label>
            {error ? <p className="form-error" role="alert">{error}</p> : null}
            <button className="login-submit" type="submit" disabled={busy || !username.trim() || !displayName.trim() || !password || !confirmedPassword}>{busy ? <LoaderCircle className="spin" size={18} /> : <UserRoundPlus size={17} />}{busy ? '正在初始化…' : '创建管理员并进入'}</button>
            <p className="form-note">初始化成功后此入口会永久关闭。你可以登录后创建一次性邀请，并为自己的 AI Agent 生成专属令牌。</p>
          </form>
        ) : registering ? (
          <form className="login-form registration-form" onSubmit={submitRegistration}>
            <label className="registration-invite"><span>一次性邀请码</span><input value={inviteCode} onChange={(event) => setInviteCode(event.target.value)} placeholder="粘贴管理员发给你的邀请码" maxLength={256} required /></label>
            <div className="registration-columns"><label><span>登录用户名</span><input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} placeholder="3–80 个字符，不能有空格" maxLength={80} required /></label><label><span>显示昵称</span><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="工作台如何称呼你" maxLength={80} required /></label></div>
            <label><span>密码</span><PasswordField value={password} onChange={setPassword} visible={showPassword} onToggle={() => setShowPassword((value) => !value)} autoComplete="new-password" placeholder="至少 12 个字符" /></label>
            <label><span>再次输入密码</span><input type="password" autoComplete="new-password" value={confirmedPassword} onChange={(event) => setConfirmedPassword(event.target.value)} placeholder="再次输入密码" maxLength={256} required /></label>
            {error ? <p className="form-error" role="alert">{error}</p> : null}
            <button className="login-submit" type="submit" disabled={busy || !inviteCode.trim() || !username.trim() || !displayName.trim() || !password || !confirmedPassword}>{busy ? <LoaderCircle className="spin" size={18} /> : <UserRoundPlus size={17} />}{busy ? '正在创建…' : '创建并进入工作台'}</button>
            <button type="button" className="login-mode-switch" onClick={() => switchMode('login')}><ArrowLeft size={14} />已有账号，返回登录</button>
          </form>
        ) : (
          <form className="login-form" onSubmit={submitLogin}>
            <label><span>账号</span><input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} placeholder="输入你的账号" maxLength={80} /></label>
            <label><span>密码</span><PasswordField value={password} onChange={setPassword} visible={showPassword} onToggle={() => setShowPassword((value) => !value)} /></label>
            {error ? <p className="form-error" role="alert">{error}</p> : null}
            <button className="login-submit" type="submit" disabled={busy || !username.trim() || !password}>{busy ? <LoaderCircle className="spin" size={18} /> : <LockKeyhole size={17} />}{busy ? '正在进入…' : '进入工作台'}</button>
            <button type="button" className="login-mode-switch" onClick={() => switchMode('register')}><UserRoundPlus size={14} />收到邀请码？创建新账号</button>
          </form>
        )}
        <p className="login-privacy">健康、财务和图片仅对当前账号及其专属 AI Agent 可见。</p>
      </section>
    </main>
  )
}
