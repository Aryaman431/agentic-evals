/* API base URL configuration for the Production Trace -> Release Decision console.
   Override order: ?api= query param > localStorage('evalApiBase') > environment default.

   - Served by the FastAPI backend itself (local or Render): same origin.
   - Local static preview: http://localhost:8000 (uvicorn app:app).
   - Served statically (GitHub Pages / Vercel): the deployed Render backend. */
window.EVAL_CONFIG = window.EVAL_CONFIG || {};
(function () {
  var PROD_API_BASE = 'https://production-trace-release-decision.onrender.com';
  var q = new URLSearchParams(location.search).get('api');
  var ls = null; try { ls = localStorage.getItem('evalApiBase'); } catch (e) {}
  var host = location.hostname;
  var isLocal = host === 'localhost' || host === '127.0.0.1';
  var isRender = /\.onrender\.com$/i.test(host);
  var fallback = isLocal
    ? 'http://localhost:8000'
    : (isRender ? location.origin : PROD_API_BASE);
  window.EVAL_CONFIG.apiBase = (q || ls || fallback).replace(/\/+$/, '');
})();
