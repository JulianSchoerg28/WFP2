import React from "react";
import { Navigate, useLocation } from "react-router-dom";
import { getToken, isTokenValid } from "../utils/auth";

export default function RequireAuth({ children }) {
  const token = getToken();
  const location = useLocation();
  if (!token || !isTokenValid(token)) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  return children;
}
