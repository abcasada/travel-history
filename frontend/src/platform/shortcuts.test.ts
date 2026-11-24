import { bindShortcuts } from "./shortcuts";

function press(key: string, init: KeyboardEventInit = {}, target: EventTarget = window) {
  target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, ...init }));
}

test("single keys and two-key sequences fire their handlers", () => {
  const help = vi.fn();
  const goMap = vi.fn();
  const unbind = bindShortcuts({ "?": help, "g m": goMap });
  press("?");
  press("g");
  press("m");
  expect(help).toHaveBeenCalledTimes(1);
  expect(goMap).toHaveBeenCalledTimes(1);
  unbind();
  press("?");
  expect(help).toHaveBeenCalledTimes(1);
});

test("typing in a field is not a shortcut, except Escape", () => {
  const slash = vi.fn();
  const onEscape = vi.fn();
  const unbind = bindShortcuts({ "/": slash, Escape: onEscape });
  const input = document.createElement("input");
  document.body.append(input);
  press("/", {}, input);
  press("Escape", {}, input);
  expect(slash).not.toHaveBeenCalled();
  expect(onEscape).toHaveBeenCalledTimes(1);
  input.remove();
  unbind();
});

test("modifier combinations are left to the browser", () => {
  const t = vi.fn();
  const unbind = bindShortcuts({ t });
  press("t", { ctrlKey: true });
  press("t", { metaKey: true });
  press("t", { altKey: true });
  expect(t).not.toHaveBeenCalled();
  unbind();
});

test("Enter on a focused link or button activates it instead of the shortcut", () => {
  const open = vi.fn();
  const unbind = bindShortcuts({ Enter: open });
  const button = document.createElement("button");
  document.body.append(button);
  press("Enter", {}, button);
  expect(open).not.toHaveBeenCalled();
  press("Enter");
  expect(open).toHaveBeenCalledTimes(1);
  button.remove();
  unbind();
});

test("sequences that start with a symbol work (* then a)", () => {
  const all = vi.fn();
  const unbind = bindShortcuts({ "* a": all });
  press("*", { shiftKey: true });
  press("a");
  expect(all).toHaveBeenCalledTimes(1);
  unbind();
});

test("a focused checkbox is not a text field: list keys keep working after ticking one", () => {
  const next = vi.fn();
  const unbind = bindShortcuts({ j: next });
  const box = document.createElement("input");
  box.type = "checkbox";
  document.body.append(box);
  press("j", {}, box);
  expect(next).toHaveBeenCalledTimes(1);
  box.remove();
  unbind();
});
