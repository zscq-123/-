import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = { title: '法援协同 · 智能接待工作台', description: '法律援助多智能体接待与人工审核演示平台' };
export default function RootLayout({ children }: Readonly<{children: React.ReactNode}>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
