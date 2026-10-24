import { useState } from "react";
import { api } from "../api";
import type { TemplateInfo } from "../types";
import { Alert, Button, Card, Dropzone, formatBytes } from "./ui";

const MAX_MB = 30;

interface Props {
  sessionId: string;
  template: TemplateInfo | null;
  templateVersion: number;
  onTemplate: (info: TemplateInfo) => void;
  onError: (err: unknown) => void;
  onBack: () => void;
  onNext: () => void;
}

export function TemplateStep({ sessionId, template, templateVersion, onTemplate, onError, onBack, onNext }: Props) {
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  async function upload(file: File) {
    setLocalError(null);
    if (!/\.png$/i.test(file.name) || (file.type && file.type !== "image/png")) {
      return setLocalError("Please choose a PNG image (.png). Convert other formats to PNG first.");
    }
    if (file.size > MAX_MB * 1024 * 1024) return setLocalError(`The image is larger than ${MAX_MB} MB.`);
    setBusy(true);
    try {
      onTemplate(await api.uploadTemplate(sessionId, file));
    } catch (err) {
      onError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card title="Upload the original certificate (PNG)">
        <Dropzone
          accept=".png,image/png"
          title={template ? "Drop a different PNG to replace the template" : "Drag & drop your certificate PNG here, or click to browse"}
          hint={`PNG only · landscape or portrait · up to ${MAX_MB} MB`}
          busy={busy}
          onFile={upload}
        />
        {localError && <div className="mt-3"><Alert kind="error">{localError}</Alert></div>}
      </Card>

      {template && (
        <Card title={`Template: ${template.filename}`}>
          <dl className="mb-4 grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
            <div><dt className="text-slate-500">Dimensions</dt><dd className="font-medium">{template.width} × {template.height} px</dd></div>
            <div><dt className="text-slate-500">Orientation</dt><dd className="font-medium">{template.width >= template.height ? "Landscape" : "Portrait"}</dd></div>
            <div><dt className="text-slate-500">Resolution</dt><dd className="font-medium">{template.dpi ? `${template.dpi[0]} DPI` : "Not specified"}</dd></div>
            <div><dt className="text-slate-500">File size</dt><dd className="font-medium">{formatBytes(template.file_size)}</dd></div>
          </dl>
          <div className="overflow-hidden rounded-lg bg-[repeating-conic-gradient(#e2e8f0_0_25%,#fff_0_50%)] bg-[length:20px_20px] ring-1 ring-slate-200">
            <img
              src={api.templateUrl(sessionId, templateVersion)}
              alt="Uploaded certificate template"
              className="mx-auto block h-auto max-h-[70vh] w-auto max-w-full"
            />
          </div>
          <p className="mt-3 text-xs text-slate-500">
            This is your exact uploaded file. It is used unchanged as the background of every certificate. Only the name text is added on top.
          </p>
        </Card>
      )}

      <div className="flex justify-between">
        <Button variant="secondary" onClick={onBack}>← Back</Button>
        <Button disabled={!template} onClick={onNext}>Continue: place the name →</Button>
      </div>
    </div>
  );
}
