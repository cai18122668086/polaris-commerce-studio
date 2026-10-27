// A Node-only frontend for isolated verification; production hosting stays intact.
import { createServer } from 'vite';
import vinext from 'vinext';
const server = await createServer({
  configFile: false,
  cacheDir: '.cache/node_modules/.vite-credit-node',
  plugins: [vinext()],
  server: { host: '127.0.0.1', port: 4190, strictPort: true, watch: { ignored: ["**/backend/**", "**/.cache/**"] },
    proxy: { '/api': 'http://127.0.0.1:8190' } },
});
await server.listen();
server.printUrls();
