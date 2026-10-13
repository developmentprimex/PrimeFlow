import type { Metadata } from "next"

// Lets PX Notes be added to the iPhone home screen as its own app:
// Safari > Share > "Add to Home Screen" while this page is open.
export const metadata: Metadata = {
  title: "PX Notes",
  manifest: "/px-notes.webmanifest",
  appleWebApp: {
    capable: true,
    title: "PX Notes",
    statusBarStyle: "default",
  },
  icons: {
    icon: "/ICON@2x.png",
    shortcut: "/ICON@2x.png",
    apple: "/px-notes-icon-180.png",
  },
  other: {
    "apple-mobile-web-app-capable": "yes",
  },
}

export default function GaKaNotesLayout({ children }: { children: React.ReactNode }) {
  return children
}
