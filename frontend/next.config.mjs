/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  poweredByHeader: false,
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${process.env.API_URL_INTERNAL || 'http://localhost:8000'}/api/:path*` }];
  },
};
export default nextConfig;
