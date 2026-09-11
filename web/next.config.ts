import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The decision log lives beside web/, in the repository's logs/ folder. Trace from the
  // repository root and ship the log with /app, so a deployment (e.g. Vercel, root
  // directory web/) can replay it with no setup. Each pushed log commit redeploys.
  outputFileTracingRoot: path.join(__dirname, ".."),
  outputFileTracingIncludes: {
    "/app": ["../logs/decisions/*.jsonl"],
  },
};

export default nextConfig;
