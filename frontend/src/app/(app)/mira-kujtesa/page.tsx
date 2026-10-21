import { redirect } from "next/navigation"

// Kujtesa is now a tab of the Mira view; old links keep working.
export default function MiraKujtesaPage() {
  redirect("/mira?tab=kujtesa")
}
