import type { Box, TextStyle } from "./types";

/** Default name box: centred, 60% of the certificate width, slightly below the middle. */
export function defaultNameStyle(width: number, height: number, fontId: string): TextStyle {
  const fontSize = Math.max(12, Math.round(height * 0.07));
  return {
    box: {
      x: Math.round(width * 0.2),
      y: Math.round(height * 0.42),
      width: Math.round(width * 0.6),
      height: Math.round(height * 0.12),
    },
    font_id: fontId,
    font_size: fontSize,
    min_font_size: Math.max(8, Math.round(fontSize * 0.55)),
    color: "#1f2937",
    align: "center",
    vertical_align: "middle",
    allow_wrap: true,
    max_lines: 2,
    line_spacing: 1.15,
  };
}

export function defaultDepartmentStyle(height: number, name: TextStyle): TextStyle {
  const fontSize = Math.max(10, Math.round(height * 0.032));
  const y = Math.min(height - Math.round(height * 0.07), name.box.y + name.box.height + Math.round(height * 0.02));
  return {
    ...name,
    box: { x: name.box.x, y, width: name.box.width, height: Math.round(height * 0.06) },
    font_size: fontSize,
    min_font_size: Math.max(8, Math.round(fontSize * 0.6)),
    allow_wrap: false,
    max_lines: 1,
  };
}

export const MIN_BOX = 12;

export function clampBox(box: Box, width: number, height: number): Box {
  const w = Math.min(Math.max(MIN_BOX, box.width), width);
  const h = Math.min(Math.max(MIN_BOX, box.height), height);
  return {
    x: Math.round(Math.min(Math.max(0, box.x), width - w)),
    y: Math.round(Math.min(Math.max(0, box.y), height - h)),
    width: Math.round(w),
    height: Math.round(h),
  };
}
