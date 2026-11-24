/**
 * File access adapter (PLAN.md §19.2). The PWA uses a file picker; a desktop wrapper can add
 * native dialogs and folder watching (auto-import of new Timeline exports) behind this API.
 */
export const canWatchFolders = false;

export function pickFiles(options: { accept?: string; multiple?: boolean } = {}): Promise<File[]> {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    if (options.accept) input.accept = options.accept;
    input.multiple = options.multiple ?? false;
    input.addEventListener("change", () => resolve(Array.from(input.files ?? [])), { once: true });
    input.addEventListener("cancel", () => resolve([]), { once: true });
    input.click();
  });
}

/** Save text the app made (a report) as a file. The PWA downloads it through a temporary link;
 * a wrapper can show a native save dialog behind the same call. */
export function saveFile(name: string, content: string, type = "text/plain"): void {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  // Revoke after the click has been handled, or some browsers cancel the download.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
