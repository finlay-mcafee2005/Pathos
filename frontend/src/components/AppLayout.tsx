import { Navigate, Outlet } from "react-router-dom";
import NavBar from "./NavBar";
import VerifyBanner from "./VerifyBanner";
import { isLoggedIn } from "../utils/session";

// Wraps every logged-in page with the nav bar.
// Sends logged-out users to the login page.
function AppLayout() {
  if (!isLoggedIn()) {
    return <Navigate to="/login" replace />;
  }
  return (
    <>
      <NavBar />
      <VerifyBanner />
      <Outlet />
    </>
  );
}

export default AppLayout;
