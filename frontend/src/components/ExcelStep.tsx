import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { ColumnMapping, ExcelData, RecordAnalysis } from "../types";
import { Alert, Button, Card, Dropzone, Stat, rowList } from "./ui";

const MAX_MB = 10;
const PAGE_SIZE = 25;

interface Props {
  sessionId: string;
  excel: ExcelData | null;
  mapping: ColumnMapping;
  onExcel: (data: ExcelData) => void;
  onMapping: (mapping: ColumnMapping) => void;
  onError: (err: unknown) => void;
  onNext: () => void;
}

export function ExcelStep({ sessionId, excel, mapping, onExcel, onMapping, onError, onNext }: Props) {
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<RecordAnalysis | null>(excel?.analysis ?? null);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);

  async function upload(file: File) {
    setLocalError(null);
    if (!/\.(xlsx|xls)$/i.test(file.name)) return setLocalError("Please choose an Excel file (.xlsx or .xls).");
    if (file.size > MAX_MB * 1024 * 1024) return setLocalError(`The file is larger than ${MAX_MB} MB.`);
    setBusy(true);
    try {
      onExcel(await api.uploadExcel(sessionId, file));
      setPage(0);
    } catch (err) {
      onError(err);
    } finally {
      setBusy(false);
    }
  }

  async function reparse(sheet: string, headerRow: string) {
    setBusy(true);
    try {
      onExcel(await api.reparseExcel(sessionId, sheet, headerRow));
      setPage(0);
    } catch (err) {
      onError(err);
    } finally {
      setBusy(false);
    }
  }

  // Re-run the server-side checks whenever the column mapping changes.
  useEffect(() => {
    if (!excel || !mapping.name_column) {
      setAnalysis(null);
      return;
    }
    let cancelled = false;
    api
      .analyze(sessionId, mapping)
      .then((a) => !cancelled && setAnalysis(a))
      .catch(onError);
    return () => {
      cancelled = true;
    };
  }, [excel, mapping.name_column, mapping.department_column, mapping.email_column, sessionId]);

  const blankRows = useMemo(() => new Set(analysis?.blank_name_rows ?? []), [analysis]);
  const duplicateRows = useMemo(() => new Set(analysis?.duplicate_groups.flatMap((g) => g.rows) ?? []), [analysis]);

  const shownColumns = useMemo(() => {
    if (!excel) return [];
    const picked = [mapping.name_column, mapping.department_column, mapping.email_column].filter(Boolean) as string[];
    return picked.length ? picked : excel.columns.slice(0, 4);
  }, [excel, mapping]);

  const filtered = useMemo(() => {
    if (!excel) return [];
    const q = query.trim().toLocaleLowerCase();
    if (!q) return excel.records;
    return excel.records.filter((r) => Object.values(r.values).some((v) => v.toLocaleLowerCase().includes(q)));
  }, [excel, query]);

  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const visible = filtered.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);

  const columnSelect = (label: string, field: keyof ColumnMapping, required = false) => (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium text-slate-700">
        {label} {required ? <span className="text-rose-600">*</span> : <span className="text-slate-400">(optional)</span>}
      </span>
      <select
        className="rounded-lg border-slate-300 py-2 pl-3 pr-8 text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-indigo-500"
        value={mapping[field] ?? ""}
        onChange={(e) => onMapping({ ...mapping, [field]: e.target.value || null })}
      >
        <option value="">{required ? "— Select column —" : "— None —"}</option>
        {excel!.columns.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <div className="space-y-6">
      <Card title="Upload the student Excel sheet">
        <Dropzone
          accept=".xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
          title={excel ? "Drop a different Excel file to replace it" : "Drag & drop your Excel file here, or click to browse"}
          hint={`.xlsx or .xls · up to ${MAX_MB} MB · columns such as Student Name, Department, Email Address`}
          busy={busy}
          onFile={upload}
        />
        {localError && <div className="mt-3"><Alert kind="error">{localError}</Alert></div>}
      </Card>

      {excel && (
        <>
          <Card title={`File: ${excel.filename}`}>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-slate-700">Sheet</span>
                <select
                  className="rounded-lg py-2 pl-3 pr-8 text-sm ring-1 ring-slate-300"
                  value={excel.sheet}
                  disabled={busy}
                  onChange={(e) => reparse(e.target.value, "auto")}
                >
                  {excel.sheets.map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-slate-700">Header row</span>
                <select
                  className="rounded-lg py-2 pl-3 pr-8 text-sm ring-1 ring-slate-300"
                  value={excel.header_row === null ? "none" : String(excel.header_row)}
                  disabled={busy}
                  onChange={(e) => reparse(excel.sheet, e.target.value)}
                >
                  <option value="none">No header row</option>
                  {Array.from({ length: Math.max(10, excel.header_row ?? 0) }, (_, i) => (
                    <option key={i} value={String(i + 1)}>
                      Row {i + 1}
                    </option>
                  ))}
                </select>
              </label>
              {columnSelect("Name column", "name_column", true)}
              {columnSelect("Department column", "department_column")}
              {columnSelect("Email column", "email_column")}
            </div>

            {!mapping.name_column && (
              <div className="mt-4">
                <Alert kind="warning" title="Name column not detected">
                  Pick the column that contains the student names. If the headers are on a different row, change “Header row”.
                </Alert>
              </div>
            )}

            {analysis && (
              <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-4">
                <Stat label="Rows read" value={analysis.total_rows} />
                <Stat label="Valid names" value={analysis.valid_names} tone="green" />
                <Stat label="Blank names" value={analysis.blank_name_rows.length} tone={analysis.blank_name_rows.length ? "red" : "slate"} />
                <Stat label="Duplicate names" value={analysis.duplicate_groups.length} tone={analysis.duplicate_groups.length ? "amber" : "slate"} />
              </div>
            )}

            <div className="mt-4 space-y-2">
              {analysis && analysis.blank_name_rows.length > 0 && (
                <Alert kind="error" title={`${analysis.blank_name_rows.length} row(s) have a blank name and will be skipped`}>
                  Excel rows: {rowList(analysis.blank_name_rows)}. Fill them in and re-upload, or continue without them.
                </Alert>
              )}
              {analysis && analysis.duplicate_groups.length > 0 && (
                <Alert kind="warning" title="Duplicate names found">
                  Each row still gets its own certificate (files are numbered _2, _3…).{" "}
                  {analysis.duplicate_groups.slice(0, 5).map((g) => `“${g.name}” (rows ${g.rows.join(", ")})`).join("; ")}
                  {analysis.duplicate_groups.length > 5 && " …"}
                </Alert>
              )}
              {analysis && analysis.invalid_email_rows.length > 0 && (
                <Alert kind="info">Emails that look invalid in rows {rowList(analysis.invalid_email_rows)}. This doesn't affect certificates.</Alert>
              )}
              {excel.ignored_empty_rows > 0 && (
                <Alert kind="info">{excel.ignored_empty_rows} completely empty row(s) between records were ignored.</Alert>
              )}
            </div>
          </Card>

          <Card
            title={`Students (${excel.total_records})`}
            actions={
              <input
                type="search"
                placeholder="Search…"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setPage(0);
                }}
                className="w-56 rounded-lg px-3 py-1.5 text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-indigo-500"
              />
            }
          >
            <div className="overflow-x-auto rounded-lg ring-1 ring-slate-200">
              <table className="min-w-full divide-y divide-slate-200 text-sm">
                <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-3 py-2">Row</th>
                    {shownColumns.map((c) => (
                      <th key={c} className="px-3 py-2">
                        {c}
                        {c === mapping.name_column && <span className="ml-1 rounded bg-indigo-100 px-1.5 py-0.5 text-[10px] text-indigo-700">NAME</span>}
                      </th>
                    ))}
                    <th className="px-3 py-2">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {visible.map((r) => {
                    const blank = blankRows.has(r.row_number);
                    const dup = duplicateRows.has(r.row_number);
                    return (
                      <tr key={r.index} className={blank ? "bg-rose-50" : dup ? "bg-amber-50/60" : ""}>
                        <td className="px-3 py-2 tabular-nums text-slate-500">{r.row_number}</td>
                        {shownColumns.map((c) => (
                          <td key={c} className="max-w-xs truncate px-3 py-2" title={r.values[c]}>
                            {r.values[c] || <span className="text-slate-400">—</span>}
                          </td>
                        ))}
                        <td className="px-3 py-2 text-xs">
                          {!mapping.name_column ? null : blank ? (
                            <span className="font-medium text-rose-700">Blank name · skipped</span>
                          ) : dup ? (
                            <span className="font-medium text-amber-700">Duplicate</span>
                          ) : (
                            <span className="text-emerald-700">OK</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                  {visible.length === 0 && (
                    <tr>
                      <td colSpan={shownColumns.length + 2} className="px-3 py-6 text-center text-slate-500">
                        No matching rows.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="mt-3 flex items-center justify-between text-sm text-slate-600">
              <span>
                {filtered.length} row(s){query && " match"} · page {page + 1} of {pages}
              </span>
              <div className="flex gap-2">
                <Button variant="secondary" disabled={page === 0} onClick={() => setPage(page - 1)}>
                  Previous
                </Button>
                <Button variant="secondary" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>
                  Next
                </Button>
              </div>
            </div>
          </Card>

          <div className="flex justify-end">
            <Button disabled={!mapping.name_column || !analysis || analysis.valid_names === 0} onClick={onNext}>
              Continue: upload certificate →
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
