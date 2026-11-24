import { useEffect, useRef, useState } from "react";

/**
 * Text for a box whose value lives in the URL (the trip search `q`). The text is local state:
 * the URL updates a moment after each keystroke, and a box bound to it directly drops letters
 * typed faster than that. The text follows the URL only when the URL changes from elsewhere
 * (Clear filters, leaving the list). Call `edit` on each keystroke, then write the URL.
 */
export function useFollowedText(urlValue: string): [string, (next: string) => void] {
  const [text, setText] = useState(urlValue);
  const sent = useRef(urlValue);
  useEffect(() => {
    if (urlValue !== sent.current) {
      sent.current = urlValue;
      setText(urlValue);
    }
  }, [urlValue]);
  const edit = (next: string) => {
    setText(next);
    sent.current = next;
  };
  return [text, edit];
}
