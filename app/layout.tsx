import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PulseCode",
  description: "A local-first software evolution time machine"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

