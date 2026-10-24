import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { CertificateConfig, JobStatus, ValidationResult } from "../types";
import { Alert, Button, Card, Spinner, Stat, rowList } from "./ui";

interface Props {
  sessionId: string;
  config: CertificateConfig;
  job: JobStatus | null;
  onJob: (job: JobStatus) => void;
  onError: (err: unknown) => void;
  onBack: () => void;
  onDone: () => void;
}

export function GenerateStep({ sessionId, config, job, onJob, onError, onBack, onDone }: Props) {
  const [check, setCheck] = useState<ValidationResult | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [pdf, setPdf] = useState(false);
  const [png, setPng] = useState(true);
  const [approved, setApproved] = useState(false);
  const [starting, setStarting] = useState(false);
  const poll = useRef<number>();

  useEffect(() => {
    let cancelled = false;
    api
      .validate(sessionId, config)
      .then((r) => !cancelled && setCheck(r))
      .catch((err) => !cancelled && (err?.status === 422 ? setCheckError(err.message) : onError(err)));
    return () => {
      cancelled = true;
    };
  }, [sessionId, config, onError]);

  const running = job?.status === "queued" || job?.status === "running";

  useEffect(() => {
    if (!job || !running) return;
    poll.current = window.setTimeout(async () => {
      try {
        const next = await api.job(job.job_id);
        onJob(next);
        if (next.status === "completed" || next.status === "cancelled") onDone();
      } catch (err) {
        onError(err);
      }
    }, 600);
    return () => window.clearTimeout(poll.current);
  }, [job, running, onJob, onDone, onError]);

  async function start() {
    setStarting(true);
    try {
      const { job_id } = await api.generate(sessionId, config, { png, pdf });
      onJob(await api.job(job_id));
    } catch (err) {
      onError(err);
    } finally {
      setStarting(false);
    }
  }

  const fit = check?.fit;
  const percent = job && job.total ? Math.round((job.processed / job.total) * 100) : 0;

  return (
    <div className="space-y-6">
      <Card title="Pre-generation check">
        {!check && !checkError && <p className="flex items-center gap-2 text-sm text-slate-500"><Spinner /> Checking every row and name layout…</p>}
        {checkError && <Alert kind="error">{checkError}</Alert>}
        {check && fit && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Stat label="Rows in sheet" value={check.total_rows} />
              <Stat label="Will be generated" value={check.will_generate} tone="green" />
              <Stat label="Blank names (skipped)" value={check.analysis.blank_name_rows.length} tone={check.analysis.blank_name_rows.length ? "red" : "slate"} />
              <Stat label="Auto-resized names" value={fit.shrunk.length + fit.wrapped.length} tone="indigo" />
            </div>
            <div className="space-y-2">
              {check.analysis.blank_name_rows.length > 0 && (
                <Alert kind="error" title="Rows with a blank name will be skipped">
                  Excel rows {rowList(check.analysis.blank_name_rows)}. They will be listed as “skipped” in the final report.
                </Alert>
              )}
              {fit.clipped.length > 0 && (
                <Alert kind="error" title={`${fit.clipped.length} name(s) would be cut off at the certificate edge and will fail`}>
                  Rows {rowList(fit.clipped.map((f) => f.row))}. Go back and enlarge the text box or lower the smallest font size.
                </Alert>
              )}
              {fit.overflow.length > 0 && (
                <Alert kind="warning" title={`${fit.overflow.length} name(s) are larger than the text box even at the smallest size`}>
                  {fit.overflow.slice(0, 5).map((f) => `Row ${f.row}: ${f.text}`).join(" · ")}
                  {fit.overflow.length > 5 && " …"}
                </Alert>
              )}
              {fit.shaping.length > 0 && (
                <Alert kind="warning" title={`${fit.shaping.length} name(s) use a script that needs complex text shaping`}>
                  Rows {rowList(fit.shaping.map((f) => f.row))}. The server's Pillow build lacks the raqm library, so letters in
                  scripts such as Tamil, Hindi or Arabic may not join correctly. See “Complex scripts” in the README.
                </Alert>
              )}
              {fit.department_issues.length > 0 && (
                <Alert kind="warning">Department text does not fit in its box for rows {rowList(fit.department_issues.map((f) => f.row))}.</Alert>
              )}
              {check.analysis.duplicate_groups.length > 0 && (
                <Alert kind="info">{check.analysis.duplicate_groups.length} duplicate name(s): each row still gets its own numbered file.</Alert>
              )}
              {(fit.shrunk.length > 0 || fit.wrapped.length > 0) && (
                <Alert kind="info">
                  {fit.shrunk.length} long name(s) will use a smaller font and {fit.wrapped.length} will wrap onto multiple lines so that they fit.
                </Alert>
              )}
            </div>
          </div>
        )}
      </Card>

      <Card title="Generate certificates">
        <div className="flex flex-wrap gap-6 text-sm">
          <label className="flex items-center gap-2">
            <input type="checkbox" className="h-4 w-4 accent-indigo-600" checked={png} disabled={running} onChange={(e) => setPng(e.target.checked)} />
            PNG (original quality and dimensions)
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" className="h-4 w-4 accent-indigo-600" checked={pdf} disabled={running} onChange={(e) => setPdf(e.target.checked)} />
            Also create PDF versions
          </label>
        </div>

        <label className="mt-4 flex items-start gap-2 rounded-lg bg-indigo-50 p-3 text-sm text-indigo-900 ring-1 ring-inset ring-indigo-200">
          <input type="checkbox" className="mt-0.5 h-4 w-4 accent-indigo-600" checked={approved} disabled={running} onChange={(e) => setApproved(e.target.checked)} />
          <span>I have checked the preview and approve this name position and style for all {check?.will_generate ?? "…"} certificates.</span>
        </label>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button disabled={!approved || !check || check.will_generate === 0 || running || starting || (!png && !pdf)} onClick={start}>
            {(starting || running) && <Spinner />} Generate {check?.will_generate ?? ""} certificates
          </Button>
          {running && job && (
            <Button variant="secondary" onClick={() => api.cancelJob(job.job_id).catch(onError)}>Cancel</Button>
          )}
          {!png && !pdf && <span className="text-sm text-rose-600">Choose at least one format.</span>}
        </div>

        {job && (
          <div className="mt-5">
            <div className="flex justify-between text-sm">
              <span className="font-medium text-slate-700">
                {running ? "Generating…" : job.status === "completed" ? "Finished" : job.status === "cancelled" ? "Cancelled" : "Failed"}
              </span>
              <span className="tabular-nums text-slate-500">{job.processed} / {job.total} · {percent}%</span>
            </div>
            <div className="mt-2 h-3 overflow-hidden rounded-full bg-slate-200" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
              <div className={`h-full transition-all ${job.status === "failed" ? "bg-rose-500" : "bg-indigo-600"}`} style={{ width: `${percent}%` }} />
            </div>
            <p className="mt-2 text-xs text-slate-500">
              {job.counts.generated} generated · {job.counts.skipped} skipped · {job.counts.failed} failed
            </p>
            {job.error && <div className="mt-3"><Alert kind="error" title="Generation failed">{job.error}</Alert></div>}
          </div>
        )}
      </Card>

      <div className="flex justify-between">
        <Button variant="secondary" disabled={running} onClick={onBack}>← Back to editor</Button>
        {job && !running && <Button onClick={onDone}>View downloads →</Button>}
      </div>
    </div>
  );
}
