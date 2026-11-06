import { mergeConfig, type ViteDevServer } from '../../../frontend/node_modules/vite';
import base from '../../../frontend/vite.config';
import { HARNESS_PORT } from './harness-origin';

// Test-owned HTML; production source and API responses are served unchanged.
// Retain a public React Root handle so the login shell can be unmounted before
// measuring the lane. There is no hidden second grid/cache during measurements.
const html = `<!doctype html><html lang="vi"><head><meta charset="UTF-8"><title>Accounting bulk evidence</title></head><body><div id="root"></div><script type="module">
  import React from 'react';
  import { createRoot } from 'react-dom/client';
  import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
  import { ConfigProvider } from 'antd';
  import locale from 'antd/locale/vi_VN';
  import { App } from '/src/app/App.tsx';
  import { AccountingPage } from '/src/features/accounting/AccountingPage.tsx';
  import { useSession } from '/src/shared/session.ts';
  import '/src/app/styles.css';
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(document.getElementById('root'));
  Object.assign(window, { __bulkShellRoot: root, __bulkShellCache: cache });
  root.render(React.createElement(ConfigProvider, { locale }, React.createElement(QueryClientProvider, { client: cache }, React.createElement(App))));
  window.__bulkGetAccessToken = () => useSession.getState().token;
  window.__bulkMountAccounting = bookId => {
    root.unmount(); cache.clear();
    history.replaceState(null, '', location.pathname + '#/accounting?book=' + encodeURIComponent(bookId));
    const host = document.getElementById('root'); host.id = 'bulk-lane-root';
    const laneCache = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });
    window.__bulkLaneCache = laneCache;
    const laneRoot = createRoot(host);
    laneRoot.render(React.createElement(ConfigProvider, { locale }, React.createElement(QueryClientProvider, { client: laneCache }, React.createElement(AccountingPage))));
  };
</script></body></html>`;

export default mergeConfig(base, {
  server: { host: '127.0.0.1', port: HARNESS_PORT, strictPort: true },
  plugins: [{
    name: 'accounting-bulk-isolated-harness',
    configureServer(server: ViteDevServer) {
      server.middlewares.use('/__accounting_bulk_harness', async (_request, response, next) => {
        try {
          const transformed = await server.transformIndexHtml('/__accounting_bulk_harness', html);
          response.statusCode = 200;
          response.setHeader('Content-Type', 'text/html; charset=utf-8');
          response.setHeader('Cache-Control', 'no-store');
          response.end(transformed);
        } catch (error) { next(error); }
      });
    },
  }],
});
