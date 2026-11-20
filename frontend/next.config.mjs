/** @type {import('next').NextConfig} */
const staticExport = process.env.STATIC_EXPORT === 'true';
const nextConfig = {
  output: staticExport ? 'export' : 'standalone',
  images: { unoptimized: staticExport },
  poweredByHeader: false,
  ...(!staticExport && {
    async rewrites() {
      return [{ source: '/api/:path*', destination: `${process.env.API_URL_INTERNAL || 'http://localhost:8000'}/api/:path*` }];
    },
  }),
};
export default nextConfig;
