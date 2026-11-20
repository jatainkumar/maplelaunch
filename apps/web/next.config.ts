import type { NextConfig } from "next";

// MapleLaunch's web app is a static export (served by Render's free static hosting, no server, never sleeps).
// All data comes from the FastAPI backend at NEXT_PUBLIC_API_URL.
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  devIndicators: false,
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
