import React, { useEffect, useState } from "react";
import { fetchProducts, addToCartServer } from "../api";

export default function Products() {
  const [products, setProducts] = useState([]);
  const [q, setQ] = useState("");
  const token = localStorage.getItem("token");
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const r = await fetchProducts({ q, token });
      setProducts(r.data || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  return (
    <div>
      <h2>Products</h2>
      <div style={{ marginBottom: 8 }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search" />
        <button onClick={() => { setPage(1); load(); }}>Search</button>
      </div>
      {loading && <div>Loading...</div>}
      <ul>
        {products.map((p) => (
          <li key={p.id} style={{ marginBottom: 6 }}>
            <strong>{p.name}</strong> — {p.description || ""} — ${p.price}
            <div>
              <button onClick={async () => {
                const token = localStorage.getItem("token");
                if (token) {
                  try {
                    await addToCartServer(p.id, 1, token);
                    alert("Added to cart (server)");
                  } catch (err) {
                    console.error(err);
                    alert("Failed to add to server cart, saved locally");
                    const existing = JSON.parse(localStorage.getItem("cart") || "[]");
                    existing.push({ product_id: p.id, quantity: 1, name: p.name, price: p.price });
                    localStorage.setItem("cart", JSON.stringify(existing));
                  }
                } else {
                  const existing = JSON.parse(localStorage.getItem("cart") || "[]");
                  existing.push({ product_id: p.id, quantity: 1, name: p.name, price: p.price });
                  localStorage.setItem("cart", JSON.stringify(existing));
                  alert("Added to cart (local)");
                }
              }}>Add to cart</button>
            </div>
          </li>
        ))}
      </ul>
      {/* Pagination removed for FH demo — all items are shown */}
    </div>
  );
}
