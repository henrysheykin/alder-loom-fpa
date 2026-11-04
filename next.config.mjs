/** @type {import('next').NextConfig} */
const nextConfig = {
  poweredByHeader: false,
  // files read at runtime by route handlers must be shipped with the serverless functions
  outputFileTracingIncludes: {
    "/dashboard": ["./private/dashboard.html"],
    "/api/data": ["./private/datamart.json"],
  },
  outputFileTracingExcludes: {
    "*": ["./data/**", "./pipeline/**"],
  },
  async redirects() {
    return [{ source: "/", destination: "/dashboard", permanent: false }];
  },
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "X-Frame-Options", value: "DENY" },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "same-origin" },
        { key: "X-Robots-Tag", value: "noindex, nofollow" },
      ],
    }];
  },
};
export default nextConfig;
