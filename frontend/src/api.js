import axios from "axios";

const GATEWAY_URL = import.meta.env.VITE_GATEWAY_URL || "http://localhost:8000";
const AUTH_URL = GATEWAY_URL;
const PRODUCT_URL = GATEWAY_URL;
const ORDER_URL = GATEWAY_URL;
const PAYMENT_URL = GATEWAY_URL;
const CART_URL = GATEWAY_URL;
const LOG_URL = GATEWAY_URL;

export const authClient = axios.create({ baseURL: AUTH_URL });
export const productClient = axios.create({ baseURL: PRODUCT_URL });

export async function register(username, password) {
  return authClient.post("/auth/register/", { username, password });
}

export async function login(username, password) {
  const r = await authClient.post("/token", new URLSearchParams({ username, password }));
  return r.data;
}

export async function fetchProducts({ q, token } = {}) {
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const r = await productClient.get("/products/", { params: { q }, headers });
  return r;
}

export async function createProduct(product) {
  const token = localStorage.getItem("token");
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const r = await productClient.post("/products/", product, { headers });
  return r.data;
}

export async function updateProduct(product_id, data) {
  const token = localStorage.getItem("token");
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const r = await productClient.patch(`/products/${product_id}`, data, { headers });
  return r.data;
}

export async function deleteProduct(product_id) {
  const token = localStorage.getItem("token");
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const r = await productClient.delete(`/products/${product_id}`, { headers });
  return r.data;
}

export async function fetchOrders() {
  const token = localStorage.getItem("token");
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const r = await fetch(`${ORDER_URL}/orders`, { headers });
  return r.json();
}

export async function updateOrderStatus(order_id, status) {
  const token = localStorage.getItem("token");
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const r = await fetch(`${ORDER_URL}/orders/${order_id}?status=${encodeURIComponent(status)}`, {
    method: "PATCH",
    headers,
  });
  return r.json();
}

export async function createOrder() {
  const token = localStorage.getItem("token");
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const r = await fetch(`${ORDER_URL}/orders`, {
    method: "POST",
    headers,
  });
  return r.json();
}

export async function createPayment(order_id, method = "mock") {
  const token = localStorage.getItem("token");
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const url = `${PAYMENT_URL}/payment`;
  try {
    console.debug("createPayment ->", { url, headers, body: { order_id, method } });
    const r = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify({ order_id, method }),
    });
    // Accept 200 (SUCCESS) or 202 (PENDING). Do not throw on 202 so UI can show a pending state.
    const bodyText = await r.text().catch(() => "");
    let parsed = null;
    try { parsed = bodyText ? JSON.parse(bodyText) : null; } catch (_) { parsed = { raw: bodyText }; }
    if (r.status === 200) return parsed;
    if (r.status === 202) return parsed || { result: 'PENDING' };
    // other statuses are errors
    console.error("createPayment non-OK response", r.status, bodyText);
    throw new Error(`Payment request failed: ${r.status}`);
  } catch (err) {
    console.error("createPayment error", err);
    throw err;
  }
}

// Cart service API
export async function fetchCartServer(token) {
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const url = `${CART_URL}/cart`;
  try {
    console.debug("fetchCartServer ->", { url, headers });
    const r = await fetch(url, { headers });
    if (!r.ok) {
      const text = await r.text().catch(() => "<no-body>");
      console.error("fetchCartServer non-OK", r.status, text);
      throw new Error(`fetchCartServer failed: ${r.status}`);
    }
    return r.json();
  } catch (err) {
    console.error("fetchCartServer error", err);
    throw err;
  }
}

export async function addToCartServer(product_id, quantity = 1, token) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const url = `${CART_URL}/cart/items`;
  try {
    console.debug("addToCartServer ->", { url, headers, body: { product_id, quantity } });
    const r = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify({ product_id, quantity }),
    });
    if (!r.ok) {
      const text = await r.text().catch(() => "<no-body>");
      console.error("addToCartServer non-OK", r.status, text);
      throw new Error(`addToCartServer failed: ${r.status}`);
    }
    return r.json();
  } catch (err) {
    console.error("addToCartServer error", err);
    throw err;
  }
}

export async function removeFromCartServer(product_id, token, quantity = 1) {
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const qs = quantity ? `?quantity=${encodeURIComponent(quantity)}` : "";
  const url = `${CART_URL}/cart/items/${product_id}${qs}`;
  try {
    console.debug("removeFromCartServer ->", { url, headers });
    const r = await fetch(url, {
      method: "DELETE",
      headers,
    });
    if (!r.ok) {
      const text = await r.text().catch(() => "<no-body>");
      console.error("removeFromCartServer non-OK", r.status, text);
      throw new Error(`removeFromCartServer failed: ${r.status}`);
    }
    return r.json();
  } catch (err) {
    console.error("removeFromCartServer error", err);
    throw err;
  }
}

export async function clearCartServer(token) {
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const url = `${CART_URL}/cart`;
  try {
    const r = await fetch(url, { method: 'DELETE', headers });
    if (!r.ok) {
      const text = await r.text().catch(() => "<no-body>");
      console.error("clearCartServer non-OK", r.status, text);
      throw new Error(`clearCartServer failed: ${r.status}`);
    }
    return r.json();
  } catch (err) {
    console.error("clearCartServer error", err);
    throw err;
  }
}

export async function fetchMyOrders(token) {
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const r = await fetch(`${ORDER_URL}/myorders`, { headers });
  return r.json();
}

export async function fetchOrder(order_id) {
  const token = localStorage.getItem("token");
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const r = await fetch(`${ORDER_URL}/orders/${order_id}`, { headers });
  if (!r.ok) {
    const text = await r.text().catch(() => "<no-body>");
    throw new Error(`fetchOrder failed: ${r.status} ${text}`);
  }
  return r.json();
}

export async function fetchProduct(product_id) {
  const r = await productClient.get(`/products/${product_id}`);
  return r.data;
}

export async function fetchLogs({ level = null, limit = 100 } = {}) {
  const params = new URLSearchParams();
  if (level) params.set('level', level);
  params.set('limit', String(limit));
  const url = `${LOG_URL}/events?${params.toString()}`;
  const r = await fetch(url);
  return r.json();
}

export async function fetchMetrics(baseUrl) {
  const url = `${baseUrl}/metrics`;
  const r = await fetch(url);
  if (!r.ok) {
    const text = await r.text().catch(() => "<no-body>");
    throw new Error(`metrics request failed: ${r.status} ${text}`);
  }
  return r.text();
}

export async function fetchHealth(url) {
  try {
    const r = await fetch(`${url}/health`);
    if (!r.ok) return { ok: false, status: r.status };
    const j = await r.json();
    return { ok: true, body: j };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}
