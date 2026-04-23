/**
 * Router scaffold. `/` is the dashboard; `/chat` + `/chat/:conversationId`
 * are Stew (Phase 2). Later: `/review`, `/viz`, `/dq`, `/report`, `/settings`.
 *
 * Keeping this thin on purpose: route definitions live here, everything
 * real lives in screens/. QueryClient + BrowserRouter wrap in main.tsx.
 */

import { Route, Routes } from 'react-router-dom';

import { Dashboard } from './screens/Dashboard';
import { DQ } from './screens/DQ';
import { Review } from './screens/Review';
import { Stew } from './screens/Stew';
import { StewConversation } from './screens/StewConversation';
import { Viz } from './screens/Viz';

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/chat" element={<Stew />} />
      <Route path="/chat/:conversationId" element={<StewConversation />} />
      <Route path="/review" element={<Review />} />
      <Route path="/viz" element={<Viz />} />
      <Route path="/dq" element={<DQ />} />
    </Routes>
  );
}
