import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  // Em `next dev`, libera o tunel ngrok (sem isso o Next bloqueia o JS e a pagina nao hidrata).
  allowedDevOrigins: ["*.ngrok-free.app", "*.ngrok-free.dev", "*.ngrok.app"],
  // Proxy da API: com NEXT_PUBLIC_API_URL=/api o navegador fala so com o painel (um link so,
  // ex.: tunel ngrok) e o servidor do Next repassa para API_INTERNA_URL.
  async rewrites() {
    const destino = process.env.API_INTERNA_URL ?? "http://localhost:8000";
    return [{ source: "/api/:path*", destination: `${destino}/:path*` }];
  },
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
