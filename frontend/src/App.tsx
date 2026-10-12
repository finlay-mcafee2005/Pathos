import { useCallback, useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import SignupPage from "./pages/SignupPage";
import LoginPage from "./pages/LoginPage";
import CheckinPage from "./pages/CheckinPage";
import RecommendationsPage from "./pages/RecommendationsPage";
import LogRunPage from "./pages/LogRunPage";
import PastRunsPage from "./pages/PastRunsPage";
import FavoritesPage from "./pages/FavoritesPage";
import StatsPage from "./pages/StatsPage";
import RunTogetherPage from "./pages/RunTogetherPage";
import GroupsPage from "./pages/GroupsPage";
import FollowPage from "./pages/FollowPage";
import AppLayout from "./components/AppLayout";
import Splash, { shouldShowSplash } from "./components/Splash";
import "./App.css";
import { isLoggedIn } from "./utils/session";

function HomeRedirect() {
  return isLoggedIn() ? <Navigate to="/checkin" replace /> : <Navigate to="/login" replace />;
}

function App() {
  // animated logo intro, shown once per session before the login page
  const [showSplash, setShowSplash] = useState(() => shouldShowSplash(isLoggedIn()));
  const hideSplash = useCallback(() => setShowSplash(false), []);

  return (
    <BrowserRouter>
      {showSplash && <Splash onDone={hideSplash} />}
      <Routes>
        <Route path="/" element={<HomeRedirect />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/follow" element={<FollowPage />} />

        {/* logged-in pages: all share the nav bar */}
        <Route element={<AppLayout />}>
          <Route path="/checkin" element={<CheckinPage />} />
          <Route path="/recommendations" element={<RecommendationsPage />} />
          <Route path="/log-run" element={<LogRunPage />} />
          <Route path="/runs" element={<PastRunsPage />} />
          <Route path="/favorites" element={<FavoritesPage />} />
          <Route path="/stats" element={<StatsPage />} />
          <Route path="/groups" element={<GroupsPage />} />
          <Route path="/run-together" element={<RunTogetherPage />} />
          <Route path="/my-club" element={<Navigate to="/groups" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
