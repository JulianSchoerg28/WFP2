import React, { useEffect, useState } from "react";
import { Outlet, Link, useNavigate } from "react-router-dom";
import { getToken, isTokenValid, parseJwt, clearAuth } from "./utils/auth";

export default function App() {
  const [token, setToken] = useState(getToken());
  const [expiresIn, setExpiresIn] = useState(null);

  const navigate = useNavigate();

  function logout() {
    clearAuth();
    setToken(null);
    try {
      // replace current history entry so Back won't return to a cached logged-in page
      window.history.replaceState({}, "", "/login");
    } catch (e) {}
    // navigate to login via router to avoid full page reloads
    navigate("/login", { replace: true });
  }

  useEffect(() => {
    let timer;
    function scheduleLogout() {
      const t = getToken();
      setToken(t);
      if (!t) return;
      const claims = parseJwt(t);
      if (!claims || !claims.exp) return;
      const msLeft = claims.exp * 1000 - Date.now();
      if (msLeft <= 0) {
        logout();
        return;
      }
      setExpiresIn(Math.floor(msLeft / 1000));
      timer = setTimeout(() => {
        logout();
      }, msLeft);
    }

    scheduleLogout();
    const interval = setInterval(() => {
      const t = getToken();
      if (!t) return;
      if (!isTokenValid(t)) {
        logout();
      }
    }, 5000);

    // Handle bfcache / back-forward cache and back navigation: if the page is restored
    // from cache, re-check token and force redirect to login when missing/expired.
    function handlePageShow(e) {
      const t = getToken();
      if (!t || !isTokenValid(t)) {
        try { window.history.replaceState({}, "", "/login"); } catch (er) {}
        navigate("/login", { replace: true });
      }
    }

    // Also handle popstate (back/forward) navigations in SPA
    function handlePopState() {
      const t = getToken();
      if (!t || !isTokenValid(t)) {
        try { window.history.replaceState({}, "", "/login"); } catch (er) {}
        navigate("/login", { replace: true });
      }
    }

    window.addEventListener("pageshow", handlePageShow);
    window.addEventListener("popstate", handlePopState);

    return () => {
      if (timer) clearTimeout(timer);
      clearInterval(interval);
      window.removeEventListener("pageshow", handlePageShow);
      window.removeEventListener("popstate", handlePopState);
    };
  }, [navigate]);

  const claims = token ? parseJwt(token) : null;
  const isAdmin = claims && claims.role === "admin";

  return (
    <div style={{ padding: 20, fontFamily: "Arial, sans-serif" }}>
      <header style={{ marginBottom: 20 }}>
        <h1>MicroShop</h1>
        <nav>
          <Link to="/products">Products</Link> {" | "}
          <Link to="/cart">Cart</Link> {" | "}
          {isAdmin && <Link to="/admin">Admin</Link>} {isAdmin && " | "}
          {token && <Link to="/myorders">My Orders</Link>} {" | "}
          {token ? (
            <>
              <span style={{ marginRight: 8 }}>Expires in: {expiresIn ?? "—"}s</span>
              <button onClick={logout}>Logout</button>
            </>
          ) : (
            <Link to="/login">Login</Link>
          )}
        </nav>
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
