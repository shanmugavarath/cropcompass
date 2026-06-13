import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import ChatWindow from './components/ChatWindow'

function OnboardingPlaceholder() {
  const navigate = useNavigate()

  function enterChat() {
    localStorage.setItem('farmer_id', 'mock-farmer-001')
    navigate('/chat')
  }

  return (
    <div style={{ padding: '60px 24px', textAlign: 'center', maxWidth: 480, margin: '0 auto' }}>
      <h2 style={{ fontFamily: 'var(--font-display)', color: 'var(--color-green)', marginBottom: 12 }}>
        Farmer Onboarding
      </h2>
      <p style={{ color: 'var(--color-brown)', lineHeight: 1.6, marginBottom: 32 }}>
        The 3-step onboarding wizard will be implemented here (Task 4.3).
      </p>
      <button
        onClick={enterChat}
        style={{
          padding: '14px 28px',
          background: 'var(--color-green)',
          color: '#fff',
          border: 'none',
          borderRadius: 10,
          cursor: 'pointer',
          fontFamily: 'var(--font-body)',
          fontSize: 15,
          minHeight: 48,
        }}
      >
        Skip (dev) → Enter Chat
      </button>
    </div>
  )
}

export default function App() {
  const farmerId = localStorage.getItem('farmer_id')

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/onboarding" element={<OnboardingPlaceholder />} />
        <Route
          path="/chat"
          element={
            farmerId
              ? <ChatWindow farmerId={farmerId} />
              : <Navigate to="/onboarding" replace />
          }
        />
        <Route
          path="*"
          element={<Navigate to={farmerId ? '/chat' : '/onboarding'} replace />}
        />
      </Routes>
    </BrowserRouter>
  )
}
