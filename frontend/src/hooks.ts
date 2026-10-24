import { useEffect, useRef, useState } from "react";

/** Width of an element, kept up to date with ResizeObserver. */
export function useElementWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(el);
    setWidth(el.getBoundingClientRect().width);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

export function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

const loadedFonts = new Map<string, Promise<boolean>>();
const WEIGHTS: Record<string, string> = { Regular: "400", Medium: "500", SemiBold: "600", Bold: "700" };

/** CSS family/weight to display a server font in the browser (used only for the font list). */
export function cssFontFor(fontId: string, variation: string | null) {
  return { fontFamily: `"cf-${fontId.replace(/[^a-z0-9]/gi, "-")}", sans-serif`, fontWeight: variation ? WEIGHTS[variation] ?? "400" : "400" };
}

export function loadBrowserFont(fontId: string, variation: string | null, url: string): Promise<boolean> {
  const key = fontId;
  let promise = loadedFonts.get(key);
  if (!promise) {
    const family = `cf-${fontId.replace(/[^a-z0-9]/gi, "-")}`;
    const face = new FontFace(family, `url(${url})`, variation ? { weight: WEIGHTS[variation] ?? "400" } : {});
    promise = face
      .load()
      .then((loaded) => {
        document.fonts.add(loaded);
        return true;
      })
      .catch(() => false);
    loadedFonts.set(key, promise);
  }
  return promise;
}
