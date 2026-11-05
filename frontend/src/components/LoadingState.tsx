export function LoadingState() {
  return (
    <div className="min-h-screen bg-canvas p-4 sm:p-8" aria-live="polite" aria-busy="true">
      <span className="sr-only">Učitavanje podataka o kvalitetu zraka…</span>
      <div className="mx-auto max-w-[1500px] space-y-5 animate-pulse">
        <div className="h-20 rounded-3xl bg-white" />
        <div className="grid gap-5 lg:grid-cols-[1.2fr_.8fr]">
          <div className="h-80 rounded-3xl bg-[#214b3a]" />
          <div className="h-80 rounded-3xl bg-white" />
        </div>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {[0, 1, 2, 3].map((item) => <div key={item} className="h-36 rounded-3xl bg-white" />)}
        </div>
      </div>
    </div>
  )
}

