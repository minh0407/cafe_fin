import { mergeConfig } from '../../../frontend/node_modules/vite';
import base from '../../../frontend/vite.config';

// Test-owned HTML; production source and API responses are served unchanged.
// Retain a public React Root handle so the login shell can be unmounted before
// measuring the lane. There is no hidden second grid/cache during measurements.
const html = `<!doctype html><html lang="vi"><head><meta charset="UTF-8"><title>Accounting bulk evidence</title></head><body><div id="root"></div><script type="module">
  const mainSource = await (await fetch('/src/app/main.tsx')).text();
  const dependency = token => {
    const urls = [...mainSource.matchAll(/["']([^"']*\\/node_modules\\/\\.vite\\/deps\\/[^"']+)["']/g)].map(match => match[1]);
    const found = urls.find(url => url.includes(token));
    if (!found) throw new Error('Vite dependency URL unavailable: ' + token);
    return found;
  };
  const React = (await import(dependency('/react.js'))).default;
  const ReactDOM = await import(dependency('/react-dom_client.js'));
  const { QueryClient, QueryClientProvider } = await import(dependency('/@tanstack_react-query.js'));
  const { ConfigProvider } = await import(dependency('/antd.js'));
  const locale = (await import(dependency('/antd_locale_vi_VN.js'))).default;
  const { App } = await import('/src/app/App.tsx');
  await import('/src/app/styles.css');
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = (ReactDOM.createRoot ?? ReactDOM.default.createRoot)(document.getElementById('root'));
  Object.assign(window, { __bulkShellRoot: root, __bulkShellCache: cache });
  root.render(React.createElement(ConfigProvider, { locale }, React.createElement(QueryClientProvider, { client: cache }, React.createElement(App))));
</script></body></html>`;

export default mergeConfig(base, {
  plugins: [{
    name: 'accounting-bulk-isolated-harness',
    configureServer(server) {
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
