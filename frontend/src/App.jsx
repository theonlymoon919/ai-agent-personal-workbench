import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import { AppShell } from './components/AppShell.jsx'
import { Dashboard } from './components/Dashboard.jsx'
import { LearningPlanDetail } from './components/LearningPlanDetail.jsx'
import { HealthHistoryDetail } from './components/HealthHistoryDetail.jsx'
import { FinanceDetail } from './components/FinanceDetail.jsx'
import { TaskCalendarDetail } from './components/TaskCalendarDetail.jsx'
import { LibraryDetail } from './components/LibraryDetail.jsx'
import { ContentDetail } from './components/ContentDetail.jsx'
import { RecordDialog } from './components/RecordDialog.jsx'
import { SettingsDialog } from './components/SettingsDialog.jsx'
import { LoginScreen } from './components/LoginScreen.jsx'
import { useDashboard } from './hooks/useDashboard.js'
import { api } from './api.js'

const ProjectPlannerDetail = lazy(() => import('./components/ProjectPlannerDetail.jsx').then((module) => ({ default: module.ProjectPlannerDetail })))

const VALID_ACTIONS = new Set(['task', 'water', 'meal', 'weight', 'exercise', 'growth', 'library'])
const SETTINGS_ACTIONS = new Set(['profile', 'health', 'ip', 'project'])

function WorkbenchApp({ onLogout }) {
  const [toast, setToast] = useState(null)
  const { data, error, loading, reload, notice } = useDashboard()
  const [section, setSection] = useState('workbench')
  const [action, setAction] = useState(null)
  const [settingsAction, setSettingsAction] = useState(null)
  const [detail, setDetail] = useState(null)

  const showToast = useCallback((nextToast) => {
    setToast(typeof nextToast === 'string' ? { message: nextToast } : nextToast)
  }, [])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const requested = params.get('action')
    if (VALID_ACTIONS.has(requested)) setAction(requested)
    if (params.get('detail') === 'project-plan') {
      setSection('tasks')
      setDetail({ type: 'project-planner', id: params.get('project') || '' })
    }
  }, [])

  useEffect(() => {
    const unauthorized = () => onLogout()
    window.addEventListener('workbench:unauthorized', unauthorized)
    return () => window.removeEventListener('workbench:unauthorized', unauthorized)
  }, [onLogout])

  useEffect(() => {
    if (!toast) return undefined
    const timer = window.setTimeout(() => setToast(null), toast.actionLabel ? 6500 : 3800)
    return () => window.clearTimeout(timer)
  }, [toast])

  useEffect(() => {
    if (notice) showToast(notice)
  }, [notice, showToast])

  useEffect(() => {
    window.__personalWorkbenchHandleBack = () => {
      const dialogs = [...document.querySelectorAll('[role="dialog"], [role="alertdialog"]')]
      const topDialog = dialogs.at(-1)
      if (topDialog) {
        const closeControl = topDialog.querySelector('.dialog-close, header button[aria-label="关闭"], .dialog-actions .secondary-button')
        if (closeControl) {
          closeControl.click()
          return true
        }
      }
      if (settingsAction) { setSettingsAction(null); return true }
      if (action) { setAction(null); return true }
      if (detail) { setDetail(null); return true }
      if (section !== 'workbench') { setSection('workbench'); return true }
      return false
    }
    window.PersonalWorkbenchAndroid?.setCanGoBack?.(Boolean(settingsAction || action || detail || section !== 'workbench'))
    return () => { delete window.__personalWorkbenchHandleBack }
  }, [action, detail, section, settingsAction])

  const completeAction = useCallback(
    async (message, completedAction = {}) => {
      setAction(null)
      showToast(message)
      if (completedAction.type === 'growth' && completedAction.record?.id) {
        setSection('growth')
        setDetail({ type: 'learning-plan', id: completedAction.record.id })
      }
      if (completedAction.type === 'library' && completedAction.record?.id) {
        setSection('growth')
        setDetail({ type: 'library-item', id: completedAction.record.id })
      }
      await reload({ quiet: true })
    },
    [reload, showToast],
  )

  const changeSection = useCallback((nextSection) => {
    setDetail(null)
    setSection(nextSection)
  }, [])

  const activePlanVersion = detail?.type === 'learning-plan'
    ? data?.growth?.find((plan) => plan.id === detail.id)?.updated_at
    : null
  const activeLibraryVersion = detail?.type === 'library-item'
    ? data?.library?.find((item) => item.id === detail.id)?.updated_at
    : null
  const healthRefreshToken = detail?.type === 'health-history'
    ? JSON.stringify([data?.health, data?.health_records])
    : null

  return (
    <AppShell
      section={section}
      onSectionChange={changeSection}
      hermes={data?.hermes}
      activity={data?.activity || []}
      suggestion={data?.suggestion}
      onQuickRecord={() => setAction('task')}
      onLogout={onLogout}
      focusWide={detail?.type === 'project-planner'}
    >
      {detail?.type === 'learning-plan' ? (
        <LearningPlanDetail
          planId={detail.id}
          refreshToken={activePlanVersion}
          onBack={() => setDetail(null)}
          onNewPlan={() => setAction('growth')}
          onDashboardReload={() => reload({ quiet: true })}
          onDeleted={async () => {
            setDetail(null)
            showToast('学习计划已移入回收站')
            await reload({ quiet: true })
          }}
        />
      ) : detail?.type === 'library-item' ? (
        <LibraryDetail
          itemId={detail.id}
          refreshToken={activeLibraryVersion}
          onBack={() => setDetail(null)}
          onDashboardReload={() => reload({ quiet: true })}
        />
      ) : detail?.type === 'content-item' ? (
        <ContentDetail itemId={detail.id} onBack={() => setDetail(null)} />
      ) : detail?.type === 'health-history' ? (
        <HealthHistoryDetail
          refreshToken={healthRefreshToken}
          onBack={() => setDetail(null)}
          onRecord={setAction}
        />
      ) : detail?.type === 'task-calendar' ? (
        <TaskCalendarDetail
          initialTask={detail.task}
          onBack={() => setDetail(null)}
          onDashboardReload={() => reload({ quiet: true })}
          onToast={showToast}
        />
      ) : detail?.type === 'project-planner' ? (
        <Suspense fallback={<div className="screen-state">正在打开项目全景…</div>}>
          <ProjectPlannerDetail
            initialProjectId={detail.id}
            onBack={() => setDetail(null)}
            onDashboardReload={() => reload({ quiet: true })}
            onToast={showToast}
          />
        </Suspense>
      ) : section === 'finance' ? (
        <FinanceDetail
          onBack={() => changeSection('workbench')}
          onDashboardReload={() => reload({ quiet: true })}
        />
      ) : (
        <Dashboard
          section={section}
          data={data}
          loading={loading}
          error={error}
          onAction={setAction}
          onSettings={(next) => SETTINGS_ACTIONS.has(next) && setSettingsAction(next)}
          onOpenPlan={(id) => setDetail({ type: 'learning-plan', id })}
          onOpenLibrary={(id) => setDetail({ type: 'library-item', id })}
          onOpenContent={(id) => setDetail({ type: 'content-item', id })}
          onOpenHealth={() => {
            setSection('health')
            setDetail({ type: 'health-history' })
          }}
          onOpenCalendar={(task = null) => {
            setSection('tasks')
            setDetail({ type: 'task-calendar', task })
          }}
          onOpenProjects={(id = '') => {
            setSection('tasks')
            setDetail({ type: 'project-planner', id })
          }}
          onReload={() => reload()}
          onToast={showToast}
        />
      )}
      {action ? <RecordDialog type={action} data={data} onClose={() => setAction(null)} onComplete={completeAction} /> : null}
      {settingsAction ? <SettingsDialog type={settingsAction} data={data} onClose={() => setSettingsAction(null)} onComplete={async (message) => { setSettingsAction(null); showToast(message); await reload({ quiet: true }) }} /> : null}
      {toast ? <div className={`toast ${toast.tone === 'error' ? 'is-error' : ''}`} role="status"><span>{toast.message}</span>{toast.actionLabel ? <button type="button" onClick={async () => { const actionHandler = toast.onAction; setToast(null); try { await actionHandler?.() } catch (actionError) { showToast({ message: actionError.message || '撤销失败，请稍后重试', tone: 'error' }) } }}>{toast.actionLabel}</button> : null}<button type="button" className="toast__close" aria-label="关闭提示" onClick={() => setToast(null)}>×</button></div> : null}
    </AppShell>
  )
}

export default function App() {
  const [identity, setIdentity] = useState(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    let active = true
    api.me()
      .then((result) => { if (active) setIdentity(result) })
      .catch(() => { if (active) setIdentity(null) })
      .finally(() => { if (active) setChecking(false) })
    return () => { active = false }
  }, [])

  useEffect(() => {
    const viewport = window.visualViewport
    const updateViewport = () => {
      document.documentElement.style.setProperty('--workbench-viewport-height', `${Math.round(viewport?.height || window.innerHeight)}px`)
    }
    const keepFocusedFieldVisible = (event) => {
      if (window.innerWidth > 820 || !event.target?.matches?.('input, textarea, select')) return
      window.setTimeout(() => event.target.scrollIntoView({ block: 'center', behavior: 'smooth' }), 180)
    }
    updateViewport()
    viewport?.addEventListener('resize', updateViewport)
    viewport?.addEventListener('scroll', updateViewport)
    window.addEventListener('resize', updateViewport)
    document.addEventListener('focusin', keepFocusedFieldVisible)
    return () => {
      viewport?.removeEventListener('resize', updateViewport)
      viewport?.removeEventListener('scroll', updateViewport)
      window.removeEventListener('resize', updateViewport)
      document.removeEventListener('focusin', keepFocusedFieldVisible)
    }
  }, [])

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      setIdentity(null)
    }
  }, [])

  if (checking || !identity) {
    return <LoginScreen checking={checking} onLogin={setIdentity} />
  }
  return <WorkbenchApp onLogout={logout} />
}
