import type {
  CertificateConfig, ColumnMapping, EmailConfigInfo, EmailJobStatus, EmailPreview, ExcelData, FontInfo, JobStatus,
  PreviewResult, RecordAnalysis, Security, SmtpPublic, TemplateInfo, ValidationResult,
} from "./types";

const BASE = "/api";

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

function describe(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{loc, msg}, ...]
    return detail
      .map((d) => {
        const loc = Array.isArray(d?.loc) ? d.loc.filter((p: unknown) => p !== "body").join(" → ") : "";
        return loc ? `${loc}: ${d?.msg}` : String(d?.msg ?? d);
      })
      .join("; ");
  }
  return "Unexpected error";
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(BASE + path, init);
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError("Cannot reach the backend server. Is it running on port 8000?", 0);
  }
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      message = describe((await response.json()).detail) || message;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(message, response.status);
  }
  return response.json() as Promise<T>;
}

const json = (body: unknown, signal?: AbortSignal): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
  signal,
});

function form(fields: Record<string, string | Blob | undefined>): RequestInit {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) if (value !== undefined) data.append(key, value);
  return { method: "POST", body: data };
}

export const api = {
  createSession: () => request<{ session_id: string; retention_minutes: number }>("/sessions", { method: "POST" }),
  deleteSession: (sessionId: string) => request(`/sessions/${sessionId}`, { method: "DELETE" }),

  uploadExcel: (sessionId: string, file: File) =>
    request<ExcelData>("/upload-excel", form({ session_id: sessionId, file })),
  reparseExcel: (sessionId: string, sheet: string, headerRow: string) =>
    request<ExcelData>("/reparse-excel", json({ session_id: sessionId, sheet, header_row: headerRow })),
  analyze: (sessionId: string, mapping: ColumnMapping) =>
    request<RecordAnalysis>("/analyze-records", json({ session_id: sessionId, mapping })),

  uploadTemplate: (sessionId: string, file: File) =>
    request<TemplateInfo>("/upload-template", form({ session_id: sessionId, file })),
  templateUrl: (sessionId: string, version: number) => `${BASE}/template/${sessionId}?v=${version}`,

  fonts: (sessionId: string) =>
    request<{ fonts: FontInfo[]; default_font_id: string }>(`/fonts?session_id=${sessionId}`),
  uploadFont: (sessionId: string, file: File) => request<FontInfo>("/upload-font", form({ session_id: sessionId, file })),
  fontFileUrl: (sessionId: string, fontId: string) =>
    `${BASE}/fonts/${encodeURIComponent(fontId)}/file?session_id=${sessionId}`,

  preview: (sessionId: string, recordIndex: number, config: CertificateConfig, maxWidth: number, signal?: AbortSignal) =>
    request<PreviewResult>(
      "/preview-certificate",
      json({ session_id: sessionId, record_index: recordIndex, config, max_width: maxWidth }, signal),
    ),
  validate: (sessionId: string, config: CertificateConfig) =>
    request<ValidationResult>("/validate-generation", json({ session_id: sessionId, config })),

  generate: (sessionId: string, config: CertificateConfig, formats: { png: boolean; pdf: boolean }) =>
    request<{ job_id: string; total: number }>(
      "/generate-certificates",
      json({ session_id: sessionId, config, formats, approved: true }),
    ),
  job: (jobId: string) => request<JobStatus>(`/jobs/${jobId}`),
  cancelJob: (jobId: string) => request(`/jobs/${jobId}/cancel`, { method: "POST" }),
  fileUrl: (jobId: string, fileName: string) => `${BASE}/jobs/${jobId}/files/${encodeURIComponent(fileName)}`,
  zipUrl: (jobId: string) => `${BASE}/download-zip/${jobId}`,

  emailConfig: (sessionId: string) => request<EmailConfigInfo>(`/email/config?session_id=${sessionId}`),
  connectEmail: (body: SmtpConnectBody) => request<SmtpPublic>("/email/config", json(body)),
  forgetEmail: (sessionId: string) => request(`/email/config?session_id=${sessionId}`, { method: "DELETE" }),
  emailPreview: (body: EmailComposeBody & { resend: boolean; only_indices: number[] | null }, signal?: AbortSignal) =>
    request<EmailPreview>("/email/preview", json(body, signal)),
  emailTest: (body: EmailComposeBody & { to: string }) =>
    request<{ sent_to: string; row_number: number; attachment: string }>("/email/test", json(body)),
  emailSend: (body: EmailComposeBody & { resend: boolean; only_indices: number[] | null; authorized: boolean; confirm_count: number }) =>
    request<{ email_job_id: string; to_send: number }>("/email/send", json(body)),
  emailJob: (emailJobId: string) => request<EmailJobStatus>(`/email/jobs/${emailJobId}`),
  cancelEmailJob: (emailJobId: string) => request(`/email/jobs/${emailJobId}/cancel`, { method: "POST" }),
};

export interface SmtpConnectBody {
  session_id: string;
  use_server_config?: boolean;
  preset?: string;
  host?: string;
  port?: number | null;
  security?: Security | null;
  username?: string;
  password?: string;
  from_email?: string;
  from_name?: string;
  reply_to?: string;
}

export interface EmailComposeBody {
  session_id: string;
  job_id: string;
  email_column: string;
  subject: string;
  body: string;
}
