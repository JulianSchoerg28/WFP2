import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { register, login } from "../api";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  async function doRegister(e) {
    e.preventDefault();
    console.debug("doRegister", { username });
    setError(null);
    try {
      await register(username, password);
      // fallthrough to login
      const t0 = performance.now();
      const tokenResp = await login(username, password);
      const t1 = performance.now();
      console.debug(`login timing: ${(t1 - t0).toFixed(1)}ms`);
      localStorage.setItem("token", tokenResp.access_token);
      // notify auth-service about login for logging, then navigate
      try { await fetch(`${import.meta.env.VITE_AUTH_URL || 'http://localhost:8002'}/auth/logged_in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(username) }); } catch {};
      navigate("/products", { replace: true });
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    }
  }

  async function doLogin(e) {
    e.preventDefault();
    console.debug("doLogin", { username });
    setError(null);
    try {
      const t0 = performance.now();
      const tokenResp = await login(username, password);
      const t1 = performance.now();
      console.debug(`login timing: ${(t1 - t0).toFixed(1)}ms`);
      localStorage.setItem("token", tokenResp.access_token);
      try { await fetch(`${import.meta.env.VITE_AUTH_URL || 'http://localhost:8002'}/auth/logged_in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(username) }); } catch {};
      navigate("/products", { replace: true });
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    }
  }

  return (
    <div>
      <h2>Login / Register</h2>
      <form onSubmit={doLogin} style={{ display: "grid", gap: 8, maxWidth: 360 }}>
        <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="username" />
        <input value={password} onChange={(e) => setPassword(e.target.value)} placeholder="password" type="password" />
        <div style={{ display: "flex", gap: 8 }}>
          <button type="submit">Login</button>
          <button onClick={doRegister} type="button">Register</button>
        </div>
        {error && <div style={{ color: "red" }}>{error}</div>}
      </form>
    </div>
  );
}
