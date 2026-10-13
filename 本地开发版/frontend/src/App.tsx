import { useState } from 'react'
import { getUser, clearToken } from './lib/api'
import LoginPage from './pages/LoginPage'
import WorkspacePage from './pages/WorkspacePage'
import ReviewPage from './pages/ReviewPage'

type View = 'workspace' | 'review'

function App() {
  const [loggedIn, setLoggedIn] = useState(!!getUser())
  const [view, setView] = useState<View>('workspace')
  const [activeJobId, setActiveJobId] = useState('')

  if (!loggedIn) {
    return <LoginPage onLogin={() => setLoggedIn(true)} />
  }

  const handleLogout = () => {
    clearToken()
    setLoggedIn(false)
  }

  return (
    <div>
      {/* 顶部导航 */}
      <div style={{ background: '#00B8B8', color: '#fff', padding: '12px 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 18, fontWeight: 700, textShadow: '0 1px 3px rgba(0,0,0,0.3)' }}>
          <span style={{ fontFamily: '"Microsoft YaHei", "PingFang SC", sans-serif', letterSpacing: '1px' }}>认证清单整合系统</span>
          <span style={{ marginLeft: 10, fontFamily: '"Segoe UI", Consolas, monospace', fontWeight: 700, fontSize: 17, letterSpacing: '0.5px', color: '#ffffff' }}>CertAgent</span>
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ color: '#e0f7f7' }}>{getUser()?.username}</span>
          {view === 'review' && (
            <button onClick={() => setView('workspace')}
              style={{ padding: '4px 12px', background: '#1677ff', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}>
              返回工作台
            </button>
          )}
          <button onClick={handleLogout}
            style={{ padding: '4px 12px', background: 'transparent', color: '#fff', border: '1px solid #fff', borderRadius: 4, cursor: 'pointer' }}>
            退出
          </button>
        </div>
      </div>

      {/* 页面内容 */}
      {view === 'workspace' && (
        <WorkspacePage onReview={(id) => { setActiveJobId(id); setView('review') }} />
      )}
      {view === 'review' && (
        <ReviewPage jobId={activeJobId} onDone={() => setView('workspace')} />
      )}
    </div>
  )
}

export default App
