from __future__ import annotations

import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.fonts import FontRegistry
from app.main import create_app
from conftest import student_rows

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(storage_dir=tmp_path / "storage", max_workers=4), FontRegistry(include_system=False))
    with TestClient(app) as test_client:
        yield test_client


def name_style(**kw):
    data = {"box": {"x": 100, "y": 300, "width": 1000, "height": 150}, "font_id": "builtin:default",
            "font_size": 72, "min_font_size": 28, "color": "#222244", "align": "center"}
    data.update(kw)
    return data


def cfg(**kw):
    data = {"mapping": {"name_column": "Student Name", "department_column": "Department", "email_column": "Email Address"},
            "name": name_style()}
    data.update(kw)
    return data


def setup_session(client, make_xlsx, template_png, rows=None):
    session_id = client.post("/api/sessions").json()["session_id"]
    with open(make_xlsx(rows or student_rows(100)), "rb") as fh:
        r = client.post("/api/upload-excel", data={"session_id": session_id}, files={"file": ("students.xlsx", fh, XLSX)})
    assert r.status_code == 200, r.text
    with open(template_png, "rb") as fh:
        r = client.post("/api/upload-template", data={"session_id": session_id}, files={"file": ("cert.png", fh, "image/png")})
    assert r.status_code == 200, r.text
    return session_id


def wait_for(client, job_id, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/api/jobs/{job_id}").json()
        if status["status"] not in ("queued", "running"):
            return status
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def test_full_workflow_100_students(client, make_xlsx, template_png):
    session_id = client.post("/api/sessions").json()["session_id"]
    with open(make_xlsx(student_rows(100)), "rb") as fh:
        excel = client.post("/api/upload-excel", data={"session_id": session_id},
                            files={"file": ("students.xlsx", fh, XLSX)}).json()
    assert excel["total_records"] == 100
    assert excel["detected_mapping"]["name_column"] == "Student Name"
    assert excel["analysis"]["valid_names"] == 100

    with open(template_png, "rb") as fh:
        template = client.post("/api/upload-template", data={"session_id": session_id},
                               files={"file": ("cert.png", fh, "image/png")}).json()
    assert (template["width"], template["height"]) == (1200, 800)
    served = client.get(f"/api/template/{session_id}")
    assert served.content == template_png.read_bytes()   # the exact uploaded file is served back

    fonts = client.get("/api/fonts", params={"session_id": session_id}).json()
    assert any(f["id"] == "builtin:default" for f in fonts["fonts"])

    preview = client.post("/api/preview-certificate", json={"session_id": session_id, "record_index": 4, "config": cfg(),
                                                             "max_width": 600}).json()
    assert preview["image"].startswith("data:image/jpeg;base64,")
    assert preview["record"] == {"index": 4, "row_number": 6, "name": excel["records"][4]["values"]["Student Name"]}
    assert preview["preview_width"] == 600 and preview["width"] == 1200
    assert preview["name_layout"]["fits"]

    check = client.post("/api/validate-generation", json={"session_id": session_id, "config": cfg()}).json()
    assert check["will_generate"] == 100

    denied = client.post("/api/generate-certificates", json={"session_id": session_id, "config": cfg(), "approved": False})
    assert denied.status_code == 400

    started = client.post("/api/generate-certificates", json={
        "session_id": session_id, "config": cfg(), "approved": True, "formats": {"png": True, "pdf": True}})
    assert started.status_code == 202
    status = wait_for(client, started.json()["job_id"])
    assert status["status"] == "completed"
    assert status["counts"]["generated"] == 100 and status["processed"] == 100

    zipped = client.get(f"/api/download-zip/{status['job_id']}")
    assert zipped.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zipped.content)) as zf:
        assert len([n for n in zf.namelist() if n.endswith(".png") and "/" not in n]) == 100
        assert len([n for n in zf.namelist() if n.startswith("pdf/")]) == 100

    first = status["results"][0]
    single = client.get(f"/api/jobs/{status['job_id']}/files/{first['png']}")
    assert single.status_code == 200 and single.content.startswith(b"\x89PNG")
    assert client.get(f"/api/jobs/{status['job_id']}/files/{first['pdf']}").content.startswith(b"%PDF")

    assert client.delete(f"/api/sessions/{session_id}").status_code == 200
    assert client.get(f"/api/jobs/{status['job_id']}").status_code == 404


def test_rejects_invalid_uploads(client, tmp_path):
    session_id = client.post("/api/sessions").json()["session_id"]
    r = client.post("/api/upload-excel", data={"session_id": session_id}, files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 415
    r = client.post("/api/upload-excel", data={"session_id": session_id}, files={"file": ("fake.xlsx", b"not excel", XLSX)})
    assert r.status_code == 422
    r = client.post("/api/upload-template", data={"session_id": session_id}, files={"file": ("cert.png", b"GIF89a....", "image/png")})
    assert r.status_code == 415
    r = client.post("/api/upload-template", data={"session_id": session_id}, files={"file": ("cert.jpg", b"\xff\xd8\xff", "image/jpeg")})
    assert r.status_code == 415
    r = client.post("/api/upload-excel", data={"session_id": "0" * 32}, files={"file": ("a.xlsx", b"PK", XLSX)})
    assert r.status_code == 404


def test_file_download_cannot_escape_job_folder(client, make_xlsx, template_png):
    session_id = setup_session(client, make_xlsx, template_png, student_rows(2))
    job_id = client.post("/api/generate-certificates", json={"session_id": session_id, "config": cfg(), "approved": True}).json()["job_id"]
    wait_for(client, job_id)
    for bad in ["..%2F..%2Ftemplate.png", "..\\..\\template.png", "%2e%2e%2fstudents.xlsx", "template.png"]:
        assert client.get(f"/api/jobs/{job_id}/files/{bad}").status_code == 404
    assert client.get("/api/download-zip/../../etc").status_code == 404
    assert client.get("/api/jobs/not-a-valid-id").status_code == 404


def test_preview_errors_are_clear(client, make_xlsx, template_png):
    rows = [["Student Name", "Department", "Email Address"], ["Asha", "CSE", "a@x.io"], [None, "EEE", "b@x.io"]]
    session_id = setup_session(client, make_xlsx, template_png, rows)
    blank = client.post("/api/preview-certificate", json={"session_id": session_id, "record_index": 1, "config": cfg()})
    assert blank.status_code == 422 and "row 3" in blank.json()["detail"]

    outside = cfg(name=name_style(box={"x": 900, "y": 300, "width": 600, "height": 100}))
    r = client.post("/api/preview-certificate", json={"session_id": session_id, "record_index": 0, "config": outside})
    assert r.status_code == 422 and "beyond the template" in r.json()["detail"]

    bad_font = cfg(name=name_style(font_id="no-such-font"))
    r = client.post("/api/preview-certificate", json={"session_id": session_id, "record_index": 0, "config": bad_font})
    assert r.status_code == 422 and "Unknown font" in r.json()["detail"]

    check = client.post("/api/validate-generation", json={"session_id": session_id, "config": cfg()}).json()
    assert check["analysis"]["blank_name_rows"] == [3]
    assert check["will_generate"] == 1


def test_works_when_paths_exceed_windows_260_character_limit(tmp_path, make_xlsx, template_png):
    # A deep install folder plus a long student name: certificate paths are well over 260 characters.
    deep = tmp_path / ("install folder " * 4).strip() / ("certificate-name-autofiller-main " * 3).strip() / ("x" * 60)
    long_name = "Venkata Lakshmi Narasimha Subrahmanya Sharma Venkataraman Iyer"
    app = create_app(Settings(storage_dir=deep / "backend" / "storage"), FontRegistry(include_system=False))
    with TestClient(app) as client:
        rows = [["Student Name", "Email Address"], [long_name, "v@example.edu"]]
        session_id = setup_session(client, make_xlsx, template_png, rows)
        started = client.post("/api/generate-certificates", json={
            "session_id": session_id, "config": cfg(mapping={"name_column": "Student Name"}), "approved": True,
            "formats": {"png": True, "pdf": True}})
        status = wait_for(client, started.json()["job_id"])
        result = status["results"][0]
        assert status["counts"]["generated"] == 1, result["message"]
        store = app.state.store
        job = store.get_job(status["job_id"])
        assert len(str(job.files[result["png"]]).removeprefix("\\\\?\\")) > 260 or len(str(deep)) < 200
        assert client.get(f"/api/jobs/{status['job_id']}/files/{result['png']}").content.startswith(b"\x89PNG")
        with zipfile.ZipFile(io.BytesIO(client.get(f"/api/download-zip/{status['job_id']}").content)) as zf:
            assert result["png"] in zf.namelist()
        from app.mailer import certificate_pdf
        pdf, _ = certificate_pdf(job, next(r for r in job.results))
        assert pdf.startswith(b"%PDF")
        assert client.delete(f"/api/sessions/{session_id}").status_code == 200


def test_reparse_with_manual_header_row(client, make_xlsx, template_png):
    rows = [["Batch 2026"], ["Full Name", "Branch"], ["Asha", "CSE"]]
    session_id = setup_session(client, make_xlsx, template_png, rows)
    r = client.post("/api/reparse-excel", json={"session_id": session_id, "header_row": "none"}).json()
    assert r["columns"] == ["Column A", "Column B"] and r["total_records"] == 3
    r = client.post("/api/reparse-excel", json={"session_id": session_id, "header_row": "auto"}).json()
    assert r["header_row"] == 2 and r["detected_mapping"]["name_column"] == "Full Name"
