import { Gem } from "lucide-react"

export function RealizationProposalNotice({ yes, saved = false }: { yes: boolean; saved?: boolean }) {
  return <div className="mt-2 rounded-md border border-cyan-200 bg-cyan-50 p-2 text-xs text-cyan-950">
    <p className="flex items-center gap-1.5 font-semibold"><Gem className="h-4 w-4 shrink-0 fill-cyan-300 text-cyan-700" />
      {yes && saved ? "1 diamant për propozimin" : "Propozim për përmirësim · 1 diamant"}
    </p>
    <p className="mt-1 leading-4">{yes
      ? saved ? "Diamanti shfaqet te Reviews dhe te Common. Redaktimi i kësaj përgjigjeje nuk jep diamant tjetër."
        : "Përshkruaj propozimin dhe përfitimin. Kur ruan Po me koment, merr automatikisht 1 diamant."
      : "Po me koment jep automatikisht 1 diamant. Javori përmbledh propozimet ditore pa i shpërblyer dy herë."}</p>
  </div>
}
