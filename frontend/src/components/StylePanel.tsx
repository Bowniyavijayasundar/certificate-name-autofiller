import type { ReactNode } from "react";
import { clampBox } from "../defaults";
import type { Align, FontInfo, TextStyle, VAlign } from "../types";
import { FontPicker } from "./FontPicker";

interface Props {
  sessionId: string;
  style: TextStyle;
  fonts: FontInfo[];
  imageWidth: number;
  imageHeight: number;
  onChange: (style: TextStyle) => void;
  onFontUploaded: (font: FontInfo) => void;
  onError: (err: unknown) => void;
}

declare global {
  interface Window {
    EyeDropper?: new () => { open: () => Promise<{ sRGBHex: string }> };
  }
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-xs font-medium text-slate-600">{label}</span>
      {children}
    </label>
  );
}

const inputCls = "w-full rounded-lg px-2.5 py-1.5 text-sm tabular-nums ring-1 ring-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-500";

function NumberInput({ value, min, max, onChange }: { value: number; min: number; max: number; onChange: (v: number) => void }) {
  return (
    <input
      type="number"
      className={inputCls}
      value={Math.round(value)}
      min={min}
      max={max}
      onChange={(e) => {
        const v = Number(e.target.value);
        if (Number.isFinite(v)) onChange(Math.min(max, Math.max(min, v)));
      }}
    />
  );
}

function Segmented<T extends string>({ value, options, onChange }: { value: T; options: { value: T; label: ReactNode; title: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex w-full rounded-lg bg-slate-100 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          title={o.title}
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={`flex flex-1 items-center justify-center rounded-md px-2 py-1.5 text-xs font-medium ${value === o.value ? "bg-white text-indigo-700 shadow-sm" : "text-slate-600 hover:text-slate-900"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

const alignIcon = (lines: string[]) => (
  <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden>
    {lines.map((d) => <path key={d} d={d} />)}
  </svg>
);

export function StylePanel({ sessionId, style, fonts, imageWidth, imageHeight, onChange, onFontUploaded, onError }: Props) {
  const set = (patch: Partial<TextStyle>) => onChange({ ...style, ...patch });
  const setBox = (patch: Partial<TextStyle["box"]>) => set({ box: clampBox({ ...style.box, ...patch }, imageWidth, imageHeight) });
  const maxFont = Math.max(200, Math.round(imageHeight / 3));

  async function pickColour() {
    try {
      const result = await new window.EyeDropper!().open();
      set({ color: result.sRGBHex.length === 7 ? result.sRGBHex : style.color });
    } catch {
      /* user cancelled */
    }
  }

  return (
    <div className="space-y-4">
      <Field label="Font">
        <FontPicker sessionId={sessionId} fonts={fonts} value={style.font_id} onChange={(font_id) => set({ font_id })} onUploaded={onFontUploaded} onError={onError} />
      </Field>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Font size (px)">
          <NumberInput value={style.font_size} min={4} max={maxFont} onChange={(v) => set({ font_size: v, min_font_size: Math.min(style.min_font_size, v) })} />
        </Field>
        <Field label="Smallest auto-fit size">
          <NumberInput value={style.min_font_size} min={4} max={style.font_size} onChange={(v) => set({ min_font_size: v })} />
        </Field>
      </div>
      <input
        type="range"
        aria-label="Font size"
        min={8}
        max={maxFont}
        value={style.font_size}
        onChange={(e) => {
          const v = Number(e.target.value);
          set({ font_size: v, min_font_size: Math.min(style.min_font_size, v) });
        }}
        className="w-full accent-indigo-600"
      />

      <Field label="Text colour">
        <div className="flex items-center gap-2">
          <input type="color" value={style.color} onChange={(e) => set({ color: e.target.value })} className="h-9 w-12 cursor-pointer rounded border-0 bg-transparent p-0" />
          <input
            className={`${inputCls} font-mono uppercase`}
            value={style.color}
            maxLength={7}
            onChange={(e) => {
              const v = e.target.value.startsWith("#") ? e.target.value : `#${e.target.value}`;
              if (/^#[0-9a-f]{6}$/i.test(v)) set({ color: v.toLowerCase() });
            }}
          />
          {window.EyeDropper && (
            <button type="button" onClick={pickColour} title="Pick a colour from the certificate" className="rounded-lg p-2 text-slate-600 ring-1 ring-slate-300 hover:bg-slate-50">
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d="m2 22 1-1h3l9-9M3 21v-3l9-9m3-3 3-3 3 3-3 3m-6 0 6 6-2 2-6-6z" />
              </svg>
            </button>
          )}
        </div>
      </Field>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Horizontal">
          <Segmented<Align>
            value={style.align}
            onChange={(align) => set({ align })}
            options={[
              { value: "left", title: "Align left", label: alignIcon(["M2 4h12", "M2 8h8", "M2 12h10"]) },
              { value: "center", title: "Align centre", label: alignIcon(["M2 4h12", "M4 8h8", "M3 12h10"]) },
              { value: "right", title: "Align right", label: alignIcon(["M2 4h12", "M6 8h8", "M4 12h10"]) },
            ]}
          />
        </Field>
        <Field label="Vertical">
          <Segmented<VAlign>
            value={style.vertical_align}
            onChange={(vertical_align) => set({ vertical_align })}
            options={[
              { value: "top", title: "Top of box", label: "Top" },
              { value: "middle", title: "Middle of box", label: "Mid" },
              { value: "bottom", title: "Bottom of box", label: "Btm" },
            ]}
          />
        </Field>
      </div>

      <div className="flex items-center justify-between gap-3">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" className="h-4 w-4 rounded accent-indigo-600" checked={style.allow_wrap} onChange={(e) => set({ allow_wrap: e.target.checked, max_lines: Math.max(2, style.max_lines) })} />
          Wrap long names
        </label>
        <select
          disabled={!style.allow_wrap}
          aria-label="Maximum lines"
          className="rounded-lg py-1 pl-2 pr-7 text-sm ring-1 ring-slate-300 disabled:opacity-50"
          value={style.max_lines}
          onChange={(e) => set({ max_lines: Number(e.target.value) })}
        >
          {[2, 3, 4].map((n) => (
            <option key={n} value={n}>up to {n} lines</option>
          ))}
        </select>
      </div>

      <fieldset className="rounded-xl bg-slate-50 p-3 ring-1 ring-inset ring-slate-200">
        <legend className="px-1 text-xs font-semibold text-slate-600">Text box position (template pixels)</legend>
        <div className="grid grid-cols-2 gap-2">
          <Field label="X"><NumberInput value={style.box.x} min={0} max={imageWidth - 1} onChange={(x) => setBox({ x })} /></Field>
          <Field label="Y"><NumberInput value={style.box.y} min={0} max={imageHeight - 1} onChange={(y) => setBox({ y })} /></Field>
          <Field label="Width"><NumberInput value={style.box.width} min={12} max={imageWidth} onChange={(width) => setBox({ width })} /></Field>
          <Field label="Height"><NumberInput value={style.box.height} min={12} max={imageHeight} onChange={(height) => setBox({ height })} /></Field>
        </div>
        <div className="mt-2 flex gap-2">
          <button type="button" className="flex-1 rounded-md bg-white px-2 py-1 text-xs font-medium text-slate-700 ring-1 ring-slate-300 hover:bg-slate-100" onClick={() => setBox({ x: (imageWidth - style.box.width) / 2 })}>
            Centre horizontally
          </button>
          <button type="button" className="flex-1 rounded-md bg-white px-2 py-1 text-xs font-medium text-slate-700 ring-1 ring-slate-300 hover:bg-slate-100" onClick={() => setBox({ y: (imageHeight - style.box.height) / 2 })}>
            Centre vertically
          </button>
        </div>
      </fieldset>
    </div>
  );
}
