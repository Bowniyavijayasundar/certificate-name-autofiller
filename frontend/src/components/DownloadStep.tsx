import { useMemo, useState } from "react";
import { api } from "../api";
import type { JobStatus, ResultStatus } from "../types";
import { EmailPanel } from "./EmailPanel";
import { Alert, Button, Card, Stat } from "./ui";

type Filter = "all" | ResultStatus | "warnings";

const STATUS_STYLE: Record<ResultStatus, string> = {
  generated: "bg-emerald-100 text-emerald-800",
  skipped: "bg-amber-100 text-amber-800",
  failed: "bg-rose-100 text-rose-800",
  cancelled: "bg-slate-200 text-slate-700",
  pending: "bg-slate-100 text-slate-600",
};

interface Props {
  sessionId: string;
  job: JobStatus;
  columns: string[];
  emailColumn: string | null;
  retentionMinutes: number;
  onJobRefresh: () => void;
  onError: (err: unknown) => void;
  onBackToEditor: () => void;
  onStartOver: () => void;
}

export function DownloadStep({ sessionId, job, columns, emailColumn, retentionMinutes, onJobRefresh, onError, onBackToEditor, onStartOver }: Props) {
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const results = job.results ?? [];

  const rows = useMemo(() => {
    const q = query.trim().toLocaleLowerCase();
    return results.filter((r) => {
      if (filter === "warnings" ? !(r.status === "generated" && r.warnings.length) : filter !== "all" && r.status !== filter) return false;
      return !q || r.name.toLocaleLowerCase().includes(q) || String(r.row_number) === q;
    });
  }, [results, filter, query]);

  const problems = job.counts.skipped + job.counts.failed + job.counts.cancelled;

  return (
    <div className="space-y-6">
      <Card title="Your certificates are ready">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Generated" value={job.counts.generated} tone="green" />
          <Stat label="Skipped" value={job.counts.skipped} tone={job.counts.skipped ? "amber" : "slate"} />
          <Stat label="Failed" value={job.counts.failed + job.counts.cancelled} tone={job.counts.failed + job.counts.cancelled ? "red" : "slate"} />
          <Stat label="Auto-fitted / warnings" value={job.with_warnings} tone="indigo" />
        </div>

        <div className="mt-4">
          {job.status === "completed" && problems === 0 && (
            <Alert kind="success" title={`All ${job.counts.generated} certificates were generated successfully.`}>
              One certificate per student row, in the same order as your Excel sheet ({job.elapsed_seconds}s).
            </Alert>
          )}
          {problems > 0 && (
            <Alert kind="warning" title={`${job.counts.generated} of ${job.total} rows produced a certificate.`}>
              {problems} row(s) did not. See the table below and the report for the exact reason for each row.
            </Alert>
          )}
          {job.status === "failed" && <Alert kind="error" title="The job stopped with an error">{job.error}</Alert>}
        </div>

        <div className="mt-5 flex flex-wrap gap-3">
          <a
            href={job.zip_available ? api.zipUrl(job.job_id) : undefined}
            aria-disabled={!job.zip_available}
            className={`inline-flex items-center gap-2 rounded-lg px-5 py-2.5 text-sm font-semibold text-white ${job.zip_available ? "bg-indigo-600 hover:bg-indigo-700" : "pointer-events-none bg-indigo-300"}`}
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden><path d="M12 4v12m0 0-4-4m4 4 4-4M4 20h16" /></svg>
            Download all ({job.counts.generated}) as ZIP
          </a>
          <a href={api.fileUrl(job.job_id, "generation_report.csv")} className="inline-flex items-center rounded-lg bg-white px-4 py-2.5 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50">
            Download report (CSV)
          </a>
        </div>
        <p className="mt-3 text-xs text-slate-500">
          Uploaded files and generated certificates are deleted automatically after {retentionMinutes} minutes of inactivity, or immediately when you click “Start a new batch”.
        </p>
      </Card>

      {job.counts.generated > 0 && (
        <EmailPanel sessionId={sessionId} job={job} columns={columns} defaultEmailColumn={emailColumn} onJobRefresh={onJobRefresh} onError={onError} />
      )}

      <Card
        title="Individual certificates"
        actions={
          <div className="flex flex-wrap gap-2">
            <select value={filter} onChange={(e) => setFilter(e.target.value as Filter)} className="rounded-lg py-1.5 pl-3 pr-8 text-sm ring-1 ring-slate-300" aria-label="Filter by status">
              <option value="all">All rows ({results.length})</option>
              <option value="generated">Generated ({job.counts.generated})</option>
              <option value="warnings">With notes ({job.with_warnings})</option>
              <option value="skipped">Skipped ({job.counts.skipped})</option>
              <option value="failed">Failed ({job.counts.failed})</option>
            </select>
            <input type="search" placeholder="Search name or row…" value={query} onChange={(e) => setQuery(e.target.value)} className="w-52 rounded-lg px-3 py-1.5 text-sm ring-1 ring-slate-300" />
          </div>
        }
      >
        <div className="max-h-[32rem] overflow-auto rounded-lg ring-1 ring-slate-200">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="sticky top-0 bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2">Row</th>
                <th className="px-3 py-2">Student name</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Notes</th>
                <th className="px-3 py-2 text-right">Download</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((r) => (
                <tr key={r.index}>
                  <td className="px-3 py-2 tabular-nums text-slate-500">{r.row_number}</td>
                  <td className="px-3 py-2 font-medium text-slate-800">{r.name || <span className="text-slate-400">(blank)</span>}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[r.status]}`}>{r.status}</span>
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-600">{[r.message, ...r.warnings].filter(Boolean).join(" ")}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-right">
                    {r.png && <a className="font-medium text-indigo-600 hover:underline" href={api.fileUrl(job.job_id, r.png)} download={r.png}>PNG</a>}
                    {r.pdf && <a className="ml-3 font-medium text-indigo-600 hover:underline" href={api.fileUrl(job.job_id, r.pdf)} download={r.pdf}>PDF</a>}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr><td colSpan={5} className="px-3 py-6 text-center text-slate-500">No rows match.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="flex flex-wrap justify-between gap-3">
        <Button variant="secondary" onClick={onBackToEditor}>← Adjust layout and regenerate</Button>
        <Button variant="danger" onClick={onStartOver}>Start a new batch (delete these files)</Button>
      </div>
    </div>
  );
}
