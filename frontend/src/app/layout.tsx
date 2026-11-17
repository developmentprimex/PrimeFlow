import type { Metadata } from "next";
import "./globals.css";
import { ConfirmDialogProvider } from "@/components/providers/confirm-dialog-provider";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider } from "@/lib/auth";
import { THEME_SCRIPT } from "@/lib/theme";

export const metadata: Metadata = {
  title: "PrimeFlow",
  description: "Internal task & project management",
  icons: {
    icon: "/ICON@2x.png",
    shortcut: "/ICON@2x.png",
    apple: "/ICON@2x.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} /></head>
      <body className="antialiased">
        <AuthProvider>
          <ConfirmDialogProvider>
            {children}
            <Toaster />
          </ConfirmDialogProvider>
        </AuthProvider>
      </body>
    </html>
  );
}


