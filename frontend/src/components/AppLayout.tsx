import { Navigate, Outlet } from "react-router-dom";
import NavBar from "./NavBar";

// Wraps every logged-in page with the nav bar.
// Sends logged-out users to the login page.
function AppLayout() {
  if (!localStorage.getItem("user_id")) {
    return <Navigate to="/login" replace />;
  }
  return (
    <>
      <NavBar />
      <Outlet />
    </>
  );
}

export default AppLayout;
