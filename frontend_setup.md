# Frontend Setup — CropCompass (React + Vite)

## Prerequisites

- **Node.js** v18 or later — [nodejs.org](https://nodejs.org)
- **npm** v9 or later (bundled with Node.js)

Verify your versions:

```bash
node -v
npm -v
```

---

## 1. Navigate to the UI directory

```bash
cd ui
```

All commands below are run from inside the `ui/` directory.

---

## 2. Install dependencies

```bash
npm install
```

This installs all runtime and dev dependencies declared in `package.json`, including:

| Package | Purpose |
|---|---|
| `react` / `react-dom` | UI framework |
| `react-router-dom` | Client-side routing |
| `axios` | HTTP client for API calls |
| `socket.io-client` | WebSocket connection to backend |
| `vite` | Build tool and dev server |
| `@vitejs/plugin-react` | Vite plugin for React/JSX support |
| `msw` | Mock Service Worker for API mocking in dev |
| `vitest` | Unit test runner |

---

## 3. Configure the mock server (optional)

The app reads `VITE_USE_MOCK` from `ui/.env`. Set it to `true` to start the MSW mock service worker instead of hitting the real backend:

```env
# ui/.env
VITE_USE_MOCK=true
VITE_API_URL=http://localhost:8000
```

When `VITE_USE_MOCK=true`, `main.jsx` imports and starts the MSW browser worker (`src/api/mock/server.js`) before mounting the React app. The mock server intercepts all API calls (`/api/districts`, `/api/profile`, `/api/forecast`, `/api/chat`) and returns canned responses — no real backend is needed. The pre-generated service worker script is at `public/mockServiceWorker.js`.

Set `VITE_USE_MOCK=false` (the default) to route all requests to the real backend at `VITE_API_URL`.

---

## 4. Run the development server

```bash
npm run dev
```

Vite starts a local dev server, typically at **http://localhost:5173**.  
The server supports Hot Module Replacement (HMR) — changes to source files reload instantly in the browser.

---

## 5. Build for production

```bash
npm run build
```

Output is written to `ui/dist/`. The build is optimized and minified.

---

## 6. Preview the production build locally

```bash
npm run preview
```

Serves the `dist/` folder at **http://localhost:4173** for a local production preview.

---

## 7. Run the linter

```bash
npm run lint
```

Uses ESLint with the React hooks and React Refresh plugins configured in `eslint.config.js`.

---

## 8. Run unit tests

```bash
npm run test
```

Runs the Vitest test suite (uses jsdom environment and `@testing-library/react`).

---

## Project structure (inside `ui/src/`)

```
src/
  main.jsx              # App entry point
  App.jsx               # Root component with routing
  components/           # Reusable UI components
    ChatWindow.jsx
    InputBar.jsx
    LanguageTag.jsx
    MessageBubble.jsx
    OnboardingWizard.jsx
    RecommendationCard.jsx
  hooks/
    useChat.js          # Chat state and WebSocket logic
  api/
    client.js           # Axios instance
    socket.js           # Socket.IO client
    mock/
      server.js         # MSW mock server (dev only)
  localization/         # i18n strings for 9 Indian languages
```

---

## Path alias

The `@` alias resolves to `ui/src/`. Use it in imports:

```js
import ChatWindow from '@/components/ChatWindow';
```

---

## Notes

- Indic font files are served from `public/fonts/`.
