import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "GAWorld — Generative Urban Social Simulation",
  description: "A replayable, intervenable multi-agent simulator for urban social behavior experiments.",
  icons: { icon: "/favicon.svg", shortcut: "/favicon.svg" },
  openGraph: { title: "GAWorld — Generative Urban Social Simulation", description: "Turn a city into a replayable, intervenable, comparable social experiment.", type: "website" },
  twitter: { card: "summary_large_image", title: "GAWorld — Generative Urban Social Simulation", description: "Turn a city into a replayable, intervenable, comparable social experiment." },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body className={`${geistSans.variable} ${geistMono.variable}`}>{children}</body></html>;
}
