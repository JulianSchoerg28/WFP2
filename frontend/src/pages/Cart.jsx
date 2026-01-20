import React, { useEffect, useState, useRef } from "react";
import { createOrder, createPayment, fetchOrder } from "../api";
import { fetchCartServer, removeFromCartServer, clearCartServer } from "../api";

export default function Cart() {
  const [cart, setCart] = useState([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState(null);
  const [lastOrder, setLastOrder] = useState(null);

  useEffect(() => {
    async function load() {
      const token = localStorage.getItem("token");
      let local = JSON.parse(localStorage.getItem("cart") || "[]");
      if (token) {
        try {
          const server = await fetchCartServer(token);
          if (server && Array.isArray(server.items)) {
            // map server items to local shape
            const serverItems = server.items.map((it) => ({ product_id: it.product_id, quantity: it.quantity, name: it.name, price: it.price }));
            // merge local items that are not present on server
            const serverIds = new Set(serverItems.map((i) => i.product_id));
            const merged = [...serverItems];
            for (const li of local) {
              if (!serverIds.has(li.product_id)) merged.push(li);
            }
            setCart(merged);
            return;
          }
        } catch (err) {
          console.error("server cart fetch failed", err);
          setMessage("Could not load server cart; showing local cart.");
        }
      }
      setCart(local);
    }
    load();
  }, []);

  function removeItem(index) {
    const token = localStorage.getItem("token");
    if (token) {
      const it = cart[index];
      // request server to decrement/remove one unit by default
      removeFromCartServer(it.product_id, token, 1).catch((err) => console.error(err));
    }
    const copy = [...cart];
    copy.splice(index, 1);
    setCart(copy);
    localStorage.setItem("cart", JSON.stringify(copy));
  }

  async function placeOrder() {
    if (cart.length === 0) return setMessage("Cart is empty");
    setLoading(true);
    setMessage(null);
    try {
      // order-service now uses the server-side cart; just request order creation
      const order = await createOrder();
      // order created; payment will be processed asynchronously by the consumer
      setLastOrder({ id: order.id, status: order.status });
      setMessage(`Bestellung erstellt (#${order.id}). Zahlung zur Bearbeitung eingereiht — Status unter 'Meine Bestellungen'.`);
      // clear UI/local cart because order items are stored server-side
      setCart([]);
      localStorage.removeItem("cart");
      // attempt best-effort server-side cart clear for logged-in users
      const token = localStorage.getItem("token");
      if (token) {
        try {
          await clearCartServer(token);
        } catch (err) {
          console.error("Failed to clear server cart after order creation", err);
        }
      }
      // start polling this order's status and update UI when it resolves
      try {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = setInterval(async () => {
          try {
            const statusResp = await fetchOrder(order.id);
            if (!statusResp || !statusResp.status) return;
            if (statusResp.status === 'PAID') {
              setMessage(`Payment successful for order ${order.id}`);
              setLastOrder(null);
              clearInterval(pollRef.current);
              pollRef.current = null;
            } else if (statusResp.status === 'PAYMENT_FAILED') {
              setMessage(`Payment failed for order ${order.id}`);
              setLastOrder({ id: order.id, status: 'PAYMENT_FAILED' });
              clearInterval(pollRef.current);
              pollRef.current = null;
            }
          } catch (err) {
            // ignore transient polling errors
          }
        }, 3000);
      } catch (err) {
        console.error('Could not start order status poll', err);
      }
    } catch (err) {
      setMessage(String(err));
    } finally {
      setLoading(false);
    }
  }

  // cleanup poll on unmount
  const pollRef = useRef(null);
  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  async function handleRetryFromCart() {
    if (!lastOrder || !lastOrder.id) return;
    setLoading(true);
    try {
      setMessage(`Retrying payment for order #${lastOrder.id}…`);
      const pay = await createPayment(lastOrder.id, 'mock');
      if (pay.result === 'SUCCESS') {
        setMessage(`Payment successful for order ${lastOrder.id}`);
        setLastOrder(null);
      } else if (pay.result === 'PENDING') {
        setMessage('Payment still pending. It was not completed; you can retry manually.');
      } else {
        setMessage('Payment retry failed. Try again later.');
      }
    } catch (err) {
      console.error('Retry failed', err);
      setMessage('Retry failed: ' + String(err));
    } finally {
      setLoading(false);
    }
  }

  const total = cart.reduce((s, it) => s + (it.price || 0) * (it.quantity || 1), 0).toFixed(2);

  return (
    <div>
      <h2>Cart</h2>
      {message && <div style={{ marginBottom: 8 }}>{message}</div>}
      <ul>
        {cart.map((it, idx) => (
          <li key={idx}>
            {it.name} — qty {it.quantity} — ${it.price}
            <button onClick={() => removeItem(idx)} style={{ marginLeft: 8 }}>Remove</button>
          </li>
        ))}
      </ul>
      <div style={{ marginTop: 12 }}>
        <strong>Total: ${total}</strong>
      </div>
      <div style={{ marginTop: 12 }}>
        <button onClick={placeOrder} disabled={loading || cart.length === 0}>{loading ? "Processing..." : "Place Order"}</button>
        {lastOrder && (
          <button onClick={handleRetryFromCart} disabled={loading} style={{ marginLeft: 12 }}>
            Retry payment for order #{lastOrder.id}
          </button>
        )}
      </div>
    </div>
  );
}
