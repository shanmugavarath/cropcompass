import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import ChatWindow from './components/ChatWindow'
import OnboardingWizard from './components/OnboardingWizard'

// Reads localStorage fresh each time the route is matched — avoids the stale
// closure bug where App (above BrowserRouter) never re-renders on navigation.
function ProtectedChat() {
  const farmerId = localStorage.getItem('farmer_id')
  return farmerId
    ? <ChatWindow farmerId={farmerId} />
    : <Navigate to="/onboarding" replace />
}

function DefaultRedirect() {
  const farmerId = localStorage.getItem('farmer_id')
  return <Navigate to={farmerId ? '/chat' : '/onboarding'} replace />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/onboarding" element={<OnboardingWizard />} />
        <Route path="/chat"       element={<ProtectedChat />} />
        <Route path="*"           element={<DefaultRedirect />} />
      </Routes>
    </BrowserRouter>
  )
}
