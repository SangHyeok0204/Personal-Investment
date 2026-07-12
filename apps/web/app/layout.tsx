import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { Bell, ChevronDown, CircleHelp, Menu, Search } from "lucide-react";
import "./globals.css";
import { Providers } from "./providers";
import { Sidebar } from "@/components/layout/sidebar";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Personal Investment",
  description: "Personal investment platform dashboard",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={inter.variable}>
      <body>
        <Providers>
          <div className="flex min-h-screen">
            <Sidebar />
            <div className="min-w-0 flex flex-1 flex-col">
              <header className="flex h-16 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-7">
                <div className="flex items-center gap-5">
                  <Menu className="h-5 w-5 text-slate-500" />
                  <div className="h-7 w-40 rounded-lg bg-slate-100" />
                </div>
                <div className="text-sm font-medium text-slate-400">Topbar Placeholder</div>
                <div className="flex items-center gap-5 text-slate-500">
                  <Search className="h-5 w-5" />
                  <Bell className="h-5 w-5" />
                  <CircleHelp className="h-5 w-5" />
                  <div className="flex items-center gap-1.5">
                    <span className="h-8 w-8 rounded-full bg-slate-100" />
                    <ChevronDown className="h-4 w-4" />
                  </div>
                </div>
              </header>
              <main className="min-w-0 flex-1">{children}</main>
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
