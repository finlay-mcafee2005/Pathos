import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import SignupPage from "./pages/SignupPage";
import LoginPage from "./pages/LoginPage";
import CheckinPage from "./pages/CheckinPage";
import RecommendationsPage from "./pages/RecommendationsPage";
import LogRunPage from "./pages/LogRunPage";
import MyClubPage from "./pages/MyClubPage";
import "./App.css";

function getStoredUserId(): string | null {
  return localStorage.getItem("user_id");
}

function HomeRedirect() {
  const userId = getStoredUserId();
  return userId ? <Navigate to="/checkin" replace /> : <Navigate to="/login" replace />;
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomeRedirect />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/checkin" element={<CheckinPage />} />
        <Route path="/recommendations" element={<RecommendationsPage />} />
        <Route path="/log-run" element={<LogRunPage />} />
        <Route path="/my-club" element={<MyClubPage />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
