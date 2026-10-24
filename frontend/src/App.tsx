import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { DownloadStep } from "./components/DownloadStep";
import { EditorStep } from "./components/EditorStep";
import { ExcelStep } from "./components/ExcelStep";
import { GenerateStep } from "./components/GenerateStep";
import { TemplateStep } from "./components/TemplateStep";
import { Alert, Button, Spinner, Stepper, type StepDef } from "./components/ui";
import { defaultNameStyle } from "./defaults";
import type { CertificateConfig, ColumnMapping, ExcelData, FontInfo, JobStatus, TemplateInfo, TextStyle } from "./types";

const STEPS: StepDef[] = [
  { title: "Upload Excel", subtitle: "Student list" },
  { title: "Upload Certificate", subtitle: "Original PNG" },
  { title: "Configure Name", subtitle: "Position & style" },
  { title: "Generate", subtitle: "Review & create" },
  { title: "Download", subtitle: "ZIP, PNG, PDF" },
];

const EMPTY_MAPPING: ColumnMapping = { name_column: null, department_column: null, email_column: null };

export default function App() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [retention, setRetention] = useState(60);
  const [startupError, setStartupError] = useState<string | null>(null);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [step, setStep] = useState(0);
  const [excel, setExcel] = useState<ExcelData | null>(null);
  const [mapping, setMapping] = useState<ColumnMapping>(EMPTY_MAPPING);
  const [template, setTemplate] = useState<TemplateInfo | null>(null);
  const [templateVersion, setTemplateVersion] = useState(0);
  const [fonts, setFonts] = useState<FontInfo[]>([]);
  const [defaultFont, setDefaultFont] = useState("builtin:default");
  const [nameStyle, setNameStyle] = useState<TextStyle | null>(null);
  const [departmentEnabled, setDepartmentEnabled] = useState(false);
  const [departmentStyle, setDepartmentStyle] = useState<TextStyle | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const [previewOk, setPreviewOk] = useState(false);
  const [job, setJob] = useState<JobStatus | null>(null);

  const handleError = useCallback((err: unknown) => {
    if (err instanceof ApiError && err.status === 404 && /session/i.test(err.message)) setSessionExpired(true);
    else setError(err instanceof Error ? err.message : String(err));
  }, []);

  const startSession = useCallback(async () => {
    setStartupError(null);
    setSessionExpired(false);
    setError(null);
    setStep(0);
    setExcel(null);
    setMapping(EMPTY_MAPPING);
    setTemplate(null);
    setNameStyle(null);
    setDepartmentEnabled(false);
    setDepartmentStyle(null);
    setSelectedIndex(-1);
    setPreviewOk(false);
    setJob(null);
    try {
      const session = await api.createSession();
      const fontList = await api.fonts(session.session_id);
      setSessionId(session.session_id);
      setRetention(session.retention_minutes);
      setFonts(fontList.fonts);
      setDefaultFont(fontList.default_font_id);
    } catch (err) {
      setStartupError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  const started = useRef(false);
  useEffect(() => {
    if (started.current) return; // StrictMode runs effects twice in development
    started.current = true;
    startSession();
  }, [startSession]);

  // Keep the previewed student valid when the data or the name column changes.
  useEffect(() => {
    if (!excel || !mapping.name_column) return;
    const current = excel.records[selectedIndex];
    if (!current || !current.values[mapping.name_column]) {
      const first = excel.records.find((r) => r.values[mapping.name_column!]);
      setSelectedIndex(first ? first.index : -1);
    }
  }, [excel, mapping.name_column, selectedIndex]);

  useEffect(() => {
    if (!mapping.department_column) setDepartmentEnabled(false);
  }, [mapping.department_column]);

  function onExcel(data: ExcelData) {
    setExcel(data);
    setMapping(data.detected_mapping);
    setSelectedIndex(-1);
    setJob(null);
  }

  function onTemplate(info: TemplateInfo) {
    const sameSize = template && template.width === info.width && template.height === info.height;
    setTemplate(info);
    setTemplateVersion((v) => v + 1);
    setJob(null);
    if (!sameSize || !nameStyle) {
      setNameStyle(defaultNameStyle(info.width, info.height, defaultFont));
      setDepartmentStyle(null);
      setDepartmentEnabled(false);
    }
  }

  const config = useMemo<CertificateConfig | null>(() => {
    if (!nameStyle || !mapping.name_column) return null;
    return {
      mapping: { name_column: mapping.name_column, department_column: mapping.department_column, email_column: mapping.email_column },
      name: nameStyle,
      department_enabled: departmentEnabled && !!departmentStyle,
      department: departmentEnabled ? departmentStyle : null,
    };
  }, [nameStyle, mapping, departmentEnabled, departmentStyle]);

  const jobFinished = !!job && !["queued", "running"].includes(job.status);
  const canEditor = !!excel && !!mapping.name_column && !!template && !!config;
  const maxReachable = jobFinished && canEditor ? 4 : canEditor && previewOk ? 3 : canEditor ? 2 : excel && mapping.name_column ? 1 : 0;

  const onJob = useCallback((next: JobStatus) => setJob(next), []);
  const goDownloads = useCallback(() => setStep(4), []);
  const jobId = job?.job_id;
  const refreshJob = useCallback(() => {
    if (jobId) api.job(jobId).then(setJob).catch(handleError);
  }, [jobId, handleError]);

  async function startOver() {
    if (!window.confirm("Delete the uploaded files and all generated certificates from the server and start again?")) return;
    if (sessionId) await api.deleteSession(sessionId).catch(() => undefined);
    await startSession();
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600 text-white">
              <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
                <rect x="3" y="4" width="18" height="13" rx="2" />
                <path d="M7 9h10M7 12.5h6M9 17l-1 4 4-2 4 2-1-4" />
              </svg>
            </div>
            <div>
              <h1 className="text-lg font-semibold text-slate-900">Certificate Name Autofiller</h1>
              <p className="text-xs text-slate-500">Personalised certificates from your Excel list and your original PNG</p>
            </div>
          </div>
          <p className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 ring-1 ring-inset ring-emerald-200">
            Processed on your server only · no external AI services
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6">
        {startupError && (
          <Alert kind="error" title="Could not connect to the backend">
            <p>{startupError}</p>
            <p className="mt-1">Start it with <code className="rounded bg-rose-100 px-1">uvicorn app.main:app --port 8000</code> in the backend folder, then retry.</p>
            <Button className="mt-3" variant="secondary" onClick={startSession}>Retry</Button>
          </Alert>
        )}
        {sessionExpired && (
          <Alert kind="warning" title="Your session has expired">
            <p>Uploaded files are deleted after {retention} minutes of inactivity or when the server restarts.</p>
            <Button className="mt-3" variant="secondary" onClick={startSession}>Start again</Button>
          </Alert>
        )}

        {!sessionId && !startupError && (
          <p className="flex items-center gap-2 text-sm text-slate-500"><Spinner /> Connecting…</p>
        )}

        {sessionId && (
          <>
            <Stepper steps={STEPS} current={step} maxReachable={maxReachable} onSelect={setStep} />

            {step === 0 && (
              <ExcelStep sessionId={sessionId} excel={excel} mapping={mapping} onExcel={onExcel} onMapping={setMapping} onError={handleError} onNext={() => setStep(1)} />
            )}
            {step === 1 && (
              <TemplateStep sessionId={sessionId} template={template} templateVersion={templateVersion} onTemplate={onTemplate} onError={handleError} onBack={() => setStep(0)} onNext={() => setStep(2)} />
            )}
            {step === 2 && canEditor && (
              <EditorStep
                sessionId={sessionId}
                excel={excel!}
                mapping={mapping}
                template={template!}
                templateVersion={templateVersion}
                fonts={fonts}
                config={config!}
                selectedIndex={selectedIndex}
                onSelectIndex={setSelectedIndex}
                onNameStyle={setNameStyle}
                onDepartment={(enabled, style) => {
                  setDepartmentEnabled(enabled);
                  setDepartmentStyle(style);
                }}
                onFontUploaded={(font) => setFonts((list) => [font, ...list])}
                onPreviewOk={setPreviewOk}
                onError={handleError}
                onBack={() => setStep(1)}
                onNext={() => {
                  setJob(null);
                  setStep(3);
                }}
              />
            )}
            {step === 3 && canEditor && (
              <GenerateStep sessionId={sessionId} config={config!} job={job} onJob={onJob} onError={handleError} onBack={() => setStep(2)} onDone={goDownloads} />
            )}
            {step === 4 && job && (
              <DownloadStep
                sessionId={sessionId}
                job={job}
                columns={excel?.columns ?? []}
                emailColumn={mapping.email_column}
                retentionMinutes={retention}
                onJobRefresh={refreshJob}
                onError={handleError}
                onBackToEditor={() => setStep(2)}
                onStartOver={startOver}
              />
            )}
          </>
        )}
      </main>

      {error && (
        <div className="fixed bottom-4 right-4 z-50 w-[min(28rem,calc(100vw-2rem))]">
          <div className="flex items-start gap-3 rounded-xl bg-white p-4 shadow-lg ring-1 ring-rose-200">
            <div className="flex-1 text-sm text-rose-800">
              <p className="font-semibold">Something went wrong</p>
              <p className="mt-1">{error}</p>
            </div>
            <button type="button" aria-label="Dismiss" onClick={() => setError(null)} className="rounded p-1 text-slate-400 hover:text-slate-700">✕</button>
          </div>
        </div>
      )}
    </div>
  );
}
