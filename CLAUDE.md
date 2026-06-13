# CLAUDE.md - Frontend Website Rules

## Always do first
- **Invoke the `frontend-design` skill** before writing any frontend code, every session, no exceptions.
- **Follow `coding_guidelines.md`** for all Vite + React code — structure, components, state, styling, performance, accessibility, and testing rules all apply.

## Pinned library versions

All `ui/` code must use these versions. Do not upgrade without updating this file and `docs/frontend_contract.md`.

### Runtime
| Package | Installed version | Notes |
|---------|------------------|-------|
| Node.js | **20 LTS** | Install via `nodesource` or `nvm` |
| `vite` | **8.0.16** | Scaffolded via `npm create vite@latest ui -- --template react` |
| `react` | **19.2.7** | Bundled with the Vite react template |
| `react-dom` | **19.2.7** | Matches react version |
| `react-router-dom` | **6.30.4** | v6 API |
| `axios` | **1.17.0** | HTTP client for REST calls |
| `socket.io-client` | **4.8.3** | Must match `python-socketio@5.x` on the backend — version mismatch breaks the transport |

### Dev / test
| Package | Installed version | Notes |
|---------|------------------|-------|
| `vitest` | **4.1.8** | Test runner (Vite-native, replaces Jest) |
| `@testing-library/react` | **16.3.2** | Component testing |
| `@testing-library/jest-dom` | **6.9.1** | Custom matchers |
| `jsdom` | **25.0.1** | DOM environment for Vitest |
| `msw` | **2.14.6** | Mock Service Worker for API mocking |
| `@vitejs/plugin-react` | **6.0.2** | Vite React plugin (babel transforms) |

### Install commands
```bash
# Production deps
npm install axios socket.io-client react-router-dom

# Dev deps
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom msw
```