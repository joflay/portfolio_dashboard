import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Vol_Factor Dashboard",
  description: "Strategy-focused Webull portfolio dashboard"
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
