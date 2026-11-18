import type { NextConfig } from "next";

const deploymentId =
  process.env.NEXT_DEPLOYMENT_ID ||
  process.env.GITHUB_SHA ||
  process.env.APP_BUILD_SHA;
const distDir = process.env.NEXT_DIST_DIR || ".next";

const nextConfig: NextConfig = {
  distDir,
  ...(process.env.PRIMEFLOW_STANDALONE === "1" ? { output: "standalone" as const } : {}),
  ...(deploymentId ? { deploymentId } : {}),
  typescript: {
    ignoreBuildErrors: true,
  },
  turbopack: {
    root: process.cwd(),
  },
};

export default nextConfig;
