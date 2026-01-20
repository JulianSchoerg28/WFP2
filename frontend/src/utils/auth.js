export function getToken() {
  return localStorage.getItem("token");
}

export function parseJwt(token) {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const payload = parts[1];
    const decoded = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
    return JSON.parse(decodeURIComponent(escape(decoded)));
  } catch (err) {
    return null;
  }
}

export function isTokenValid(token) {
  if (!token) return false;
  const claims = parseJwt(token);
  if (!claims || !claims.exp) return false;
  const exp = claims.exp * 1000; // exp is seconds
  return Date.now() < exp;
}

export function clearAuth() {
  localStorage.removeItem("token");
}
