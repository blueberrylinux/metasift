/**
 * Phase 1 router scaffold. One route for now — Dashboard at `/`. Phase 2
 * adds `/chat`, Phase 3 `/review`, Phase 5 `/viz` + `/dq`, Phase 6 `/report`
 * + `/settings`.
 *
 * Keeping this thin on purpose: route definitions live here, everything
 * real lives in screens/. QueryClient + BrowserRouter wrap in main.tsx.
 */

import { Route, Routes } from 'react-router-dom';

import { Dashboard } from './screens/Dashboard';

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
    </Routes>
  );
}
