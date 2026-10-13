import { useState } from 'react'
import { login } from '../lib/api'

export default function LoginPage({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('admin123')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      await login(username, password)
      onLogin()
    } catch (err: any) {
      setError(err.message || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 400, margin: '100px auto', padding: 24, border: '1px solid #ddd', borderRadius: 8 }}>
      <h2 style={{ textAlign: 'center' }}>认证清单整合系统</h2>
      <form onSubmit={handleSubmit}>
        <div style={{ marginBottom: 12 }}>
          <label>用户名</label>
          <input type="text" value={username} onChange={e => setUsername(e.target.value)}
            style={{ width: '100%', padding: 8, marginTop: 4 }} />
        </div>
        <div style={{ marginBottom: 12 }}>
          <label>密码</label>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)}
            style={{ width: '100%', padding: 8, marginTop: 4 }} />
        </div>
        {error && <div style={{ color: 'red', marginBottom: 12 }}>{error}</div>}
        <button type="submit" disabled={loading}
          style={{ width: '100%', padding: 10, background: '#1677ff', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}>
          {loading ? '登录中...' : '登录'}
        </button>
      </form>
    </div>
  )
}
