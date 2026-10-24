import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { cssFontFor, loadBrowserFont } from "../hooks";
import type { FontInfo } from "../types";
import { Spinner } from "./ui";

const GROUPS: { key: string; label: string; match: (f: FontInfo) => boolean }[] = [
  { key: "uploaded", label: "Your uploaded fonts", match: (f) => f.source === "uploaded" },
  { key: "script", label: "Script & handwriting", match: (f) => f.category === "script" },
  { key: "serif", label: "Serif", match: (f) => f.category === "serif" },
  { key: "sans", label: "Sans-serif", match: (f) => f.category === "sans-serif" },
  { key: "display", label: "Decorative", match: (f) => f.category === "display" },
];

interface Props {
  sessionId: string;
  fonts: FontInfo[];
  value: string;
  onChange: (fontId: string) => void;
  onUploaded: (font: FontInfo) => void;
  onError: (err: unknown) => void;
}

export function FontPicker({ sessionId, fonts, value, onChange, onUploaded, onError }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [uploading, setUploading] = useState(false);
  const [, setLoadedCount] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const selected = fonts.find((f) => f.id === value);

  // Load browser copies of the fonts so every option is shown in its own typeface.
  useEffect(() => {
    const wanted = open ? fonts : selected ? [selected] : [];
    wanted
      .filter((f) => f.has_file)
      .forEach((f) => loadBrowserFont(f.id, f.variation, api.fontFileUrl(sessionId, f.id)).then((ok) => ok && setLoadedCount((n) => n + 1)));
  }, [open, fonts, selected, sessionId]);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !root.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = fonts.filter((f) => !q || f.name.toLowerCase().includes(q));
    const used = new Set<string>();
    return GROUPS.map((g) => {
      const items = list.filter((f) => !used.has(f.id) && g.match(f));
      items.forEach((f) => used.add(f.id));
      return { ...g, items };
    }).filter((g) => g.items.length);
  }, [fonts, query]);

  async function upload(file: File) {
    if (!/\.(ttf|otf)$/i.test(file.name)) return onError(new Error("Font files must be .ttf or .otf"));
    setUploading(true);
    try {
      const font = await api.uploadFont(sessionId, file);
      onUploaded(font);
      onChange(font.id);
      setOpen(false);
    } catch (err) {
      onError(err);
    } finally {
      setUploading(false);
    }
  }

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex w-full items-center justify-between rounded-lg bg-white px-3 py-2 text-left text-sm ring-1 ring-slate-300 hover:ring-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
      >
        <span className="truncate text-base" style={selected ? cssFontFor(selected.id, selected.variation) : undefined}>
          {selected?.name ?? "Choose a font"}
        </span>
        <svg className="h-4 w-4 shrink-0 text-slate-400" viewBox="0 0 20 20" fill="currentColor" aria-hidden>
          <path d="M5.3 7.3a1 1 0 0 1 1.4 0L10 10.6l3.3-3.3a1 1 0 1 1 1.4 1.4l-4 4a1 1 0 0 1-1.4 0l-4-4a1 1 0 0 1 0-1.4Z" />
        </svg>
      </button>

      {open && (
        <div className="absolute z-30 mt-1 w-full min-w-[260px] rounded-xl bg-white shadow-xl ring-1 ring-slate-200">
          <div className="border-b border-slate-100 p-2">
            <input
              autoFocus
              type="search"
              placeholder="Search fonts…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full rounded-md px-2 py-1.5 text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <ul role="listbox" className="max-h-72 overflow-y-auto py-1">
            {groups.map((g) => (
              <li key={g.key}>
                <p className="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400">{g.label}</p>
                <ul>
                  {g.items.map((f) => (
                    <li key={f.id}>
                      <button
                        type="button"
                        role="option"
                        aria-selected={f.id === value}
                        onClick={() => {
                          onChange(f.id);
                          setOpen(false);
                        }}
                        className={`flex w-full items-center justify-between px-3 py-1.5 text-left hover:bg-indigo-50 ${f.id === value ? "bg-indigo-50 text-indigo-700" : ""}`}
                      >
                        <span className="truncate text-lg" style={cssFontFor(f.id, f.variation)}>{f.name}</span>
                        {f.source === "system" && <span className="ml-2 shrink-0 text-[10px] text-slate-400">system</span>}
                      </button>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
            {groups.length === 0 && <li className="px-3 py-4 text-center text-sm text-slate-500">No fonts match.</li>}
          </ul>
          <div className="border-t border-slate-100 p-2">
            <input ref={fileInput} type="file" accept=".ttf,.otf" hidden onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) upload(file);
              e.target.value = "";
            }} />
            <button
              type="button"
              disabled={uploading}
              onClick={() => fileInput.current?.click()}
              className="flex w-full items-center justify-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium text-indigo-700 hover:bg-indigo-50"
            >
              {uploading && <Spinner />} Upload your own font (.ttf / .otf)
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
