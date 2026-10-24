import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api";
import { useDebounced } from "../hooks";
import type { EmailConfigInfo, EmailJobStatus, EmailPreview, JobStatus, RecipientStatus, SmtpPublic } from "../types";
import { EmailConnect } from "./EmailConnect";
import { Alert, Button, Card, Spinner, Stat } from "./ui";

const STATUS_LABEL: Record<RecipientStatus, { text: string; cls: string }> = {
  ready: { text: "will send", cls: "bg-emerald-100 text-emerald-800" },
  already_sent: { text: "already sent", cls: "bg-sky-100 text-sky-800" },
  no_email: { text: "no e-mail", cls: "bg-amber-100 text-amber-800" },
  invalid_email: { text: "invalid e-mail", cls: "bg-rose-100 text-rose-800" },
  no_certificate: { text: "no certificate", cls: "bg-slate-200 text-slate-700" },
  not_selected: { text: "not selected", cls: "bg-slate-100 text-slate-500" },
};

const SEND_STYLE: Record<string, string> = {
  sent: "bg-emerald-100 text-emerald-800",
  failed: "bg-rose-100 text-rose-800",
  pending: "bg-slate-100 text-slate-600",
  skipped: "bg-amber-100 text-amber-800",
  cancelled: "bg-slate-200 text-slate-700",
};

interface Props {
  sessionId: string;
  job: JobStatus;
  columns: string[];
  defaultEmailColumn: string | null;
  onJobRefresh: () => void;
  onError: (err: unknown) => void;
}

export function EmailPanel({ sessionId, job, columns, defaultEmailColumn, onJobRefresh, onError }: Props) {
  const [open, setOpen] = useState(false);
  const [info, setInfo] = useState<EmailConfigInfo | null>(null);
  const [smtp, setSmtp] = useState<SmtpPublic | null>(null);
  const [emailColumn, setEmailColumn] = useState(defaultEmailColumn ?? "");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [resend, setResend] = useState(false);
  const [onlyIndices, setOnlyIndices] = useState<number[] | null>(null);
  const [preview, setPreview] = useState<EmailPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | RecipientStatus>("all");
  const [testTo, setTestTo] = useState("");
  const [testState, setTestState] = useState<{ busy: boolean; message: string | null; ok: boolean }>({ busy: false, message: null, ok: false });
  const [authorized, setAuthorized] = useState(false);
  const [typedCount, setTypedCount] = useState("");
  const [sendJob, setSendJob] = useState<EmailJobStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (!open || info) return;
    api
      .emailConfig(sessionId)
      .then((cfg) => {
        setInfo(cfg);
        setSmtp(cfg.current);
        setSubject(cfg.default_subject);
        setBody(cfg.default_body);
        if (cfg.current) setTestTo(cfg.current.from_email);
      })
      .catch(onError);
  }, [open, info, sessionId, onError]);

  // Recipient list + rendered sample, refreshed while the user edits.
  const request = useDebounced(JSON.stringify({ emailColumn, subject, body, resend, onlyIndices, refreshKey, from: smtp?.from_name }), 350);
  useEffect(() => {
    const r = JSON.parse(request);
    if (!open || !r.emailColumn || !r.subject.trim() || !r.body.trim()) return;
    const controller = new AbortController();
    api
      .emailPreview({ session_id: sessionId, job_id: job.job_id, email_column: r.emailColumn, subject: r.subject, body: r.body,
                      resend: r.resend, only_indices: r.onlyIndices }, controller.signal)
      .then((p) => {
        setPreview(p);
        setPreviewError(null);
      })
      .catch((err) => {
        if ((err as Error).name === "AbortError") return;
        if (err instanceof ApiError && err.status === 422) setPreviewError(err.message);
        else onError(err);
      });
    return () => controller.abort();
  }, [request, open, sessionId, job.job_id, onError]);

  const sending = sendJob?.status === "queued" || sendJob?.status === "running";

  const poll = useCallback(async (id: string) => {
    try {
      const status = await api.emailJob(id);
      setSendJob(status);
      if (status.status === "queued" || status.status === "running") {
        window.setTimeout(() => poll(id), 800);
      } else {
        setRefreshKey((k) => k + 1);
        setTypedCount("");
        setAuthorized(false);
        onJobRefresh();
      }
    } catch (err) {
      onError(err);
    }
  }, [onError, onJobRefresh]);

  const ready = preview?.counts.ready ?? 0;
  const compose = { session_id: sessionId, job_id: job.job_id, email_column: emailColumn, subject, body };

  async function sendTest() {
    setTestState({ busy: true, message: null, ok: false });
    try {
      const r = await api.emailTest({ ...compose, to: testTo });
      setTestState({ busy: false, ok: true, message: `Test e-mail sent to ${r.sent_to} with ${r.attachment} (row ${r.row_number}). Check that inbox before sending to everyone.` });
    } catch (err) {
      setTestState({ busy: false, ok: false, message: err instanceof Error ? err.message : String(err) });
    }
  }

  async function sendAll() {
    setStarting(true);
    try {
      const { email_job_id } = await api.emailSend({ ...compose, resend, only_indices: onlyIndices, authorized, confirm_count: Number(typedCount) });
      setSendJob(null);
      poll(email_job_id);
    } catch (err) {
      if (err instanceof ApiError && err.status < 500) setPreviewError(err.message);
      else onError(err);
    } finally {
      setStarting(false);
    }
  }

  function retryFailed() {
    if (!sendJob) return;
    const failed = sendJob.results.filter((r) => r.status === "failed" || r.status === "cancelled").map((r) => r.index);
    setOnlyIndices(failed);
    setResend(false);
    setSendJob(null);
  }

  function insertPlaceholder(key: string) {
    setBody((b) => `${b}{${key}}`);
  }

  const shown = useMemo(
    () => (preview?.recipients ?? []).filter((r) => (filter === "all" ? r.status !== "not_selected" : r.status === filter)),
    [preview, filter],
  );

  if (!open) {
    return (
      <Card title="E-mail certificates to students (optional)">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <p className="max-w-3xl text-sm text-slate-600">
            Send each student <strong>their own certificate as a PDF</strong> to the e-mail address in their Excel row, from your own
            e-mail account. You will review every recipient and send a test to yourself first. Nothing is sent without your confirmation.
          </p>
          <Button variant="secondary" onClick={() => setOpen(true)}>
            Set up e-mail delivery
            {job.emails_sent > 0 && <span className="rounded-full bg-emerald-100 px-2 text-xs text-emerald-800">{job.emails_sent} sent</span>}
          </Button>
        </div>
      </Card>
    );
  }

  if (!info) {
    return <Card title="E-mail certificates to students"><p className="flex items-center gap-2 text-sm text-slate-500"><Spinner /> Loading…</p></Card>;
  }

  const counts = preview?.counts ?? {};
  const confirmOk = Number(typedCount) === ready && typedCount !== "";

  return (
    <Card title="E-mail certificates to students" actions={<Button variant="ghost" onClick={() => setOpen(false)}>Hide</Button>}>
      <div className="space-y-8">
        <section>
          <h3 className="mb-3 text-sm font-semibold text-slate-900">1. Connect your e-mail account</h3>
          <EmailConnect sessionId={sessionId} info={info} current={smtp} onError={onError} onConnected={(s) => {
            setSmtp(s);
            if (s && !testTo) setTestTo(s.from_email);
            setRefreshKey((k) => k + 1);
          }} />
        </section>

        <section>
          <h3 className="mb-3 text-sm font-semibold text-slate-900">2. Write the message</h3>
          <div className="grid gap-6 lg:grid-cols-2">
            <div className="space-y-3">
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-slate-700">E-mail column in your Excel sheet</span>
                <select className="rounded-lg py-2 pl-3 pr-8 text-sm ring-1 ring-slate-300" value={emailColumn} onChange={(e) => setEmailColumn(e.target.value)}>
                  <option value="">— Select column —</option>
                  {columns.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-slate-700">Subject</span>
                <input className="rounded-lg px-3 py-2 text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-indigo-500" value={subject} maxLength={300} onChange={(e) => setSubject(e.target.value)} />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-slate-700">Message</span>
                <textarea rows={8} className="rounded-lg px-3 py-2 text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-indigo-500" value={body} maxLength={20000} onChange={(e) => setBody(e.target.value)} />
              </label>
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                Insert:
                {info.placeholders.map((p) => (
                  <button key={p} type="button" onClick={() => insertPlaceholder(p)} className="rounded-md bg-slate-100 px-2 py-1 font-mono text-slate-700 hover:bg-indigo-100">{`{${p}}`}</button>
                ))}
              </div>
            </div>
            <div>
              <p className="mb-1 text-sm font-medium text-slate-700">Preview of the first e-mail</p>
              {preview?.sample ? (
                <div className="rounded-xl bg-white text-sm ring-1 ring-slate-200">
                  <dl className="space-y-1 border-b border-slate-100 px-4 py-3 text-xs">
                    <div className="flex gap-2"><dt className="w-16 text-slate-500">From</dt><dd>{smtp ? (smtp.from_name ? `${smtp.from_name} <${smtp.from_email}>` : smtp.from_email) : "(connect an account)"}</dd></div>
                    <div className="flex gap-2"><dt className="w-16 text-slate-500">To</dt><dd>{preview.sample.to.join(", ")} <span className="text-slate-400">(row {preview.sample.row_number})</span></dd></div>
                    <div className="flex gap-2"><dt className="w-16 text-slate-500">Subject</dt><dd className="font-semibold">{preview.sample.subject}</dd></div>
                  </dl>
                  <p className="whitespace-pre-wrap px-4 py-3">{preview.sample.body}</p>
                  <p className="border-t border-slate-100 px-4 py-2 text-xs text-slate-600">📎 {preview.sample.attachment}</p>
                </div>
              ) : (
                <p className="rounded-xl bg-slate-50 px-4 py-6 text-center text-sm text-slate-500 ring-1 ring-inset ring-slate-200">
                  {emailColumn ? "No student is ready to receive an e-mail." : "Select the e-mail column to see a preview."}
                </p>
              )}
            </div>
          </div>
          {previewError && <div className="mt-3"><Alert kind="error">{previewError}</Alert></div>}
        </section>

        {preview && (
          <section>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-sm font-semibold text-slate-900">3. Review recipients</h3>
              <div className="flex flex-wrap items-center gap-3 text-sm">
                {onlyIndices && (
                  <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs text-indigo-700 ring-1 ring-indigo-200">
                    Retrying {onlyIndices.length} e-mail(s) · <button type="button" className="underline" onClick={() => setOnlyIndices(null)}>show all</button>
                  </span>
                )}
                <label className="flex items-center gap-2">
                  <input type="checkbox" className="h-4 w-4 accent-indigo-600" checked={resend} disabled={sending} onChange={(e) => setResend(e.target.checked)} />
                  Also re-send to students already e-mailed
                </label>
                <select value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)} className="rounded-lg py-1.5 pl-3 pr-8 text-sm ring-1 ring-slate-300" aria-label="Filter recipients">
                  <option value="all">All rows</option>
                  {(Object.keys(STATUS_LABEL) as RecipientStatus[]).filter((s) => counts[s]).map((s) => (
                    <option key={s} value={s}>{STATUS_LABEL[s].text} ({counts[s]})</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-4">
              <Stat label="Will be sent" value={ready} tone="green" />
              <Stat label="Already sent" value={counts.already_sent ?? 0} tone="indigo" />
              <Stat label="Missing / invalid e-mail" value={(counts.no_email ?? 0) + (counts.invalid_email ?? 0)} tone={(counts.no_email ?? 0) + (counts.invalid_email ?? 0) ? "amber" : "slate"} />
              <Stat label="No certificate" value={counts.no_certificate ?? 0} />
            </div>
            <div className="max-h-80 overflow-auto rounded-lg ring-1 ring-slate-200">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <thead className="sticky top-0 bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <tr><th className="px-3 py-2">Row</th><th className="px-3 py-2">Student</th><th className="px-3 py-2">E-mail</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Note</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {shown.map((r) => (
                    <tr key={r.index}>
                      <td className="px-3 py-2 tabular-nums text-slate-500">{r.row_number}</td>
                      <td className="px-3 py-2 font-medium">{r.name || <span className="text-slate-400">(blank)</span>}</td>
                      <td className="px-3 py-2">{r.emails.join(", ") || <span className="text-slate-400">{r.raw_email || "—"}</span>}</td>
                      <td className="px-3 py-2"><span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_LABEL[r.status].cls}`}>{STATUS_LABEL[r.status].text}</span></td>
                      <td className="px-3 py-2 text-xs text-slate-600">{r.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {smtp && preview && (
          <section>
            <h3 className="mb-3 text-sm font-semibold text-slate-900">4. Send a test e-mail to yourself</h3>
            <div className="flex flex-wrap items-center gap-3">
              <input type="email" value={testTo} onChange={(e) => setTestTo(e.target.value)} className="w-72 rounded-lg px-3 py-2 text-sm ring-1 ring-slate-300" aria-label="Test address" />
              <Button variant="secondary" disabled={testState.busy || !testTo} onClick={sendTest}>{testState.busy && <Spinner />} Send test e-mail</Button>
            </div>
            {testState.message && <div className="mt-3"><Alert kind={testState.ok ? "success" : "error"}>{testState.message}</Alert></div>}
          </section>
        )}

        {smtp && preview && (
          <section>
            <h3 className="mb-3 text-sm font-semibold text-slate-900">5. Send to students</h3>
            {ready > preview.max_per_batch && (
              <div className="mb-3"><Alert kind="warning">{ready} e-mails exceed the batch limit of {preview.max_per_batch}. Use a smaller selection or raise EMAIL_MAX_PER_BATCH.</Alert></div>
            )}
            <div className="space-y-3 rounded-xl bg-amber-50 p-4 ring-1 ring-inset ring-amber-200">
              <label className="flex items-start gap-2 text-sm text-amber-950">
                <input type="checkbox" className="mt-0.5 h-4 w-4 accent-indigo-600" checked={authorized} disabled={sending} onChange={(e) => setAuthorized(e.target.checked)} />
                <span>I am authorised to e-mail these students, and I have checked the recipient list and the test e-mail.</span>
              </label>
              <label className="flex flex-wrap items-center gap-2 text-sm text-amber-950">
                To confirm, type the number of e-mails that will be sent (<strong>{ready}</strong>):
                <input inputMode="numeric" value={typedCount} disabled={sending} onChange={(e) => setTypedCount(e.target.value.replace(/\D/g, ""))} className="w-24 rounded-lg px-3 py-1.5 text-sm ring-1 ring-amber-300" aria-label="Confirm number of e-mails" />
              </label>
              <div className="flex flex-wrap items-center gap-3">
                <Button disabled={!authorized || !confirmOk || ready === 0 || sending || starting || ready > preview.max_per_batch} onClick={sendAll}>
                  {(sending || starting) && <Spinner />} Send {ready} e-mail{ready === 1 ? "" : "s"}
                </Button>
                {sending && sendJob && <Button variant="secondary" onClick={() => api.cancelEmailJob(sendJob.email_job_id).catch(onError)}>Stop sending</Button>}
                <span className="text-xs text-amber-900/80">Sent one at a time, about {info.delay_seconds}s apart, to respect provider limits.</span>
              </div>
            </div>

            {sendJob && (
              <div className="mt-4 space-y-3">
                <div className="flex justify-between text-sm">
                  <span className="font-medium">{sending ? "Sending…" : `Finished (${sendJob.status})`}</span>
                  <span className="tabular-nums text-slate-500">{sendJob.counts.sent} sent · {sendJob.counts.failed} failed · {sendJob.processed}/{sendJob.total}</span>
                </div>
                <div className="h-3 overflow-hidden rounded-full bg-slate-200" role="progressbar" aria-valuenow={sendJob.processed} aria-valuemax={sendJob.total}>
                  <div className="h-full bg-emerald-500 transition-all" style={{ width: `${sendJob.total ? (sendJob.processed / sendJob.total) * 100 : 0}%` }} />
                </div>
                {sendJob.error && <Alert kind="error" title="Sending stopped">{sendJob.error}</Alert>}
                {!sending && (
                  <div className="flex flex-wrap gap-3">
                    {sendJob.report_file && (
                      <a className="inline-flex items-center rounded-lg bg-white px-4 py-2 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50" href={api.fileUrl(job.job_id, sendJob.report_file)}>
                        Download e-mail report (CSV)
                      </a>
                    )}
                    {sendJob.counts.failed + sendJob.counts.cancelled > 0 && (
                      <Button variant="secondary" onClick={retryFailed}>Retry {sendJob.counts.failed + sendJob.counts.cancelled} unsent e-mail(s)</Button>
                    )}
                  </div>
                )}
                <div className="max-h-72 overflow-auto rounded-lg ring-1 ring-slate-200">
                  <table className="min-w-full divide-y divide-slate-200 text-sm">
                    <thead className="sticky top-0 bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                      <tr><th className="px-3 py-2">Row</th><th className="px-3 py-2">Student</th><th className="px-3 py-2">Sent to</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Details</th></tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {sendJob.results.filter((r) => r.status !== "skipped").map((r) => (
                        <tr key={r.index}>
                          <td className="px-3 py-2 tabular-nums text-slate-500">{r.row_number}</td>
                          <td className="px-3 py-2 font-medium">{r.name}</td>
                          <td className="px-3 py-2">{r.to.join(", ")}</td>
                          <td className="px-3 py-2"><span className={`rounded-full px-2 py-0.5 text-xs font-medium ${SEND_STYLE[r.status]}`}>{r.status}</span></td>
                          <td className="px-3 py-2 text-xs text-slate-600">{r.message}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </section>
        )}
      </div>
    </Card>
  );
}
