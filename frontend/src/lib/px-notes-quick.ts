/** Start URL of the iPhone "Add to Home Screen" icon (see public/px-notes.webmanifest). */
export const PX_NOTES_QUICK_URL = "/ga-ka-notes?quick=1"

/** True when the app was opened from the home screen icon rather than a browser tab. */
export function isHomeScreenApp() {
  if (typeof window === "undefined") return false
  const iosStandalone = (window.navigator as Navigator & { standalone?: boolean }).standalone === true
  return iosStandalone || window.matchMedia("(display-mode: standalone)").matches
}

/** PX Notes opened straight for writing: from the home screen icon or its link. */
export function isPxNotesQuickLaunch() {
  if (typeof window === "undefined") return false
  return isHomeScreenApp() || new URLSearchParams(window.location.search).get("quick") === "1"
}
