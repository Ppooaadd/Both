import type { Metadata, Viewport } from "next";
import { IBM_Plex_Sans_KR, JetBrains_Mono } from "next/font/google";

import { GalaxyLayer } from "@/components/galaxy/GalaxyLayer";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { Toaster } from "@/components/ui/sonner";
import { Providers } from "./providers";
import "./globals.css";

const plex = IBM_Plex_Sans_KR({
  variable: "--font-plex",
  weight: ["400", "500", "600", "700"],
  subsets: ["latin"],
  display: "swap",
  preload: false, // Korean glyph files are large; load on demand
});

const mono = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "PianoForge", template: "%s · PianoForge" },
  description: "음원을 올리면 멜로디·코드·박자를 분석해 초급·중급·고급 피아노 악보와 MIDI, 오디오를 만들어 드립니다.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#0b0a1d" },
    { media: "(prefers-color-scheme: dark)", color: "#0b0a1d" },
  ],
};

const REVEAL_BOOT =
  "(function(d){if(matchMedia('(prefers-reduced-motion: reduce)').matches)return;" +
  "d.classList.add('galaxy-js');setTimeout(function(){if(!window.__galaxyReveal)d.classList.remove('galaxy-js')},4000)})(document.documentElement)";

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko" className={`galaxy ${plex.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        {/* Hide .animate-fade-up only when the reveal script will run; if it has
            not started within 4 s (blocked JS), show everything. */}
        <script dangerouslySetInnerHTML={{ __html: REVEAL_BOOT }} />
      </head>
      <body className="min-h-dvh font-sans">
        <GalaxyLayer />
        <Providers>
          <SiteHeader />
          <main className="mx-auto w-full max-w-6xl px-4 py-8">{children}</main>
          <Toaster position="bottom-right" />
        </Providers>
      </body>
    </html>
  );
}
