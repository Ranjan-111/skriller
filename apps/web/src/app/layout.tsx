import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Skriller · Research workspace",
  description: "Prompt-first lead discovery and evidence-backed research.",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
