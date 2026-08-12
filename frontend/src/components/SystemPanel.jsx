import {
  Archive,
  Bot,
  Copy,
  Database,
  Download,
  ExternalLink,
  FolderOpen,
  KeyRound,
  Link2,
  LoaderCircle,
  Power,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Smartphone,
  Trash2,
  UserPen,
  UserRoundPlus,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { api, backupDownloadUrl } from '../api.js'

function formatDate(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

function StorageCard({ info }) {
  const storage = info.storage
  const cloud = info.mode === 'cloud'
  return <article className="system-card system-storage-card">
    <span className="system-card__icon"><Database size={20} /></span>
    <div className="system-card__body"><div className="system-card__heading"><div><h3>{cloud ? '云端数据保存' : '数据保存'}</h3><p>{cloud ? '数据库、图片与程序容器彼此分开' : 'Markdown 与图片，程序和数据彼此分开'}</p></div><strong>{storage.size_mb} MB</strong></div>
      <dl><div><dt>{cloud ? '结构化数据' : '数据文件夹'}</dt><dd><FolderOpen size={13} />{storage.data_path}</dd></div><div><dt>{cloud ? '导出方式' : '备份文件夹'}</dt><dd><Archive size={13} />{storage.backup_path}</dd></div></dl>
      <p className="system-safe-note"><ShieldCheck size={14} />{cloud ? '账号之间强制隔离；应用更新不会删除数据库或图片。' : '不安装 Obsidian 也能使用；安装包不会包含这里的个人数据。'}</p>
    </div>
  </article>
}

function BackupCard({ backups, busy, onCreate, onRestore, cloud = false, showCreateAction = true }) {
  return <article className="system-card system-backup-card">
    <span className="system-card__icon is-amber"><Archive size={20} /></span>
    <div className="system-card__body"><div className="system-card__heading"><div><h3>{cloud ? '导出与迁移' : '备份与恢复'}</h3><p>{cloud ? '生成 JSON、Markdown、CSV 与图片的独立压缩包' : '恢复前会自动再做一份安全备份'}</p></div>{showCreateAction ? <button type="button" className="primary-button" disabled={busy} onClick={onCreate}>{busy === 'create' ? <LoaderCircle className="spin" size={15} /> : <Archive size={15} />}{busy === 'create' ? '正在生成' : cloud ? '导出全部数据' : '立即备份'}</button> : null}</div>
      {backups.length ? <div className="backup-list">{backups.slice(0, 5).map((backup) => <div key={backup.name}><span><b>{formatDate(backup.created_at)}</b><small>{cloud ? `${backup.status === 'ready' ? '可下载' : '正在生成'} · 7 天内有效` : `${backup.size_mb} MB · 版本 ${backup.app_version || '未知'}`}</small></span>{backup.status !== 'ready' ? null : <a href={backupDownloadUrl(backup.name)} aria-label={`下载${formatDate(backup.created_at)}的数据`}><Download size={14} />下载</a>}{cloud ? null : <button type="button" disabled={Boolean(busy)} onClick={() => onRestore(backup)}><RotateCcw size={14} />恢复</button>}</div>)}</div> : <div className="system-empty">{cloud ? '还没有导出记录。需要迁移或自留副本时再生成即可。' : '还没有备份，建议在正式使用前先创建第一份。'}</div>}
    </div>
  </article>
}

function DeviceCard({ info, busy, onStartup, onRemote }) {
  const remote = info.remote_access
  const startup = info.startup
  const cloud = info.mode === 'cloud'
  return <article className="system-card system-device-card">
    <span className="system-card__icon is-blue"><Smartphone size={20} /></span>
    <div className="system-card__body"><div className="system-card__heading"><div><h3>设备与运行</h3><p>版本 {info.app_version} · {cloud ? 'Ubuntu 云端版' : info.packaged ? '正式 Windows 版' : '开发预览版'}</p></div></div>
      <div className="device-setting"><span><Power size={16} /><span><b>{cloud ? '云端运行状态' : '开机自动运行'}</b><small>{startup.label}</small></span></span>{cloud ? <strong className="device-online">运行中</strong> : <button type="button" className={startup.enabled ? 'is-on' : ''} disabled={!startup.available || busy === 'startup'} aria-pressed={startup.enabled} onClick={() => onStartup(!startup.enabled)}><i /></button>}</div>
      <div className="device-setting"><span><Smartphone size={16} /><span><b>Android 手机访问</b><small>{remote.label}</small></span></span>{remote.url ? <a href={remote.url} target="_blank" rel="noreferrer">打开地址<ExternalLink size={12} /></a> : !remote.installed ? <a href="https://tailscale.com/download/windows" target="_blank" rel="noreferrer">安装 Tailscale<ExternalLink size={12} /></a> : remote.connected ? <button type="button" className="device-action-button" disabled={busy === 'remote'} onClick={onRemote}>{busy === 'remote' ? '正在开启' : '开启访问'}</button> : <small className="device-waiting">请先登录</small>}</div>
    </div>
  </article>
}

function AccountSecurityCard({ busy, identity, onChangePassword, onChangeUsername, onGenerateAgentToken, showAction = true }) {
  return <article className="system-card">
    <span className="system-card__icon"><KeyRound size={20} /></span>
    <div className="system-card__body"><div className="system-card__heading"><div><h3>账号与 AI Agent</h3><p>当前登录名：<b>{identity?.user?.username || '—'}</b></p></div>{showAction ? <button type="button" className="secondary-button" disabled={busy} onClick={onChangePassword}>{busy === 'password' ? <LoaderCircle className="spin" size={15} /> : <KeyRound size={15} />}{busy === 'password' ? '正在修改' : '修改密码'}</button> : null}</div>
      <div className="account-security-actions"><button type="button" className="secondary-button" disabled={Boolean(busy)} onClick={onChangeUsername}><UserPen size={14} />修改登录名</button><button type="button" className="secondary-button" disabled={Boolean(busy)} onClick={onGenerateAgentToken}><Bot size={14} />生成 AI Agent 令牌</button></div>
      <p className="system-safe-note"><ShieldCheck size={14} />修改登录名不会影响工作空间或 AI Agent；重新生成令牌会让旧 AI Agent 令牌立即失效。</p>
    </div>
  </article>
}

function InviteCard({ busy, onCreate }) {
  return <article className="system-card invite-user-card">
    <span className="system-card__icon is-blue"><UserRoundPlus size={20} /></span>
    <div className="system-card__body"><div className="system-card__heading"><div><h3>邀请新用户</h3><p>新用户可以自行选择登录名、昵称和密码</p></div><button type="button" className="primary-button" disabled={Boolean(busy)} onClick={onCreate}>{busy === 'invite' ? <LoaderCircle className="spin" size={15} /> : <Link2 size={15} />}{busy === 'invite' ? '正在生成' : '生成邀请'}</button></div>
      <p className="system-safe-note"><ShieldCheck size={14} />邀请默认 72 小时有效且只能使用一次；工作空间创建后与其他账号完全隔离。</p>
    </div>
  </article>
}

function SecretDialog({ data, onClose }) {
  const invite = data.kind === 'invite'
  const secret = invite ? data.invite_code : data.agent_token
  const copy = async (value) => navigator.clipboard.writeText(value)
  return <div className="dialog-backdrop" role="presentation"><section className="record-dialog account-secret-dialog" role="dialog" aria-modal="true" aria-labelledby="account-secret-title">
    <header><div><span className="eyebrow">{invite ? 'ONE-TIME INVITE' : 'AI AGENT ACCESS'}</span><h2 id="account-secret-title">{invite ? '一次性邀请已生成' : '新的 AI Agent 令牌已生成'}</h2></div><button type="button" onClick={onClose} aria-label="关闭"><X size={19} /></button></header>
    <div className="account-secret-body">
      <p>{invite ? `有效期至 ${formatDate(data.expires_at)}，使用一次后立即失效。` : '旧令牌已经失效。请立即配置到当前用户自己的 AI Agent。'}</p>
      {invite ? <label><span>注册链接</span><div><input readOnly value={data.registration_url} /><button type="button" onClick={() => copy(data.registration_url)}><Copy size={14} />复制</button></div></label> : null}
      <label><span>{invite ? '邀请码' : 'Agent Token'}</span><div><input readOnly value={secret} /><button type="button" onClick={() => copy(secret)}><Copy size={14} />复制</button></div></label>
      {!invite ? <label><span>MCP 地址</span><div><input readOnly value={data.mcp_url} /><button type="button" onClick={() => copy(data.mcp_url)}><Copy size={14} />复制</button></div></label> : null}
      <p className="system-safe-note"><ShieldCheck size={14} />关闭后不会再次显示，请不要发到群聊、截图或公开文档。</p>
      <div className="dialog-actions"><button type="button" className="primary-button" onClick={onClose}>我已安全保存</button></div>
    </div>
  </section></div>
}

function AccountDeletionCard({ busy, onDelete, showAction = true }) {
  return <article className="system-card account-delete-card">
    <span className="system-card__icon is-amber"><Trash2 size={20} /></span>
    <div className="system-card__body"><div className="system-card__heading"><div><h3>注销并彻底删除</h3><p>删除当前账号的数据库记录、图片、导出文件和 AI Agent 凭证</p></div>{showAction ? <button type="button" className="danger-button" disabled={busy} onClick={onDelete}>{busy === 'delete-account' ? <LoaderCircle className="spin" size={15} /> : <Trash2 size={15} />}{busy === 'delete-account' ? '正在注销' : '删除我的数据'}</button> : null}</div>
      <p className="system-safe-note"><ShieldCheck size={14} />这是不可恢复操作；建议先在上方导出全部数据。</p>
    </div>
  </article>
}

function CloudAccountActions({ busy, onExport, onChangePassword, onDelete }) {
  return <div className="system-account-actions" aria-label="账号快捷操作">
    <button type="button" className="is-primary" disabled={Boolean(busy)} onClick={onExport}>{busy === 'create' ? <LoaderCircle className="spin" size={18} /> : <Archive size={18} />}<span>{busy === 'create' ? '正在导出' : '导出全部数据'}</span></button>
    <button type="button" disabled={Boolean(busy)} onClick={onChangePassword}>{busy === 'password' ? <LoaderCircle className="spin" size={18} /> : <KeyRound size={18} />}<span>{busy === 'password' ? '正在修改' : '修改密码'}</span></button>
    <button type="button" className="is-danger" disabled={Boolean(busy)} onClick={onDelete}>{busy === 'delete-account' ? <LoaderCircle className="spin" size={18} /> : <Trash2 size={18} />}<span>{busy === 'delete-account' ? '正在删除' : '删除我的数据'}</span></button>
  </div>
}

export function SystemPanel() {
  const [info, setInfo] = useState(null)
  const [identity, setIdentity] = useState(null)
  const [backups, setBackups] = useState([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [secretDialog, setSecretDialog] = useState(null)

  const load = useCallback(async ({ quiet = false } = {}) => {
    if (!quiet) setLoading(true)
    try {
      const [nextInfo, nextBackups, nextIdentity] = await Promise.all([api.systemInfo(), api.backups(), api.me()])
      setInfo(nextInfo); setBackups(nextBackups); setIdentity(nextIdentity); setError('')
    } catch (requestError) { setError(requestError.message) }
    finally { if (!quiet) setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  async function createBackup() {
    setBusy('create'); setError(''); setMessage('')
    try { await api.createBackup(); setMessage(info?.mode === 'cloud' ? '完整数据导出已生成，可在下方下载。' : '备份已完成，个人数据没有写入程序目录。'); await load({ quiet: true }) }
    catch (requestError) { setError(requestError.message) }
    finally { setBusy('') }
  }

  async function restoreBackup(backup) {
    const approved = window.confirm(`确定恢复 ${formatDate(backup.created_at)} 的备份吗？\n\n恢复前会自动保存当前数据，备份之后新增的文件也会保留。`)
    if (!approved) return
    setBusy(backup.name); setError(''); setMessage('')
    try { const result = await api.restoreBackup(backup.name); setMessage(`已恢复 ${result.restored_files} 个文件，并保留了恢复前的安全备份。`); await load({ quiet: true }) }
    catch (requestError) { setError(requestError.message) }
    finally { setBusy('') }
  }

  async function updateStartup(enabled) {
    setBusy('startup'); setError(''); setMessage('')
    try { await api.updateStartup(enabled); setMessage(enabled ? '已设置开机自动运行。' : '已关闭开机自动运行。'); await load({ quiet: true }) }
    catch (requestError) { setError(requestError.message) }
    finally { setBusy('') }
  }

  async function enableRemote() {
    setBusy('remote'); setError(''); setMessage('')
    try { const result = await api.enableRemoteAccess(); setMessage(result.url ? `手机访问已开启：${result.url}` : '手机访问已开启。'); await load({ quiet: true }) }
    catch (requestError) { setError(requestError.message) }
    finally { setBusy('') }
  }

  async function changePassword() {
    const currentPassword = window.prompt('请输入当前账号密码。')
    if (!currentPassword) return
    const newPassword = window.prompt('请输入新密码，至少 12 个字符。')
    if (!newPassword) return
    if (newPassword.length < 12) {
      setError('新密码至少需要 12 个字符。')
      return
    }
    const confirmed = window.prompt('请再次输入新密码。')
    if (confirmed !== newPassword) {
      setError('两次输入的新密码不一致。')
      return
    }
    setBusy('password'); setError(''); setMessage('')
    try {
      await api.changePassword(currentPassword, newPassword)
      window.alert('密码已更新，请使用新密码重新登录。')
      window.dispatchEvent(new Event('workbench:unauthorized'))
    } catch (requestError) {
      setError(requestError.message)
      setBusy('')
    }
  }

  async function changeUsername() {
    const nextUsername = window.prompt(`当前登录名：${identity?.user?.username || ''}\n请输入新的登录用户名（3–80 个字符，不能有空格）。`)
    if (!nextUsername?.trim()) return
    const currentPassword = window.prompt('请输入当前账号密码确认修改。')
    if (!currentPassword) return
    setBusy('username'); setError(''); setMessage('')
    try {
      const result = await api.changeUsername(currentPassword, nextUsername.trim())
      setMessage(result.message)
      await load({ quiet: true })
    } catch (requestError) { setError(requestError.message) }
    finally { setBusy('') }
  }

  async function createInvite() {
    setBusy('invite'); setError(''); setMessage('')
    try { setSecretDialog({ kind: 'invite', ...await api.createRegistrationInvite(72) }) }
    catch (requestError) { setError(requestError.message) }
    finally { setBusy('') }
  }

  async function generateAgentToken() {
    const approved = window.confirm('重新生成后，当前 AI Agent 使用的旧令牌会立即失效。是否继续？')
    if (!approved) return
    const currentPassword = window.prompt('请输入当前账号密码。')
    if (!currentPassword) return
    const confirmation = window.prompt('请输入：重新生成Agent令牌')
    if (confirmation !== '重新生成Agent令牌') return setError('确认文字不正确，已取消生成。')
    setBusy('agent-token'); setError(''); setMessage('')
    try { setSecretDialog({ kind: 'agent-token', ...await api.issueAgentToken(currentPassword, confirmation) }) }
    catch (requestError) { setError(requestError.message) }
    finally { setBusy('') }
  }

  async function deleteAccount() {
    const password = window.prompt('请输入当前账号密码。为了安全，建议先导出全部数据。')
    if (!password) return
    const confirmation = window.prompt('此操作不可恢复。请输入：彻底删除我的数据')
    if (confirmation !== '彻底删除我的数据') {
      setError('确认文字不正确，已取消删除。')
      return
    }
    setBusy('delete-account'); setError(''); setMessage('')
    try {
      await api.deleteAccount(password, confirmation)
      window.dispatchEvent(new Event('workbench:unauthorized'))
    } catch (requestError) {
      setError(requestError.message)
      setBusy('')
    }
  }

  if (loading && !info) return <section className="system-panel system-panel-state"><LoaderCircle className="spin" size={22} />正在检查数据与设备…</section>
  if (error && !info) return <section className="system-panel system-panel-state is-error"><p>{error}</p><button type="button" className="secondary-button" onClick={() => load()}><RefreshCw size={15} />重试</button></section>
  const cloud = info.mode === 'cloud'
  return <section className="system-panel"><div className="system-panel__heading"><div><h2>数据与设备</h2><p>备份、迁移和手机连接都从这里管理。</p></div></div>{cloud ? <CloudAccountActions busy={busy} onExport={createBackup} onChangePassword={changePassword} onDelete={deleteAccount} /> : null}<div className="system-card-list"><StorageCard info={info} /><BackupCard cloud={cloud} backups={backups} busy={busy} onCreate={createBackup} onRestore={restoreBackup} showCreateAction={!cloud} /><DeviceCard info={info} busy={busy} onStartup={updateStartup} onRemote={enableRemote} />{cloud ? <AccountSecurityCard busy={busy} identity={identity} onChangePassword={changePassword} onChangeUsername={changeUsername} onGenerateAgentToken={generateAgentToken} showAction={false} /> : null}{cloud && identity?.user?.can_invite ? <InviteCard busy={busy} onCreate={createInvite} /> : null}{cloud ? <AccountDeletionCard busy={busy} onDelete={deleteAccount} showAction={false} /> : null}</div>{message ? <p className="system-message">{message}</p> : null}{error ? <p className="form-error">{error}</p> : null}{secretDialog ? <SecretDialog data={secretDialog} onClose={() => setSecretDialog(null)} /> : null}</section>
}
