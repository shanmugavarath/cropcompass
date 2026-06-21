# Vite + React Coding Guidelines

## Project Structure

- Keep source files under `src/`. Group by feature, not by file type: `src/features/chat/`, `src/features/onboarding/`, etc.
- Colocate component, styles, and tests in the same feature folder.
- Shared primitives go in `src/components/`, shared hooks in `src/hooks/`, shared utilities in `src/lib/`.
- Entry point is `src/main.jsx` (or `.tsx`); root component is `src/App.jsx`.

## Components

- One component per file. File name matches the exported component name (`ChatInput.jsx` exports `ChatInput`).
- Prefer function components with hooks — no class components.
- Keep components small and focused on a single responsibility. Extract sub-components when JSX exceeds ~60 lines.
- Accept only what a component needs via props; avoid prop drilling beyond two levels — use context or a state store instead.
- Use named exports for components; default exports only for route-level pages.

## State Management

- Prefer local `useState` / `useReducer` for UI-only state.
- Lift state to the nearest common ancestor; use React Context for subtree-wide state.
- Keep context values stable — memoize with `useMemo`/`useCallback` to avoid unnecessary re-renders.
- Do not store derived values in state; compute them inline or with `useMemo`.

## Hooks

- Custom hooks live in `src/hooks/` and are prefixed with `use` (`useChat`, `useLanguage`).
- A hook should do one thing. If it grows beyond ~40 lines of logic, split it.
- Declare all dependencies in the `useEffect`/`useCallback`/`useMemo` dependency array — no suppressions.

## Styling

- Use Tailwind CSS utility classes as the primary styling mechanism.
- Avoid inline `style` props except for dynamic values that Tailwind cannot express.
- Do not mix Tailwind with a separate CSS-in-JS library.
- For Indic script rendering, always set `font-family` explicitly on text containers and test at 14 px / 16 px body size.

## Vite-specific

- Use `import.meta.env.VITE_*` for environment variables; never access `process.env` directly.
- Static assets referenced in JSX go in `src/assets/`; assets not imported by code go in `public/`.
- Keep `vite.config.js` minimal — add plugins only when genuinely needed.
- Rely on Vite's native ES module dev server; do not add a Webpack layer.

## Performance

- Code-split at the route level using `React.lazy` + `Suspense`.
- Wrap expensive pure computations with `useMemo`; wrap callbacks passed as props with `useCallback`.
- Avoid anonymous functions as event handlers inside JSX — define them outside or use `useCallback`.
- Profile with React DevTools before optimising — never pre-optimise without evidence.

## Accessibility

- Every interactive element must be keyboard-reachable and have a visible focus ring.
- Use semantic HTML elements (`<button>`, `<nav>`, `<main>`, `<section>`) before reaching for `<div>`.
- Provide `aria-label` or visible label text for all form inputs and icon-only buttons.
- Test with a screen reader for any new user-facing flow.

## Error Handling

- Wrap route-level components in an `ErrorBoundary`.
- Surface API errors in the UI with a user-friendly message; log the raw error to the console in development only.
- Never swallow errors silently (`catch` blocks must log or rethrow).

## Testing

- Unit-test pure utility functions and custom hooks with Vitest.
- Component tests use React Testing Library — test behaviour, not implementation details.
- Do not mock the network at the module level; use MSW (Mock Service Worker) for API mocking.

## Imports and Modules

- Use path aliases (`@/`) configured in `vite.config.js` and `jsconfig.json` instead of long relative paths.
- Import order: external libraries → internal aliases → relative imports. Keep each group sorted alphabetically.
- Tree-shake aggressively — import only the symbols you use, not entire libraries.

## Code Quality

- No unused variables, imports, or dead code — the linter enforces this.
- Functions should be pure where possible; side effects belong in hooks or event handlers.
- Avoid magic numbers and strings — name constants at the top of the file or in `src/lib/constants.js`.
- Keep files under 200 lines; if a file grows beyond that, split it.
