import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import ThemeToggle from "./ThemeToggle";
import { clearSession } from "../utils/session";

const MAIN_LINKS = [
  { to: "/checkin", label: "Daily check-in" },
  { to: "/recommendations", label: "Recommendations" },
  { to: "/log-run", label: "Log a run" },
];

const MY_RUNNING_LINKS = [
  { to: "/runs", label: "Past runs" },
  { to: "/favorites", label: "Favorite routes" },
  { to: "/stats", label: "Stats" },
  { to: "/groups", label: "Group runs" },
  { to: "/run-together", label: "Run together" },
  { to: "/account", label: "Settings" },
];

function NavBar() {
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);       // mobile menu
  const [dropdownOpen, setDropdownOpen] = useState(false); // "My running" dropdown
  const dropdownRef = useRef<HTMLDivElement>(null);

  // close menus whenever the page changes
  useEffect(() => {
    setMenuOpen(false);
    setDropdownOpen(false);
  }, [location.pathname]);

  // close the dropdown when clicking outside it
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  function handleLogout() {
    clearSession();
    navigate("/login");
  }

  const myRunningActive = MY_RUNNING_LINKS.some((l) => location.pathname.startsWith(l.to));

  return (
    <nav className="navbar">
      <div className="navbar-inner">
        <Link to="/checkin" className="navbar-brand">
          <img src="/favicon.png" alt="" width={34} height={34} />
          <span>Pathos</span>
        </Link>

        <button
          className="navbar-burger"
          aria-label="Toggle menu"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((o) => !o)}
        >
          {menuOpen ? "✕" : "☰"}
        </button>

        <div className={`navbar-links ${menuOpen ? "open" : ""}`}>
          {MAIN_LINKS.map((l) => (
            <NavLink key={l.to} to={l.to} className="navbar-link">
              {l.label}
            </NavLink>
          ))}

          <div className="navbar-dropdown" ref={dropdownRef}>
            <button
              className={`navbar-link navbar-dropdown-toggle ${myRunningActive ? "active" : ""}`}
              aria-expanded={dropdownOpen}
              onClick={() => setDropdownOpen((o) => !o)}
            >
              My running <span className={`chevron ${dropdownOpen ? "open" : ""}`}>▾</span>
            </button>
            {dropdownOpen && (
              <div className="navbar-dropdown-menu">
                {MY_RUNNING_LINKS.map((l) => (
                  <NavLink key={l.to} to={l.to} className="navbar-dropdown-item">
                    {l.label}
                  </NavLink>
                ))}
              </div>
            )}
          </div>

          <div className="navbar-actions">
            <ThemeToggle />
            <button className="navbar-logout" onClick={handleLogout}>
              Log out
            </button>
          </div>
        </div>

        {/* phone menu: one clean list instead of the desktop bar squeezed down */}
        <div className={`navbar-mobile ${menuOpen ? "open" : ""}`}>
          <span className="nm-label">Today</span>
          {MAIN_LINKS.map((l) => (
            <NavLink key={l.to} to={l.to} className="nm-link">
              {l.label}<span className="nm-arrow" aria-hidden="true">›</span>
            </NavLink>
          ))}
          <span className="nm-label">My running</span>
          {MY_RUNNING_LINKS.map((l) => (
            <NavLink key={l.to} to={l.to} className="nm-link">
              {l.label}<span className="nm-arrow" aria-hidden="true">›</span>
            </NavLink>
          ))}
          <div className="nm-foot">
            <ThemeToggle />
            <button className="nm-logout" onClick={handleLogout}>Log out</button>
          </div>
        </div>
      </div>
    </nav>
  );
}

export default NavBar;
