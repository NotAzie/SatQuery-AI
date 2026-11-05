/** Finish unmatched API requests before Vite's HTML fallback. Install last. */
export function apiNotFoundPlugin() {
  const install = (server) => {
    server.middlewares.use('/api', (req, res, next) => {
      // SatQuery's Platform API is proxied by the host Vite configuration.
      // Connect strips the mounted `/api` prefix from req.url here.
      if (req.url === '/v1' || req.url?.startsWith('/v1/')) {
        next();
        return;
      }
      res.writeHead(404, {
        'Content-Type': 'application/json',
        'Cache-Control': 'no-store',
      });
      res.end(JSON.stringify({ error: 'Unknown API route' }));
    });
  };
  return {
    name: 'api-not-found',
    configureServer: install,
    configurePreviewServer: install,
  };
}
