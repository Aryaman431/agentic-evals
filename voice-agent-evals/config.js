/* API base URL configuration.
   Override order: ?api= query param > localStorage('evalApiBase') > default.
   For production, change the default below or set localStorage/Query param. */
window.EVAL_CONFIG = window.EVAL_CONFIG || {};
(function () {
  var q = new URLSearchParams(location.search).get('api');
  var ls = null; try { ls = localStorage.getItem('evalApiBase'); } catch (e) {}
  window.EVAL_CONFIG.apiBase = (q || ls || 'http://localhost:8001').replace(/\/+$/, '');
})();
