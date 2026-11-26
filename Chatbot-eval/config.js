/* API base URL configuration.
   Override order: ?api= query param > localStorage('evalApiBase') > default.
   PROD_API_BASE points at the dedicated chatbot backend (Chatbot-eval/server.py),
   which implements /chat/evaluate in addition to the shared scenario routes.
   The voice backend does NOT implement /chat/evaluate, so do not point this at it. */
window.EVAL_CONFIG = window.EVAL_CONFIG || {};
(function () {
  var PROD_API_BASE = 'https://agentic-evals-chatbot-api.onrender.com';
  var q = new URLSearchParams(location.search).get('api');
  var ls = null; try { ls = localStorage.getItem('evalApiBase'); } catch (e) {}
  // Detect if served publicly over HTTPS (not localhost)
  var isPublic = location.protocol === 'https:' && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1';
  window.EVAL_CONFIG.apiBase = (q || ls || (isPublic ? PROD_API_BASE : 'http://127.0.0.1:8001')).replace(/\/+$/, '');
})();