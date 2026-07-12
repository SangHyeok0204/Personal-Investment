import type { Metadata } from "next";
import { Inter } from "next/font/google";
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
            <main className="min-w-0 flex-1">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
