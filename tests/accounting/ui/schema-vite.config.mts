import { mergeConfig, type ViteDevServer } from '../../../frontend/node_modules/vite';
import base from '../../../frontend/vite.config';
import { HARNESS_PORT } from './harness-origin';

// One static module graph; only session/bootstrap and mount controls are test-owned.
const html = `<!doctype html><html lang="vi"><head><meta charset="UTF-8"><title>Schema retry regression</title></head><body><div id="root"></div><script type="module">
import React from 'react';
import { createRoot } from 'react-dom/client';
import { ConfigProvider } from 'antd';
import locale from 'antd/locale/vi_VN';
import { SchemaEditor } from '/src/features/accounting/SchemaEditor.tsx';
import { useSession } from '/src/shared/session.ts';
const root = createRoot(document.getElementById('root'));
window.__schemaSession = useSession;
function Harness({ initialBook, advanceOnSaved }) {
  const [open, setOpen] = React.useState(true);
  const [book, setBook] = React.useState(initialBook);
  const [saved, setSaved] = React.useState(0);
  const [closed, setClosed] = React.useState(0);
  window.__schemaOpen = next => { setBook(next); setOpen(true); };
  window.__schemaClose = () => setOpen(false);
  window.__schemaSetBook = setBook;
  return React.createElement(React.Fragment, null,
    React.createElement('output', { 'aria-label': 'Saved callbacks' }, saved),
    React.createElement('output', { 'aria-label': 'Closed callbacks' }, closed),
    React.createElement(SchemaEditor, { open, book,
      onSaved: value => { window.__schemaSaved = value; setSaved(old => old + 1); if (advanceOnSaved) useSession.getState().logout(); },
      onClose: () => { setClosed(old => old + 1); setOpen(false); }
    }));
}
window.__schemaMount = options => {
  useSession.getState().setBoot(options.boot);
  useSession.getState().login(options.token, options.user);
  root.render(React.createElement(ConfigProvider, { locale }, React.createElement(Harness, { initialBook: options.book, advanceOnSaved: options.advanceOnSaved })));
};
</script></body></html>`;

export default mergeConfig(base, {
  server: { host: '127.0.0.1', port: HARNESS_PORT, strictPort: true },
  plugins: [{ name: 'schema-regression-static-entry', configureServer(server: ViteDevServer) {
    server.middlewares.use('/__accounting_schema_harness', async (_request, response, next) => {
      try { response.setHeader('Content-Type', 'text/html; charset=utf-8'); response.setHeader('Cache-Control', 'no-store'); response.end(await server.transformIndexHtml('/__accounting_schema_harness', html)); }
      catch (error) { next(error); }
    });
  } }],
});
