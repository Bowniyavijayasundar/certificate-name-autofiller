import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api";
import { defaultDepartmentStyle } from "../defaults";
import { useDebounced } from "../hooks";
import type { Box, CertificateConfig, ColumnMapping, ExcelData, FontInfo, PreviewResult, TemplateInfo, TextStyle } from "../types";
import { CertificateCanvas, type FieldKey } from "./CertificateCanvas";
import { StylePanel } from "./StylePanel";
import { Alert, Button, Card, Spinner } from "./ui";

interface Props {
  sessionId: string;
  excel: ExcelData;
  mapping: ColumnMapping;
  template: TemplateInfo;
  templateVersion: number;
  fonts: FontInfo[];
  config: CertificateConfig;
  selectedIndex: number;
  onSelectIndex: (index: number) => void;
  onNameStyle: (style: TextStyle) => void;
  onDepartment: (enabled: boolean, style: TextStyle | null) => void;
  onFontUploaded: (font: FontInfo) => void;
  onPreviewOk: (ok: boolean) => void;
  onError: (err: unknown) => void;
  onBack: () => void;
  onNext: () => void;
}

export function EditorStep(props: Props) {
  const { sessionId, excel, mapping, template, templateVersion, fonts, config, selectedIndex, onSelectIndex } = props;
  const [active, setActive] = useState<FieldKey>("name");
  const [showGuides, setShowGuides] = useState(true);
  const [displayWidth, setDisplayWidth] = useState(0);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const nameColumn = mapping.name_column!;
  const validRecords = useMemo(() => excel.records.filter((r) => r.values[nameColumn]), [excel, nameColumn]);
  const position = validRecords.findIndex((r) => r.index === selectedIndex);

  // Request a preview width that matches the screen (sharp on HiDPI, never above the original).
  const maxWidth = useMemo(() => {
    if (!displayWidth) return Math.min(template.width, 1400);
    const wanted = Math.ceil((displayWidth * (window.devicePixelRatio || 1)) / 200) * 200;
    return Math.max(200, Math.min(template.width, wanted));
  }, [displayWidth, template.width]);

  const request = useDebounced(JSON.stringify({ config, selectedIndex, maxWidth }), 300);

  useEffect(() => {
    const { config: cfg, selectedIndex: index, maxWidth: width } = JSON.parse(request);
    if (index < 0) return;
    const controller = new AbortController();
    setLoading(true);
    api
      .preview(sessionId, index, cfg, width, controller.signal)
      .then((result) => {
        setPreview(result);
        setPreviewError(result.error);
        props.onPreviewOk(!result.error);
      })
      .catch((err) => {
        if ((err as Error).name === "AbortError") return;
        if (err instanceof ApiError && err.status === 422) {
          setPreviewError(err.message);
          props.onPreviewOk(false);
        } else props.onError(err);
      })
      .finally(() => !controller.signal.aborted && setLoading(false));
    return () => controller.abort();
  }, [request, sessionId]);

  const fieldStyle = active === "department" && config.department_enabled && config.department ? config.department : config.name;
  const setFieldStyle = (style: TextStyle) =>
    active === "department" ? props.onDepartment(true, style) : props.onNameStyle(style);

  const onBoxChange = useCallback(
    (key: FieldKey, box: Box) => {
      if (key === "name") props.onNameStyle({ ...config.name, box });
      else if (config.department) props.onDepartment(true, { ...config.department, box });
    },
    [config],
  );

  const fields = [{ key: "name" as FieldKey, label: "Student name", box: config.name.box }];
  if (config.department_enabled && config.department) fields.push({ key: "department", label: "Department", box: config.department.box });

  function toggleDepartment(enabled: boolean) {
    props.onDepartment(enabled, enabled ? config.department ?? defaultDepartmentStyle(template.height, config.name) : config.department);
    setActive(enabled ? "department" : "name");
  }

  function pickLongest() {
    const longest = validRecords.reduce((a, b) => (b.values[nameColumn].length > a.values[nameColumn].length ? b : a), validRecords[0]);
    if (longest) onSelectIndex(longest.index);
  }

  const layout = preview?.name_layout;
  const previewMatches = preview && preview.record.index === selectedIndex;

  return (
    <div className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card
          title="Position the name on your certificate"
          actions={
            <div className="flex items-center gap-3 text-sm">
              {loading && <span className="flex items-center gap-1.5 text-slate-500"><Spinner /> Updating preview…</span>}
              <label className="flex items-center gap-2">
                <input type="checkbox" className="h-4 w-4 accent-indigo-600" checked={showGuides} onChange={(e) => setShowGuides(e.target.checked)} />
                Show text boxes
              </label>
            </div>
          }
        >
          <p className="mb-3 text-xs text-slate-500">
            Drag on the certificate to draw the area for the name, drag the box to move it, use the handles to resize, or click once to centre it on that spot.
            The image below is rendered by the server exactly as the final certificate will be.
          </p>
          <CertificateCanvas
            imageSrc={preview?.image ?? api.templateUrl(sessionId, templateVersion)}
            imageWidth={template.width}
            imageHeight={template.height}
            fields={fields}
            active={active}
            showGuides={showGuides}
            onActivate={setActive}
            onBoxChange={onBoxChange}
            onWidth={setDisplayWidth}
          />

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button variant="secondary" disabled={position <= 0} onClick={() => onSelectIndex(validRecords[position - 1].index)}>‹ Prev</Button>
            <select
              aria-label="Student to preview"
              className="min-w-0 flex-1 rounded-lg py-2 pl-3 pr-8 text-sm ring-1 ring-slate-300"
              value={selectedIndex}
              onChange={(e) => onSelectIndex(Number(e.target.value))}
            >
              {validRecords.map((r) => (
                <option key={r.index} value={r.index}>
                  Row {r.row_number}: {r.values[nameColumn]}
                </option>
              ))}
            </select>
            <Button variant="secondary" disabled={position < 0 || position >= validRecords.length - 1} onClick={() => onSelectIndex(validRecords[position + 1].index)}>Next ›</Button>
            <Button variant="ghost" onClick={pickLongest} title="Preview the student with the longest name">Longest name</Button>
          </div>

          <div className="mt-3 space-y-2">
            {previewMatches && layout && !previewError && (
              <p className="text-sm text-slate-600">
                Previewing <strong>row {preview.record.row_number}</strong> · font {layout.font_size}px
                {layout.shrunk && ` (reduced from ${config.name.font_size}px)`} · {layout.lines.length} line{layout.lines.length > 1 ? "s" : ""}
              </p>
            )}
            {previewError && <Alert kind="error">{previewError}</Alert>}
            {!previewError && preview?.warnings.map((w) => <Alert key={w} kind="warning">{w}</Alert>)}
          </div>
        </Card>

        <div className="space-y-4">
          <Card>
            <div className="mb-4 flex rounded-lg bg-slate-100 p-0.5 text-sm">
              {(["name", "department"] as FieldKey[]).map((key) => (
                <button
                  key={key}
                  type="button"
                  disabled={key === "department" && !config.department_enabled}
                  onClick={() => setActive(key)}
                  className={`flex-1 rounded-md px-3 py-1.5 font-medium disabled:text-slate-400 ${active === key ? "bg-white text-indigo-700 shadow-sm" : "text-slate-600"}`}
                >
                  {key === "name" ? "Name text" : "Department text"}
                </button>
              ))}
            </div>
            <StylePanel
              sessionId={sessionId}
              style={fieldStyle}
              fonts={fonts}
              imageWidth={template.width}
              imageHeight={template.height}
              onChange={setFieldStyle}
              onFontUploaded={props.onFontUploaded}
              onError={props.onError}
            />
          </Card>

          <Card title="Optional: department">
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 accent-indigo-600"
                disabled={!mapping.department_column}
                checked={config.department_enabled}
                onChange={(e) => toggleDepartment(e.target.checked)}
              />
              <span>
                Also print the department
                <span className="block text-xs text-slate-500">
                  {mapping.department_column ? `From column “${mapping.department_column}”, in its own text box.` : "Select a department column in Step 1 to enable this."}
                </span>
              </span>
            </label>
          </Card>
        </div>
      </div>

      <div className="flex justify-between">
        <Button variant="secondary" onClick={props.onBack}>← Back</Button>
        <Button disabled={!preview || !!previewError || loading} onClick={props.onNext}>Continue: review &amp; generate →</Button>
      </div>
    </div>
  );
}
