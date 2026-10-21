import { Suspense } from "react"
import { MiraPage } from "@/components/mira/mira-page"

export default function MiraRoute() {
  return (
    <Suspense>
      <MiraPage />
    </Suspense>
  )
}
