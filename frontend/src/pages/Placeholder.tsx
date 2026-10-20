export function Placeholder({ title, phase }: { title: string; phase: string }) {
  return (
    <div className="p-4">
      <h2 className="mb-1 text-lg font-semibold">{title}</h2>
      <p className="text-sm text-slate-600">Arrives in {phase}.</p>
    </div>
  );
}
