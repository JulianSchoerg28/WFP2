import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import App from "./App";
import Login from "./pages/Login";
import Products from "./pages/Products";
import Cart from "./pages/Cart";
import Admin from "./pages/Admin";
import MyOrders from "./pages/MyOrders";
import RequireAuth from "./components/RequireAuth";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />}> 
          <Route index element={<Navigate to="/products" replace />} />
          <Route path="login" element={<Login />} />
          <Route path="products" element={<RequireAuth><Products /></RequireAuth>} />
          <Route path="cart" element={<RequireAuth><Cart /></RequireAuth>} />
          <Route path="admin" element={<RequireAuth><Admin /></RequireAuth>} />
          <Route path="myorders" element={<RequireAuth><MyOrders /></RequireAuth>} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
