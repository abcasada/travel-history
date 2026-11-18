/** Small form building blocks shared by every editor (frontend-patterns.md, "Forms"). */
import type { ReactNode } from "react";

export const inputClass = "w-full rounded border px-2 py-1 text-sm disabled:bg-slate-50";

export function Field({
  label,
  htmlFor,
  error,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  error?: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="mb-3">
      <label className="mb-0.5 block text-sm font-medium text-slate-700" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {hint && !error && <p className="mt-0.5 text-xs text-slate-500">{hint}</p>}
      {error && (
        <p className="mt-0.5 text-xs text-red-700" id={`${htmlFor}-error`}>
          {error}
        </p>
      )}
    </div>
  );
}

type ButtonProps = {
  children: ReactNode;
  onClick?: () => void;
  type?: "button" | "submit";
  disabled?: boolean;
  variant?: "primary" | "secondary" | "danger" | "link";
  title?: string;
  "aria-label"?: string;
};

const VARIANTS = {
  primary: "rounded-md bg-blue-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-800",
  secondary: "rounded-md border px-3 py-1.5 text-sm hover:bg-slate-100",
  danger: "rounded-md border border-red-300 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50",
  link: "text-sm text-blue-700 hover:underline",
};

export function Button({ variant = "secondary", type = "button", ...props }: ButtonProps) {
  return (
    <button
      type={type}
      className={`${VARIANTS[variant]} disabled:opacity-50`}
      onClick={props.onClick}
      disabled={props.disabled}
      title={props.title}
      aria-label={props["aria-label"]}
    >
      {props.children}
    </button>
  );
}

export function Section({
  title,
  actions,
  children,
}: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="mb-5" aria-label={title}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="font-medium">{title}</h3>
        {actions}
      </div>
      {children}
    </section>
  );
}
