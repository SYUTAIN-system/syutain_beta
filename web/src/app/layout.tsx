import type { Metadata, Viewport } from "next";
import "./globals.css";
import MobileTabBar from "@/components/MobileTabBar";
import ClientErrorBoundary from "@/components/ClientErrorBoundary";
import AuthGate from "@/components/AuthGate";

export const metadata: Metadata = {
  title: "SYUTAINβ",
  description: "自律型収益エンジン ダッシュボード",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "SYUTAINβ",
  },
};

export const viewport: Viewport = {
  themeColor: "#0a0a0f",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  interactiveWidget: "resizes-content",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ja" className="dark">
      <head>
        <link rel="icon" href="/favicon.ico" sizes="any" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <link rel="apple-touch-icon" href="/icon-192.svg" />
      </head>
      <body className="min-h-screen antialiased">
        <nav className="sticky top-0 z-50 border-b border-[var(--border-color)] bg-[var(--bg-secondary)]/80 backdrop-blur-md">
          <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4">
            <a href="/" className="text-lg font-bold tracking-wider text-white">
              SYUTAIN<span className="text-[var(--accent-purple)]">&beta;</span>
            </a>
            <div className="hidden md:flex items-center gap-4 text-sm">
              <a href="/" className="text-[var(--text-secondary)] hover:text-white transition-colors">ダッシュボード</a>
              <a href="/chat" className="text-[var(--text-secondary)] hover:text-white transition-colors">チャット</a>
              <a href="/tasks" className="text-[var(--text-secondary)] hover:text-white transition-colors">タスク</a>
              <a href="/proposals" className="text-[var(--text-secondary)] hover:text-white transition-colors">提案</a>
              <a href="/timeline" className="text-[var(--text-secondary)] hover:text-white transition-colors">タイムライン</a>
              <a href="/agent-ops" className="text-[var(--text-secondary)] hover:text-white transition-colors">Agent Ops</a>
              <a href="/brain-alpha" className="text-[var(--text-secondary)] hover:text-white transition-colors">Brain-&alpha;</a>
              <a href="/node-control" className="text-[var(--text-secondary)] hover:text-white transition-colors">ノード</a>
              <a href="/revenue" className="text-[var(--text-secondary)] hover:text-white transition-colors">収益</a>
              <a href="/models" className="text-[var(--text-secondary)] hover:text-white transition-colors">モデル</a>
              <a href="/artifacts" className="text-[var(--text-secondary)] hover:text-white transition-colors">成果物</a>
              <a href="/intel" className="text-[var(--text-secondary)] hover:text-white transition-colors">情報収集</a>
              <a href="/settings" className="text-[var(--text-secondary)] hover:text-white transition-colors">設定</a>
            </div>
          </div>
        </nav>
        <AuthGate>
          <main className="mx-auto max-w-7xl px-4 py-6 pb-24 md:pb-6">
            <ClientErrorBoundary>
              {children}
            </ClientErrorBoundary>
          </main>
          <MobileTabBar />
        </AuthGate>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              if ('serviceWorker' in navigator) {
                window.addEventListener('load', function() {
                  navigator.serviceWorker.register('/sw.js').catch(function() {});
                });
              }
            `,
          }}
        />
      </body>
    </html>
  );
}
