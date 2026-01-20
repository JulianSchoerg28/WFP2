import React, { useEffect, useState } from "react";
import { fetchMyOrders, fetchProduct, createPayment } from "../api";
import { getToken } from "../utils/auth";

function parseItems(itemsStr) {
  if (!itemsStr) return [];
  try {
    // Try JSON first
    return JSON.parse(itemsStr);
  } catch (_) {}
  try {
    // Fallback: replace single quotes with double quotes
    const s = itemsStr.replace(/'/g, '"');
    return JSON.parse(s);
  } catch (err) {
    console.error("Could not parse items string", err, itemsStr);
    return [];
  }
}

export default function MyOrders() {
  const [orders, setOrders] = useState([]);
  const [retrying, setRetrying] = useState({});
  const [productsCache] = useState(new Map());

  async function enrichOrderItems(items) {
    const enriched = [];
    for (const it of items) {
      const pid = it.product_id || it.productId || it.id;
      const qty = it.quantity || it.qty || 1;
      if (!pid) continue;
      let prod = productsCache.get(pid);
      if (!prod) {
        try {
          prod = await fetchProduct(pid);
          productsCache.set(pid, prod);
        } catch (err) {
          prod = { id: pid, name: `#${pid}`, price: 0 };
        }
      }
      enriched.push({ product: prod, quantity: qty });
    }
    return enriched;
  }

  async function load() {
    const token = getToken();
    try {
      const data = await fetchMyOrders(token);
      const list = data || [];
      // enrich each order with product details
      const fully = [];
      for (const o of list) {
        const rawItems = parseItems(o.items);
        const items = await enrichOrderItems(rawItems);
        fully.push({ ...o, parsedItems: items });
      }
      setOrders(fully);
    } catch (err) {
      console.error(err);
    }
  }

  // initial load
  useEffect(() => { load(); }, []);

  // poll orders while there are pending or failed payments
  useEffect(() => {
    let timer = null;
    function needsPolling(list) {
      return list.some(o => ['PENDING_PAYMENT', 'PAYMENT_FAILED', 'PENDING'].includes(o.status));
    }
    if (needsPolling(orders)) {
      timer = setInterval(() => { load(); }, 5000);
    }
    return () => { if (timer) clearInterval(timer); };
  }, [orders]);

  async function handleRetry(orderId) {
    try {
      setRetrying(prev => ({ ...prev, [orderId]: true }));
      await createPayment(orderId);
      // reload orders to pick up status changes
      await load();
    } catch (err) {
      console.error('Retry payment failed', err);
    } finally {
      setRetrying(prev => ({ ...prev, [orderId]: false }));
    }
  }

  return (
    <div>
      <h2>My Orders</h2>
      {orders.length === 0 && <div>No orders found.</div>}
      {orders.map(o => (
        <div key={o.id} style={{ border: '1px solid #ddd', padding: 12, marginBottom: 8, borderRadius: 6 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <div><strong>Order #{o.id}</strong> — {o.status}</div>
            <div style={{ color: '#666' }}>{o.created_at ? new Date(o.created_at).toLocaleString() : ''}</div>
          </div>
          <ul style={{ marginTop: 8 }}>
            {o.parsedItems.map((it, idx) => (
              <li key={idx}>
                {it.product.name} — qty {it.quantity} — €{((it.product.price||0) * it.quantity).toFixed(2)}
              </li>
            ))}
          </ul>
          <div style={{ marginTop: 8 }}><strong>Total: €{o.parsedItems.reduce((s,it)=>s + ((it.product.price||0) * it.quantity), 0).toFixed(2)}</strong></div>
          <div style={{ marginTop: 8 }}>
            {/* Friendly status labels */}
            {o.status === 'PAID' && <span style={{ color: 'green' }}>Paid</span>}
            {o.status === 'PENDING_PAYMENT' && <span style={{ color: '#888' }}>Payment pending — not completed</span>}
            {o.status === 'PAYMENT_FAILED' && <span style={{ color: 'crimson' }}>Payment failed</span>}
            {o.status === 'PENDING' && <span style={{ color: '#b58900' }}>Payment pending — retry manually if needed</span>}

            {/* Retry button for recoverable states */}
            {['PAYMENT_FAILED', 'PENDING_PAYMENT', 'PENDING'].includes(o.status) && (
              <button onClick={() => handleRetry(o.id)} disabled={retrying[o.id]} style={{ marginLeft: 12 }}>
                {retrying[o.id] ? 'Retrying...' : 'Retry payment'}
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
