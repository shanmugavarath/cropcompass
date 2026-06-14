import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import ChatWindow from './components/ChatWindow'
import OnboardingWizard from './components/OnboardingWizard'

export default function App() {
  const farmerId = localStorage.getItem('farmer_id')
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/onboarding" element={<OnboardingWizard />} />
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
