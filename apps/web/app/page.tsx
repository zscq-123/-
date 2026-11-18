import type { Metadata } from 'next';
import Kiosk from './kiosk';

export const metadata: Metadata = {
  title: '法律援助中心 · 自助接待',
  description: '法律援助中心现场触屏接待原型',
};

export default function Home() {
  return <Kiosk />;
}
