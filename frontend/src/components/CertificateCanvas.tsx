import { useEffect, useRef, type PointerEvent as ReactPointerEvent } from "react";
import { clampBox, MIN_BOX } from "../defaults";
import { useElementWidth } from "../hooks";
import type { Box } from "../types";

export type FieldKey = "name" | "department";

interface FieldBox {
  key: FieldKey;
  label: string;
  box: Box;
}

interface Props {
  imageSrc: string;
  imageWidth: number;     // template width in pixels
  imageHeight: number;
  fields: FieldBox[];
  active: FieldKey;
  showGuides: boolean;
  onActivate: (key: FieldKey) => void;
  onBoxChange: (key: FieldKey, box: Box) => void;
  onWidth?: (displayWidth: number) => void;
}

type Handle = "n" | "s" | "e" | "w" | "ne" | "nw" | "se" | "sw";
type Drag =
  | { kind: "move"; key: FieldKey; startX: number; startY: number; box: Box }
  | { kind: "resize"; key: FieldKey; handle: Handle; startX: number; startY: number; box: Box }
  | { kind: "draw"; startX: number; startY: number; moved: boolean };

const HANDLES: { h: Handle; cls: string }[] = [
  { h: "nw", cls: "-left-1.5 -top-1.5 cursor-nwse-resize" },
  { h: "n", cls: "left-1/2 -top-1.5 -translate-x-1/2 cursor-ns-resize" },
  { h: "ne", cls: "-right-1.5 -top-1.5 cursor-nesw-resize" },
  { h: "e", cls: "-right-1.5 top-1/2 -translate-y-1/2 cursor-ew-resize" },
  { h: "se", cls: "-right-1.5 -bottom-1.5 cursor-nwse-resize" },
  { h: "s", cls: "left-1/2 -bottom-1.5 -translate-x-1/2 cursor-ns-resize" },
  { h: "sw", cls: "-left-1.5 -bottom-1.5 cursor-nesw-resize" },
  { h: "w", cls: "-left-1.5 top-1/2 -translate-y-1/2 cursor-ew-resize" },
];

export function CertificateCanvas({ imageSrc, imageWidth, imageHeight, fields, active, showGuides, onActivate, onBoxChange, onWidth }: Props) {
  const [wrapRef, displayWidth] = useElementWidth<HTMLDivElement>();
  const drag = useRef<Drag | null>(null);
  const scale = displayWidth > 0 ? displayWidth / imageWidth : 1;
  useEffect(() => {
    if (displayWidth) onWidth?.(displayWidth);
  }, [displayWidth, onWidth]);

  /** Pointer position in ORIGINAL template pixels. */
  function toImage(e: ReactPointerEvent) {
    const rect = wrapRef.current!.getBoundingClientRect();
    return {
      x: Math.min(imageWidth, Math.max(0, (e.clientX - rect.left) / scale)),
      y: Math.min(imageHeight, Math.max(0, (e.clientY - rect.top) / scale)),
    };
  }

  function begin(e: ReactPointerEvent, next: Drag) {
    e.preventDefault();
    e.stopPropagation();
    wrapRef.current?.setPointerCapture(e.pointerId);
    drag.current = next;
  }

  function onPointerMove(e: ReactPointerEvent) {
    const d = drag.current;
    if (!d) return;
    const p = toImage(e);
    if (d.kind === "move") {
      onBoxChange(d.key, clampBox({ ...d.box, x: d.box.x + p.x - d.startX, y: d.box.y + p.y - d.startY }, imageWidth, imageHeight));
    } else if (d.kind === "resize") {
      let { x, y, width, height } = d.box;
      const dx = p.x - d.startX;
      const dy = p.y - d.startY;
      if (d.handle.includes("e")) width = Math.max(MIN_BOX, width + dx);
      if (d.handle.includes("s")) height = Math.max(MIN_BOX, height + dy);
      if (d.handle.includes("w")) {
        const nx = Math.min(x + width - MIN_BOX, x + dx);
        width += x - nx;
        x = nx;
      }
      if (d.handle.includes("n")) {
        const ny = Math.min(y + height - MIN_BOX, y + dy);
        height += y - ny;
        y = ny;
      }
      x = Math.max(0, x);
      y = Math.max(0, y);
      width = Math.min(width, imageWidth - x);
      height = Math.min(height, imageHeight - y);
      onBoxChange(d.key, clampBox({ x, y, width, height }, imageWidth, imageHeight));
    } else {
      const moved = d.moved || Math.abs(p.x - d.startX) * scale > 4 || Math.abs(p.y - d.startY) * scale > 4;
      d.moved = moved;
      if (moved) {
        onBoxChange(active, clampBox({
          x: Math.min(d.startX, p.x),
          y: Math.min(d.startY, p.y),
          width: Math.abs(p.x - d.startX),
          height: Math.abs(p.y - d.startY),
        }, imageWidth, imageHeight));
      }
    }
  }

  function onPointerUp(e: ReactPointerEvent) {
    const d = drag.current;
    drag.current = null;
    wrapRef.current?.releasePointerCapture?.(e.pointerId);
    if (d?.kind === "draw" && !d.moved) {
      // Single click: centre the active text box on the clicked point.
      const current = fields.find((f) => f.key === active)!.box;
      onBoxChange(active, clampBox({ ...current, x: d.startX - current.width / 2, y: d.startY - current.height / 2 }, imageWidth, imageHeight));
    }
  }

  return (
    <div
      ref={wrapRef}
      className="relative w-full touch-none select-none overflow-hidden rounded-lg bg-slate-100 ring-1 ring-slate-200"
      style={{ aspectRatio: `${imageWidth} / ${imageHeight}`, cursor: "crosshair" }}
      onPointerDown={(e) => {
        const p = toImage(e);
        begin(e, { kind: "draw", startX: p.x, startY: p.y, moved: false });
      }}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={() => (drag.current = null)}
    >
      <img src={imageSrc} alt="Certificate preview" draggable={false} className="pointer-events-none absolute inset-0 h-full w-full" />
      {showGuides &&
        fields.map((f) => {
          const isActive = f.key === active;
          return (
            <div
              key={f.key}
              className={`absolute border-2 border-dashed ${isActive ? "border-indigo-500 bg-indigo-500/5" : "border-amber-500/80"}`}
              style={{ left: f.box.x * scale, top: f.box.y * scale, width: f.box.width * scale, height: f.box.height * scale, cursor: "move" }}
              onPointerDown={(e) => {
                onActivate(f.key);
                const p = toImage(e);
                begin(e, { kind: "move", key: f.key, startX: p.x, startY: p.y, box: f.box });
              }}
            >
              <span className={`pointer-events-none absolute left-0 ${f.box.y * scale < 26 ? "top-0" : "-top-6"} whitespace-nowrap rounded px-1.5 py-0.5 text-[11px] font-medium text-white ${isActive ? "bg-indigo-600" : "bg-amber-600"}`}>
                {f.label}
              </span>
              {isActive &&
                HANDLES.map(({ h, cls }) => (
                  <span
                    key={h}
                    className={`absolute h-3 w-3 rounded-sm border-2 border-indigo-600 bg-white ${cls}`}
                    onPointerDown={(e) => {
                      const p = toImage(e);
                      begin(e, { kind: "resize", key: f.key, handle: h, startX: p.x, startY: p.y, box: f.box });
                    }}
                  />
                ))}
            </div>
          );
        })}
    </div>
  );
}
