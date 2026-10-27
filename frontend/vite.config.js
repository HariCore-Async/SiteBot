import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const root = fileURLToPath(new URL(".", import.meta.url));

// In dev, serve the website widget at /widget/<key> like the backend does in production.
const widgetRoute = {
  name: "widget-route",
  configureServer(server) {
    server.middlewares.use((req, _res, next) => {
      if (req.url?.startsWith("/widget/")) req.url = "/widget.html";
      next();
    });
  },
};

export default defineConfig({
  plugins: [react(), widgetRoute],
  server: { proxy: { "/api": "http://localhost:8000" } },
  build: {
    rollupOptions: {
      input: { main: resolve(root, "index.html"), widget: resolve(root, "widget.html") },
    },
  },
});
