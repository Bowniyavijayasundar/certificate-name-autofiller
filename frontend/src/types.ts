export interface ColumnMapping {
  name_column: string | null;
  department_column: string | null;
  email_column: string | null;
}

export interface StudentRecord {
  index: number;
  row_number: number;
  values: Record<string, string>;
}

export interface RecordAnalysis {
  total_rows: number;
  valid_names: number;
  blank_name_rows: number[];
  duplicate_groups: { name: string; rows: number[] }[];
  invalid_email_rows: number[];
  blank_department_rows: number[];
}

export interface ExcelData {
  filename: string;
  sheets: string[];
  sheet: string;
  header_row: number | null;
  columns: string[];
  detected_mapping: ColumnMapping;
  records: StudentRecord[];
  total_records: number;
  ignored_empty_rows: number;
  analysis: RecordAnalysis | null;
}

export interface TemplateInfo {
  filename: string;
  width: number;
  height: number;
  mode: string;
  dpi: number[] | null;
  file_size: number;
}

export interface FontInfo {
  id: string;
  name: string;
  category: string;
  source: "bundled" | "system" | "uploaded" | "builtin";
  variation: string | null;
  has_file: boolean;
}

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

export type Align = "left" | "center" | "right";
export type VAlign = "top" | "middle" | "bottom";

export interface TextStyle {
  box: Box;
  font_id: string;
  font_size: number;
  min_font_size: number;
  color: string;
  align: Align;
  vertical_align: VAlign;
  allow_wrap: boolean;
  max_lines: number;
  line_spacing: number;
}

export interface CertificateConfig {
  mapping: { name_column: string; department_column: string | null; email_column: string | null };
  name: TextStyle;
  department_enabled: boolean;
  department: TextStyle | null;
}

export interface LayoutInfo {
  font_size: number;
  lines: string[];
  fits: boolean;
  shrunk: boolean;
  wrapped: boolean;
  extent: number[];
}

export interface PreviewResult {
  image: string;
  width: number;
  height: number;
  preview_width: number;
  preview_height: number;
  record: { index: number; row_number: number; name: string };
  name_layout: LayoutInfo;
  department_layout: LayoutInfo | null;
  error: string | null;
  warnings: string[];
}

export interface FitEntry {
  row: number;
  text: string;
  font_size: number;
}

export interface ValidationResult {
  total_rows: number;
  will_generate: number;
  analysis: RecordAnalysis;
  fit: {
    shrunk: FitEntry[];
    wrapped: FitEntry[];
    overflow: FitEntry[];
    clipped: FitEntry[];
    department_issues: FitEntry[];
    shaping: FitEntry[];
  };
}

export type ResultStatus = "pending" | "generated" | "skipped" | "failed" | "cancelled";

export interface CertificateResult {
  index: number;
  row_number: number;
  name: string;
  department: string;
  status: ResultStatus;
  message: string;
  warnings: string[];
  png: string | null;
  pdf: string | null;
  font_size: number | null;
  lines: number | null;
}

export type Security = "ssl" | "starttls" | "none";

export interface SmtpPublic {
  host: string;
  port: number;
  security: Security;
  username: string;
  from_email: string;
  from_name: string;
  reply_to: string;
  password_set: boolean;
  source: "session" | "server";
}

export interface EmailConfigInfo {
  presets: Record<string, { label: string; host: string; port: number; security: Security; help: string }>;
  server_config: SmtpPublic | null;
  current: SmtpPublic | null;
  default_subject: string;
  default_body: string;
  placeholders: string[];
  delay_seconds: number;
  max_per_batch: number;
}

export type RecipientStatus = "ready" | "no_email" | "invalid_email" | "no_certificate" | "already_sent" | "not_selected";

export interface Recipient {
  index: number;
  row_number: number;
  name: string;
  emails: string[];
  raw_email: string;
  status: RecipientStatus;
  reason: string;
}

export interface EmailPreview {
  counts: Partial<Record<RecipientStatus, number>>;
  recipients: Recipient[];
  sample: { row_number: number; to: string[]; attachment: string; subject: string; body: string } | null;
  max_per_batch: number;
}

export type EmailResultStatus = "pending" | "sent" | "failed" | "skipped" | "cancelled";

export interface EmailJobStatus {
  email_job_id: string;
  job_id: string;
  status: "queued" | "running" | "completed" | "cancelled" | "failed";
  total: number;
  processed: number;
  counts: Record<EmailResultStatus, number>;
  error: string | null;
  report_file: string | null;
  elapsed_seconds: number;
  results: { index: number; row_number: number; name: string; to: string[]; status: EmailResultStatus; message: string; sent_at: number | null }[];
}

export interface JobStatus {
  job_id: string;
  status: "queued" | "running" | "completed" | "cancelled" | "failed";
  total: number;
  processed: number;
  counts: Record<ResultStatus, number>;
  with_warnings: number;
  formats: { png: boolean; pdf: boolean };
  zip_available: boolean;
  emails_sent: number;
  error: string | null;
  elapsed_seconds: number;
  results?: CertificateResult[];
}
