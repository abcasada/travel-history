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
