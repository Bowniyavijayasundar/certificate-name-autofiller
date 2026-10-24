import { useState } from "react";
import { api, ApiError } from "../api";
import type { EmailConfigInfo, Security, SmtpPublic } from "../types";
import { Alert, Button, Spinner } from "./ui";

interface Props {
  sessionId: string;
  info: EmailConfigInfo;
  current: SmtpPublic | null;
  onConnected: (settings: SmtpPublic | null) => void;
  onError: (err: unknown) => void;
}

const inputCls = "w-full rounded-lg px-3 py-2 text-sm ring-1 ring-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-500";

export function EmailConnect({ sessionId, info, current, onConnected, onError }: Props) {
  const [editing, setEditing] = useState(!current);
  const [preset, setPreset] = useState("gmail");
  const [fromEmail, setFromEmail] = useState(current?.from_email ?? "");
  const [fromName, setFromName] = useState(current?.from_name ?? "");
  const [password, setPassword] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");
  const [security, setSecurity] = useState<Security | "">("");
  const [username, setUsername] = useState("");
  const [replyTo, setReplyTo] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const p = info.presets[preset] ?? info.presets.custom;

  async function connect(useServer = false) {
    setBusy(true);
    setProblem(null);
    try {
      const settings = await api.connectEmail(
        useServer
          ? { session_id: sessionId, use_server_config: true }
          : {
              session_id: sessionId, preset, from_email: fromEmail, from_name: fromName, password, reply_to: replyTo,
              host: host || undefined, port: port ? Number(port) : null, security: security || null, username,
            },
      );
      setPassword("");
      setEditing(false);
      onConnected(settings);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 422 || err.status === 409)) setProblem(err.message);
      else onError(err);
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    await api.forgetEmail(sessionId).catch(onError);
    onConnected(null);
    setEditing(true);
  }

  if (current && !editing) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-emerald-50 px-4 py-3 ring-1 ring-inset ring-emerald-200">
        <div className="text-sm text-emerald-900">
          <p className="font-semibold">Connected and verified</p>
          <p>
            Sending as <strong>{current.from_name ? `${current.from_name} <${current.from_email}>` : current.from_email}</strong> via {current.host}:{current.port}
            {current.source === "server" && " (server account)"}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => setEditing(true)}>Change</Button>
          <Button variant="ghost" onClick={disconnect}>Disconnect</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {info.server_config && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-slate-50 px-4 py-3 text-sm ring-1 ring-inset ring-slate-200">
          <span>The server has an e-mail account configured: <strong>{info.server_config.from_email}</strong></span>
          <Button variant="secondary" disabled={busy} onClick={() => connect(true)}>Use server account</Button>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm md:col-span-2">
          <span className="font-medium text-slate-700">E-mail provider</span>
          <select className={inputCls} value={preset} onChange={(e) => setPreset(e.target.value)}>
            {Object.entries(info.presets).map(([key, value]) => (
              <option key={key} value={key}>{value.label}</option>
            ))}
          </select>
          <span className="text-xs text-slate-500">{p.help}</span>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-slate-700">Your e-mail address (sender)</span>
          <input className={inputCls} type="email" autoComplete="email" value={fromEmail} onChange={(e) => setFromEmail(e.target.value)} placeholder="examcell@yourcollege.edu" />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-slate-700">{preset === "gmail" || preset === "yahoo" ? "App password" : "Password"}</span>
          <input
            className={inputCls}
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={current?.password_set ? "(unchanged)" : preset === "gmail" ? "16-character app password" : ""}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm md:col-span-2">
          <span className="font-medium text-slate-700">Sender name <span className="text-slate-400">(shown to students)</span></span>
          <input className={inputCls} value={fromName} onChange={(e) => setFromName(e.target.value)} placeholder="e.g. Department of Computer Science" />
        </label>
      </div>

      <button type="button" className="text-sm font-medium text-indigo-700 hover:underline" onClick={() => setAdvanced(!advanced)}>
        {advanced ? "Hide" : "Show"} advanced settings
      </button>
      {advanced && (
        <div className="grid gap-4 rounded-xl bg-slate-50 p-4 ring-1 ring-inset ring-slate-200 md:grid-cols-4">
          <label className="flex flex-col gap-1 text-sm md:col-span-2">
            <span className="text-xs font-medium text-slate-600">SMTP host</span>
            <input className={inputCls} value={host} onChange={(e) => setHost(e.target.value)} placeholder={p.host || "smtp.example.edu"} />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs font-medium text-slate-600">Port</span>
            <input className={inputCls} inputMode="numeric" value={port} onChange={(e) => setPort(e.target.value.replace(/\D/g, ""))} placeholder={String(p.port)} />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs font-medium text-slate-600">Security</span>
            <select className={inputCls} value={security} onChange={(e) => setSecurity(e.target.value as Security | "")}>
              <option value="">Default ({p.security.toUpperCase()})</option>
              <option value="ssl">SSL/TLS</option>
              <option value="starttls">STARTTLS</option>
              <option value="none">None (local relay only)</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm md:col-span-2">
            <span className="text-xs font-medium text-slate-600">Login username (if different from the address)</span>
            <input className={inputCls} value={username} onChange={(e) => setUsername(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-sm md:col-span-2">
            <span className="text-xs font-medium text-slate-600">Reply-to address (optional)</span>
            <input className={inputCls} type="email" value={replyTo} onChange={(e) => setReplyTo(e.target.value)} />
          </label>
        </div>
      )}

      {problem && <Alert kind="error" title="Could not connect">{problem}</Alert>}
      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={busy || !fromEmail} onClick={() => connect(false)}>
          {busy && <Spinner />} Connect &amp; verify
        </Button>
        {current && <Button variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>}
        <span className="text-xs text-slate-500">
          The password is only kept in the server's memory for this session. It is never saved to disk or shown again.
        </span>
      </div>
    </div>
  );
}
