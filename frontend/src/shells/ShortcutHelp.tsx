const ROWS: [string, string][] = [
  ["?", "Show or hide this help"],
  ["/", "Search trips"],
  ["g then m / t / r / s / v / h", "Go to Map, Trips, Review, Stats, Vehicles, History"],
  ["[ and ]", "Narrow or widen the list"],
  ["\\", "Hide or show the list"],
  ["j / k", "Trip list: next or previous trip"],
  ["Enter or o", "Open the trip under the cursor"],
  ["e", "Edit the trip under the cursor, or the open trip"],
  ["x", "Select or deselect the trip under the cursor"],
  ["Shift+J / Shift+K", "Extend the selection down or up"],
  ["* then a / n", "Select all listed trips, or none"],
  ["f", "Fit the map to the selected trips"],
  ["t / u / p", "Tag, purpose or people for the selected trips"],
  ["1 to 7", "Set that purpose on the selected trips"],
  ["u / Shift+U", "Undo or redo in the route editor"],
  ["Esc", "Close dialogs, cancel, clear the selection"],
];

export function ShortcutHelp({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/30">
      <div
        role="dialog"
        aria-label="Keyboard shortcuts"
        className="max-h-[90vh] w-[32rem] overflow-auto rounded-lg bg-white p-5 shadow-xl"
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
