/* Runtime API routing. Same-origin Render stays relative; Cloudflare Pages uses the Render API automatically. */
(() => {
  const host = String(location.hostname || '').toLowerCase();
  const sameOrigin = host === 'localhost' || host === '127.0.0.1' || host.endsWith('.onrender.com');
  window.__MF_API_ORIGIN__ = sameOrigin ? '' : 'https://modmendryx-api.onrender.com';
})();
