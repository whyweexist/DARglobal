import './globals.css';
import type { Metadata } from 'next';
export const metadata: Metadata = {
  title: 'ESTATE / Intelligence — Source-grounded real estate research',
  description: 'A research cockpit for verified DarGlobal and authorized Wasalt property intelligence.',
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
