import { useRef, useState, type ButtonHTMLAttributes, type ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-indigo-600 text-white hover:bg-indigo-700 disabled:bg-indigo-300",
  secondary: "bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50 disabled:text-slate-400",
  ghost: "text-slate-600 hover:bg-slate-100 disabled:text-slate-300",
  danger: "bg-rose-600 text-white hover:bg-rose-700 disabled:bg-rose-300",
};

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type="button"
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed ${VARIANTS[variant]} ${className}`}
      {...props}
    />
  );
}

export function Card({ title, actions, children, className = "" }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200 ${className}`}>
      {(title || actions) && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          {title && <h2 className="text-base font-semibold text-slate-900">{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

const ALERT_STYLES = {
  error: "bg-rose-50 text-rose-800 ring-rose-200",
  warning: "bg-amber-50 text-amber-900 ring-amber-200",
  info: "bg-sky-50 text-sky-900 ring-sky-200",
  success: "bg-emerald-50 text-emerald-900 ring-emerald-200",
};

export function Alert({ kind = "info", title, children }: { kind?: keyof typeof ALERT_STYLES; title?: ReactNode; children?: ReactNode }) {
  return (
    <div role={kind === "error" ? "alert" : "status"} className={`rounded-lg px-4 py-3 text-sm ring-1 ring-inset ${ALERT_STYLES[kind]}`}>
      {title && <p className="font-semibold">{title}</p>}
      {children && <div className={title ? "mt-1" : ""}>{children}</div>}
    </div>
  );
}

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="4" />
      <path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
    </svg>
  );
}

export function Stat({ label, value, tone = "slate" }: { label: string; value: ReactNode; tone?: "slate" | "green" | "amber" | "red" | "indigo" }) {
  const tones = {
    slate: "text-slate-900",
    green: "text-emerald-600",
    amber: "text-amber-600",
    red: "text-rose-600",
    indigo: "text-indigo-600",
  };
  return (
    <div className="rounded-xl bg-slate-50 px-4 py-3 ring-1 ring-inset ring-slate-200">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${tones[tone]}`}>{value}</p>
    </div>
  );
}

export interface StepDef {
  title: string;
  subtitle: string;
}

export function Stepper({ steps, current, maxReachable, onSelect }: { steps: StepDef[]; current: number; maxReachable: number; onSelect: (i: number) => void }) {
  return (
    <nav aria-label="Progress">
      <ol className="grid grid-cols-5 gap-2">
        {steps.map((step, i) => {
          const state = i === current ? "current" : i < current ? "done" : "todo";
          const reachable = i <= maxReachable;
          return (
            <li key={step.title}>
              <button
                type="button"
                disabled={!reachable}
                onClick={() => onSelect(i)}
                aria-current={state === "current" ? "step" : undefined}
                className={`group flex w-full flex-col gap-1 border-t-4 pt-2 text-left disabled:cursor-not-allowed ${
                  state === "current" ? "border-indigo-600" : state === "done" ? "border-indigo-300" : "border-slate-200"
                }`}
              >
                <span className={`text-xs font-semibold ${state === "todo" ? "text-slate-400" : "text-indigo-600"}`}>
                  Step {i + 1}
                </span>
                <span className={`hidden text-sm font-medium sm:block ${reachable ? "text-slate-800 group-hover:text-indigo-700" : "text-slate-400"}`}>
                  {step.title}
                </span>
                <span className="hidden text-xs text-slate-500 lg:block">{step.subtitle}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export function Dropzone({
  accept,
  title,
  hint,
  busy,
  onFile,
}: {
  accept: string;
  title: string;
  hint: string;
  busy?: boolean;
  onFile: (file: File) => void;
}) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  return (
    <div
      role="button"
      tabIndex={0}
      aria-busy={busy}
      onClick={() => !busy && input.current?.click()}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && !busy && input.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const file = e.dataTransfer.files?.[0];
        if (file && !busy) onFile(file);
      }}
      className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
        over ? "border-indigo-500 bg-indigo-50" : "border-slate-300 bg-white hover:border-indigo-400 hover:bg-slate-50"
      }`}
    >
      <input
        ref={input}
        type="file"
        accept={accept}
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFile(file);
          e.target.value = "";
        }}
      />
      {busy ? (
        <Spinner className="h-8 w-8 text-indigo-600" />
      ) : (
        <svg className="h-10 w-10 text-indigo-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
          <path d="M12 16V4m0 0-4 4m4-4 4 4M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
      <p className="text-sm font-semibold text-slate-800">{busy ? "Uploading…" : title}</p>
      <p className="text-xs text-slate-500">{hint}</p>
    </div>
  );
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function rowList(rows: number[], limit = 12): string {
  const shown = rows.slice(0, limit).join(", ");
  return rows.length > limit ? `${shown} and ${rows.length - limit} more` : shown;
}
