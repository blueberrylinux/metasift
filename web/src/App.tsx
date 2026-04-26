/**
 * Router scaffold. Phase 3.5 reshape follows the mockup's information
 * architecture — no Dashboard screen; `/` lands on Stew (chat home) and
 * the sidebar owns catalog-health metrics. `/settings` is a placeholder
 * for slice 2's LLM setup modal.
 *
 * Keeping this thin on purpose: route definitions live here, everything
 * real lives in screens/. QueryClient + BrowserRouter wrap in main.tsx.
 */

import { Navigate, Route, Routes } from 'react-router-dom';

import { DataSources } from './screens/DataSources';
import { DQ } from './screens/DQ';
import { Report } from './screens/Report';
import { Review } from './screens/Review';
import { Settings } from './screens/Settings';
import { Stew } from './screens/Stew';
import { StewConversation } from './screens/StewConversation';
import { Viz } from './screens/Viz';

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/chat" replace />} />
      <Route path="/chat" element={<Stew />} />
      <Route path="/chat/:conversationId" element={<StewConversation />} />
      <Route path="/review" element={<Review />} />
      <Route path="/data-sources" element={<DataSources />} />
      <Route path="/viz" element={<Viz />} />
      <Route path="/dq" element={<DQ />} />
      <Route path="/report" element={<Report />} />
      <Route path="/settings" element={<Settings />} />
    </Routes>
  );
}
