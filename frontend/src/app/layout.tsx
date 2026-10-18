import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = { title: 'PULSO | Descubre lo que viene', description: 'Inteligencia editorial para LATAM' };
export default function RootLayout({children}:{children:React.ReactNode}) {return <html lang="es"><body>{children}</body></html>}
