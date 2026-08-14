import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // This project lives inside a multi-service repo (backend/bot/vpn/frontend) rather than
  // its own git root, which Turbopack otherwise warns about when it finds a lockfile above
  // the app directory — pin the workspace root explicitly instead of relying on inference.
  turbopack: {
    root: path.join(__dirname),
  },
  // Produces a minimal, self-contained server (.next/standalone) with only the traced
  // dependencies actually needed at runtime — keeps the production Docker image small.
  output: "standalone",
};

export default nextConfig;
