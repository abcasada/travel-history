import { useEffect, useRef, useState } from "react";

/** How the trip search `q` reads back from the URL: whitespace-only text is not written (filter.ts). */
export function qEcho(text: string): string {
  return text.trim() ? text : "";
}

/**
 * Text for a box whose value lives in the URL (the trip search `q`). The text is local state:
 * the URL updates a moment after each keystroke, and a box bound to it directly drops letters
 * typed faster than that. Call `edit` on each keystroke, then write the URL.
 *
 * The URL can lag several keystrokes behind, so a value it reports may be an older one this box
 * wrote itself. Those echoes are matched against the queue of values written and not yet seen
 * back, and ignored: following them would put back an old prefix and drop the letters typed
 * since. Only a value the box never wrote (Clear filters, leaving the list) replaces the text.
 * `echo` maps typed text to the form the URL reads it back in.
 */
export function useFollowedText(
  urlValue: string,
  echo: (text: string) => string = qEcho,
): [string, (next: string) => void] {
  const [text, setText] = useState(urlValue);
  const pending = useRef<string[]>([]);
  useEffect(() => {
    const at = pending.current.indexOf(urlValue);
    if (at >= 0) {
      // Our own write caught up: it and every older write are done.
      pending.current = pending.current.slice(at + 1);
    } else {
      pending.current = [];
      setText(urlValue);
    }
  }, [urlValue]);
  const edit = (next: string) => {
    setText(next);
    pending.current.push(echo(next));
  };
  return [text, edit];
}
