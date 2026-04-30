import { useState, useEffect, useCallback } from 'react'
import AuthScreen from './pages/AuthScreen'
import DashboardView from './pages/Dashboard'
import AccountPage from './pages/AccountPage'
import Sidebar from './components/Sidebar'
import CookieConsent from './components/CookieConsent'
import { theme } from './theme'

export default function App() {
  const [page, setPage] = useState('dashboard')
  const [collapsed, setCollapsed] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const [user, setUser] = useState(() => {
    return !!localStorage.getItem('atx_token')
  })

  // Listen for 401 logout events from api client
  useEffect(() => {
    const onLogout = () => setUser(false)
    window.addEventListener('atx-logout', onLogout)
    return () => window.removeEventListener('atx-logout', onLogout)
  }, [])

  const handleLogin = useCallback(() => {
    setUser(true)
    setPage('dashboard')
    setRefreshKey(k => k + 1)
  }, [])

  const handleLogout = useCallback(() => {
    localStorage.removeItem('atx_token')
    localStorage.removeItem('atx_refresh')
    setUser(false)
  }, [])

  const handleNav = useCallback((p) => {
    setPage(p)
    if (p === 'dashboard') setRefreshKey(k => k + 1)
  }, [])

  if (!user) {
    return (
      <>
        <AuthScreen onLogin={handleLogin} />
        <CookieConsent />
      </>
    )
  }

  // Placeholder for pages not yet built
  const PagePlaceholder = ({name}) => (
    <div style={{display:'flex',flexDirection:'column',alignItems:'center',justifyContent:'center',padding:80,color:theme.textMuted}}>
      <div style={{fontSize:48,marginBottom:16}}>
        {name === 'invoices' ? '\uD83D\uDCCB' : name === 'upload' ? '\uD83D\uDCC2' : name === 'bookkeeping' ? '\uD83D\uDCD6' : name === 'export' ? '\uD83D\uDCE4' : name === 'chat' ? '\uD83E\uDD16' : '\u2753'}
      </div>
      <div style={{fontSize:20,fontWeight:600,color:theme.text,marginBottom:8}}>{name.charAt(0).toUpperCase()+name.slice(1)}</div>
      <div style={{fontSize:14,color:theme.textMuted}}>Diese Seite wird in der Monolith-Version unter / bereitgestellt.</div>
    </div>
  )

  const renderPage = () => {
    switch(page) {
      case 'dashboard': return <DashboardView refreshKey={refreshKey} />
      case 'account': return <AccountPage onLogout={handleLogout} />
      default: return <PagePlaceholder name={page} />
    }
  }

  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: theme.bg, fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" }}>
      <Sidebar active={page} onNav={handleNav} onLogout={handleLogout} collapsed={collapsed} onToggle={() => setCollapsed(c => !c)} />
      <div style={{ flex: 1, padding: 32, overflowY: 'auto' }}>
        {renderPage()}
      </div>
      <CookieConsent />
    </div>
  )
}
