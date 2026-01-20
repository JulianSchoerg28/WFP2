import React, { useEffect, useState } from "react";
import { fetchProducts, createProduct, updateProduct, deleteProduct, fetchOrders, updateOrderStatus, fetchLogs, fetchHealth, fetchMetrics } from "../api";
import { getToken, parseJwt } from "../utils/auth";

export default function Admin() {
  const [products, setProducts] = useState([]);
  const [orders, setOrders] = useState([]);
  const [newProduct, setNewProduct] = useState({ name: "", price: 0.0, description: "" });

  async function load() {
    try {
      const p = await fetchProducts({ page: 1, per_page: 100 });
      setProducts(p.data || []);
    } catch (err) {
      console.error(err);
    }
    // load orders only if current token belongs to an admin
    try {
      const t = getToken();
      const claims = t ? parseJwt(t) : null;
      if (claims && claims.role === "admin") {
        const o = await fetchOrders();
        setOrders(o || []);
      } else {
        setOrders([]);
      }
    } catch (err) {
      console.error(err);
    }
  }

  useEffect(() => { load(); }, []);

  const [logs, setLogs] = useState([]);
  const [health, setHealth] = useState({});
  const [metrics, setMetrics] = useState({});
  const [metricService, setMetricService] = useState("product");
  const [logLevel, setLogLevel] = useState(null);

  async function loadLogs() {
    try {
      const ev = await fetchLogs({ level: logLevel, limit: 200 });
      setLogs(ev || []);
    } catch (err) { console.error(err); }
  }

  async function loadHealth() {
    try {
      const GATEWAY = import.meta.env.VITE_GATEWAY_URL || "http://localhost:8000";
      const svcs = {
        // Use the gateway as default so browser-based health checks succeed
        auth: `${GATEWAY}/auth`,
        product: `${GATEWAY}/products`,
        order: `${GATEWAY}/orders`,
        payment: `${GATEWAY}/payment`,
        cart: `${GATEWAY}/cart`,
        log: `${GATEWAY}/log`,
      };
      const results = {};
      await Promise.all(Object.entries(svcs).map(async ([k, url]) => {
        results[k] = await fetchHealth(url);
      }));
      setHealth(results);
      // fetch metrics for services (best-effort)
      const mres = {};
      await Promise.all(Object.entries(svcs).map(async ([k, url]) => {
        try {
          mres[k] = await fetchMetrics(url);
        } catch (err) {
          mres[k] = null;
        }
      }));
      setMetrics(mres);
    } catch (err) { console.error(err); }
  }

  useEffect(() => { loadLogs(); loadHealth(); }, [logLevel]);

  async function handleCreate(e) {
    e.preventDefault();
    try {
      const t = getToken();
      if (!t) return alert("You must be logged in as admin to create products.");
      const claims = parseJwt(t);
      if (!claims || claims.role !== "admin") return alert("Admin role required");
      await createProduct(newProduct);
      setNewProduct({ name: "", price: 0.0, description: "" });
      load();
    } catch (err) { console.error(err); }
  }

  async function handleDelete(id) {
    if (!confirm("Delete product?")) return;
    await deleteProduct(id);
    load();
  }

  async function changeOrderStatus(id, status) {
    await updateOrderStatus(id, status);
    load();
  }

  return (
    <div>
      <h2>Admin</h2>
      {!(() => {
        const t = getToken();
        const claims = t ? parseJwt(t) : null;
        return claims && claims.role === "admin";
      })() && <div style={{ color: 'red' }}>You are not logged in as admin. Login with an admin account to manage products and orders.</div>}
      <section>
        <h3>Products</h3>
        {(() => {
          const t = getToken();
          const claims = t ? parseJwt(t) : null;
          const isAdmin = claims && claims.role === "admin";
          return (
            <form onSubmit={handleCreate} style={{ marginBottom: 8 }}>
              <input placeholder="name" value={newProduct.name} onChange={(e)=>setNewProduct({...newProduct, name: e.target.value})} disabled={!isAdmin} />
              <input placeholder="price" type="number" step="0.01" value={newProduct.price} onChange={(e)=>setNewProduct({...newProduct, price: parseFloat(e.target.value)})} disabled={!isAdmin} />
              <input placeholder="description" value={newProduct.description} onChange={(e)=>setNewProduct({...newProduct, description: e.target.value})} disabled={!isAdmin} />
              <button type="submit" disabled={!isAdmin}>{isAdmin ? 'Create' : 'Admin only'}</button>
            </form>
          );
        })()}
        <ul>
          {products.map(p => (
            <li key={p.id}>{p.id} — {p.name} — €{(p.price || 0).toFixed(2)} <button onClick={()=>handleDelete(p.id)}>Delete</button></li>
          ))}
        </ul>
      </section>
      <section style={{ marginTop: 20 }}>
        <h3>Logs & Health</h3>
        <div style={{ marginBottom: 8 }}>
          <label>Level: </label>
          <select value={logLevel || ""} onChange={(e) => setLogLevel(e.target.value || null)}>
            <option value="">All</option>
            <option value="INFO">INFO</option>
            <option value="WARN">WARN</option>
            <option value="ERROR">ERROR</option>
          </select>
          <button onClick={() => { loadLogs(); loadHealth(); }} style={{ marginLeft: 8 }}>Refresh</button>
        </div>

        <div style={{ display: 'flex', gap: 20 }}>
          <div style={{ flex: 1 }}>
            <h4>Service Health</h4>
            <ul>
              {Object.entries(health).map(([k, v]) => (
                <li key={k}><strong>{k}</strong>: {v.ok ? JSON.stringify(v.body) : (v.error || `status:${v.status}`)}</li>
              ))}
            </ul>
          </div>
          <div style={{ flex: 2 }}>
            <h4>Recent Logs</h4>
            <div style={{ maxHeight: 300, overflow: 'auto', border: '1px solid #ddd', padding: 8 }}>
              {logs.map((l, i) => (
                <div key={i} style={{ marginBottom: 6 }}>
                  <strong>[{l.ts}] {l.level}</strong> <em>{l.service}</em> — {l.event}
                  <div style={{ fontSize: 12, color: '#333' }}>{JSON.stringify(l.payload)}</div>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 12 }}>
              <h4>Metrics</h4>
              <div style={{ marginBottom: 8 }}>
                <label>Service: </label>
                <select value={metricService} onChange={(e) => setMetricService(e.target.value)}>
                  {Object.keys(health).map(k => <option key={k} value={k}>{k}</option>)}
                </select>
                <button onClick={() => { loadHealth(); }} style={{ marginLeft: 8 }}>Refresh</button>
              </div>
              <pre style={{ maxHeight: 300, overflow: 'auto', background: '#f7f7f7', padding: 8 }}>
                {metrics[metricService] || 'No metrics available for this service.'}
              </pre>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
