const ROWS: [string, string][] = [
  ["?", "Show or hide this help"],
  ["/", "Search"],
  ["g then m / t / r / s / v / h", "Go to Map, Trips, Review, Stats, Vehicles, History"],
  ["[ and ]", "Narrow or widen the list"],
  ["\\", "Hide or show the list"],
  ["Esc", "Close dialogs, cancel"],
];

export function ShortcutHelp({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/30">
      <div
        role="dialog"
        aria-label="Keyboard shortcuts"
        className="w-[28rem] rounded-lg bg-white p-5 shadow-xl"
      >
        <h2 className="mb-3 text-lg font-semibold">Keyboard shortcuts</h2>
        <table className="w-full text-sm">
          <tbody>
            {ROWS.map(([keys, action]) => (
              <tr key={keys}>
                <td className="py-1 pr-4 font-mono">{keys}</td>
                <td className="py-1">{action}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <button type="button" className="mt-4 rounded bg-slate-100 px-3 py-1" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}
