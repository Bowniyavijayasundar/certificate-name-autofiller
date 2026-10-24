from __future__ import annotations

import smtplib
import time

import pytest
from fastapi.testclient import TestClient

from app import mailer
from app.config import Settings
from app.excel_parser import parse_email_list
from app.fonts import FontRegistry
from app.main import create_app
from app.mailer import render_template

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SECRET = "app-password-123"

ROWS = [
    ["Student Name", "Department", "Email Address"],
    ["Asha Rao", "CSE", "asha@example.edu"],                 # row 2 ready
    ["Ben Okafor", "ECE", ""],                               # row 3 no e-mail
    ["Chloé Martin", "IT", "not-an-email"],                  # row 4 invalid
    [None, "EEE", "blank.name@example.edu"],                 # row 5 no certificate (blank name)
    ["Dev Patel", "MECH", "dev@example.edu; dev.p@example.org"],  # row 6 two addresses
    ["Esha Rao", "CSE", "ASHA@example.edu"],                 # row 7 same address as row 2
]


class FakeSMTP:
    sent: list = []
    fail_login = False
    refuse: set = set()
    connections = 0

    def __init__(self, host, port, timeout=None, context=None):
        FakeSMTP.connections += 1
        self.host, self.port = host, port

    def ehlo(self):
        pass

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        if FakeSMTP.fail_login or password != SECRET:
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")

    def send_message(self, msg):
        to = [a.strip() for a in msg["To"].split(",")]
        if any(a in FakeSMTP.refuse for a in to):
            raise smtplib.SMTPRecipientsRefused({to[0]: (550, b"No such user")})
        FakeSMTP.sent.append(msg)

    def quit(self):
        pass

    def close(self):
        pass


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    FakeSMTP.sent, FakeSMTP.fail_login, FakeSMTP.refuse, FakeSMTP.connections = [], False, set(), 0
    monkeypatch.setattr(mailer, "SMTP_CLASS", FakeSMTP)
    monkeypatch.setattr(mailer, "SMTP_SSL_CLASS", FakeSMTP)


def make_client(tmp_path, delay=0.0):
    app = create_app(Settings(storage_dir=tmp_path / "storage", email_delay_seconds=delay),
                     FontRegistry(include_system=False))
    return TestClient(app)


def generated_job(client, make_xlsx, template_png, rows=ROWS, pdf=False):
    sid = client.post("/api/sessions").json()["session_id"]
    with open(make_xlsx(rows), "rb") as fh:
        assert client.post("/api/upload-excel", data={"session_id": sid}, files={"file": ("s.xlsx", fh, XLSX)}).status_code == 200
    with open(template_png, "rb") as fh:
        assert client.post("/api/upload-template", data={"session_id": sid}, files={"file": ("t.png", fh, "image/png")}).status_code == 200
    config = {"mapping": {"name_column": "Student Name", "department_column": "Department", "email_column": "Email Address"},
              "name": {"box": {"x": 100, "y": 300, "width": 1000, "height": 150}, "font_id": "builtin:default",
                       "font_size": 72, "min_font_size": 28, "color": "#222244"}}
    job_id = client.post("/api/generate-certificates", json={"session_id": sid, "config": config, "approved": True,
                                                              "formats": {"png": True, "pdf": pdf}}).json()["job_id"]
    for _ in range(200):
        status = client.get(f"/api/jobs/{job_id}").json()
        if status["status"] == "completed":
            return sid, job_id, status
        time.sleep(0.05)
    raise AssertionError("generation did not finish")


def connect(client, sid, **overrides):
    body = {"session_id": sid, "preset": "gmail", "from_email": "office@example.edu", "password": SECRET,
            "from_name": "Exam Cell"}
    body.update(overrides)
    return client.post("/api/email/config", json=body)


def compose(sid, job_id, **extra):
    data = {"session_id": sid, "job_id": job_id, "email_column": "Email Address",
            "subject": "Certificate for {name}", "body": "Dear {name} ({department}),\nAttached.\n{sender_name}"}
    data.update(extra)
    return data


def wait_email(client, email_job_id):
    for _ in range(400):
        status = client.get(f"/api/email/jobs/{email_job_id}").json()
        if status["status"] not in ("queued", "running"):
            return status
        time.sleep(0.05)
    raise AssertionError("email job did not finish")


def test_parse_email_list():
    assert parse_email_list("a@x.com; b@y.org") == (["a@x.com", "b@y.org"], [])
    assert parse_email_list("<a.b+tag@uni.ac.in>") == (["a.b+tag@uni.ac.in"], [])
    assert parse_email_list("mailto:a@x.com") == (["a@x.com"], [])
    assert parse_email_list("bad@, good@x.io") == (["good@x.io"], ["bad@"])
    assert parse_email_list("") == ([], [])


def test_render_template_only_replaces_known_placeholders():
    text = render_template("Hi {name} {unknown} {{name}}", {"name": "José"})
    assert text == "Hi José {unknown} {José}"


def test_login_is_verified_and_password_never_returned(tmp_path, make_xlsx, template_png):
    with make_client(tmp_path) as client:
        sid, _, _ = generated_job(client, make_xlsx, template_png)
        bad = connect(client, sid, password="wrong")
        assert bad.status_code == 422 and "App Password" in bad.json()["detail"]
        ok = connect(client, sid)
        assert ok.status_code == 200, ok.text
        assert ok.json()["password_set"] and ok.json()["host"] == "smtp.gmail.com"
        assert SECRET not in ok.text
        cfg = client.get("/api/email/config", params={"session_id": sid})
        assert SECRET not in cfg.text and cfg.json()["current"]["from_email"] == "office@example.edu"
        # Editing the sender name keeps the stored password without resending it.
        assert connect(client, sid, password="", from_name="Dept Office").status_code == 200
        assert client.delete("/api/email/config", params={"session_id": sid}).status_code == 200
        assert client.get("/api/email/config", params={"session_id": sid}).json()["current"] is None


def test_refuses_password_over_unencrypted_connection(tmp_path, make_xlsx, template_png):
    with make_client(tmp_path) as client:
        sid, _, _ = generated_job(client, make_xlsx, template_png)
        r = connect(client, sid, preset="custom", host="mail.example.edu", port=25, security="none")
        assert r.status_code == 422 and "unencrypted" in r.json()["detail"]


def test_preview_classifies_every_row(tmp_path, make_xlsx, template_png):
    with make_client(tmp_path) as client:
        sid, job_id, _ = generated_job(client, make_xlsx, template_png)
        preview = client.post("/api/email/preview", json=compose(sid, job_id)).json()
        status = {p["row_number"]: p["status"] for p in preview["recipients"]}
        assert status == {2: "ready", 3: "no_email", 4: "invalid_email", 5: "no_certificate", 6: "ready", 7: "ready"}
        assert preview["counts"]["ready"] == 3
        assert preview["sample"]["subject"] == "Certificate for Asha Rao"
        assert preview["sample"]["attachment"] == "Asha_Rao_Certificate.pdf"
        shared = next(p for p in preview["recipients"] if p["row_number"] == 7)
        assert "row(s) 2" in shared["reason"]


def test_send_requires_authorisation_and_exact_count_then_sends_each_student_their_own_pdf(tmp_path, make_xlsx, template_png):
    with make_client(tmp_path) as client:
        sid, job_id, job = generated_job(client, make_xlsx, template_png)
        assert client.post("/api/email/send", json=compose(sid, job_id, authorized=True, confirm_count=3)).status_code == 409  # not connected
        assert connect(client, sid).status_code == 200
        assert client.post("/api/email/send", json=compose(sid, job_id, authorized=False, confirm_count=3)).status_code == 400
        mismatch = client.post("/api/email/send", json=compose(sid, job_id, authorized=True, confirm_count=6))
        assert mismatch.status_code == 400 and "3 e-mail(s)" in mismatch.json()["detail"]
        assert not FakeSMTP.sent

        started = client.post("/api/email/send", json=compose(sid, job_id, authorized=True, confirm_count=3))
        assert started.status_code == 202
        result = wait_email(client, started.json()["email_job_id"])
        assert result["status"] == "completed"
        assert result["counts"]["sent"] == 3 and result["counts"]["skipped"] == 3

        expected = {  # recipient(s) -> that row's own certificate
            "asha@example.edu": ("Asha_Rao_Certificate.pdf", "Asha Rao"),
            "dev@example.edu, dev.p@example.org": ("Dev_Patel_Certificate.pdf", "Dev Patel"),
            "ASHA@example.edu": ("Esha_Rao_Certificate.pdf", "Esha Rao"),
        }
        assert len(FakeSMTP.sent) == 3
        for msg in FakeSMTP.sent:
            filename, name = expected[msg["To"]]
            attachments = list(msg.iter_attachments())
            assert len(attachments) == 1
            assert attachments[0].get_filename() == filename
            assert attachments[0].get_content().startswith(b"%PDF")
            assert msg["Subject"] == f"Certificate for {name}"
            assert f"Dear {name}" in msg.get_body(("plain",)).get_content()
            assert "Exam Cell" in msg["From"]
        assert FakeSMTP.connections <= 3  # verify + one reused connection for the batch

        report = client.get(f"/api/jobs/{job_id}/files/{result['report_file']}")
        assert report.status_code == 200 and "Asha Rao" in report.content.decode("utf-8-sig")
        assert client.get(f"/api/jobs/{job_id}").json()["emails_sent"] == 3


def test_students_are_not_emailed_twice_unless_resend(tmp_path, make_xlsx, template_png):
    with make_client(tmp_path) as client:
        sid, job_id, _ = generated_job(client, make_xlsx, template_png)
        connect(client, sid)
        wait_email(client, client.post("/api/email/send", json=compose(sid, job_id, authorized=True, confirm_count=3)).json()["email_job_id"])
        again = client.post("/api/email/preview", json=compose(sid, job_id)).json()
        assert again["counts"].get("ready", 0) == 0 and again["counts"]["already_sent"] == 3
        assert client.post("/api/email/send", json=compose(sid, job_id, authorized=True, confirm_count=0)).status_code == 409
        resend = client.post("/api/email/preview", json=compose(sid, job_id, resend=True)).json()
        assert resend["counts"]["ready"] == 3


def test_rejected_recipient_fails_only_that_row(tmp_path, make_xlsx, template_png):
    with make_client(tmp_path) as client:
        sid, job_id, _ = generated_job(client, make_xlsx, template_png)
        connect(client, sid)
        FakeSMTP.refuse = {"asha@example.edu"}
        result = wait_email(client, client.post("/api/email/send", json=compose(sid, job_id, authorized=True, confirm_count=3)).json()["email_job_id"])
        by_row = {r["row_number"]: r for r in result["results"]}
        assert by_row[2]["status"] == "failed" and "rejected" in by_row[2]["message"]
        assert by_row[6]["status"] == "sent" and by_row[7]["status"] == "sent"
        # Retry just the failed row once the problem is fixed.
        FakeSMTP.refuse = set()
        retry = compose(sid, job_id, authorized=True, confirm_count=1, only_indices=[by_row[2]["index"]])
        result = wait_email(client, client.post("/api/email/send", json=retry).json()["email_job_id"])
        assert result["counts"]["sent"] == 1


def test_login_failure_during_sending_stops_and_reports_every_row(tmp_path, make_xlsx, template_png):
    with make_client(tmp_path) as client:
        sid, job_id, _ = generated_job(client, make_xlsx, template_png)
        connect(client, sid)
        FakeSMTP.fail_login = True
        result = wait_email(client, client.post("/api/email/send", json=compose(sid, job_id, authorized=True, confirm_count=3)).json()["email_job_id"])
        assert result["status"] == "failed" and "stopped" in result["error"]
        assert result["counts"]["failed"] == 3 and result["counts"]["pending"] == 0
        assert not FakeSMTP.sent


def test_test_email_goes_only_to_the_given_address(tmp_path, make_xlsx, template_png):
    with make_client(tmp_path) as client:
        sid, job_id, _ = generated_job(client, make_xlsx, template_png, pdf=True)
        connect(client, sid)
        assert client.post("/api/email/test", json=compose(sid, job_id, to="not valid")).status_code == 422
        r = client.post("/api/email/test", json=compose(sid, job_id, to="me@example.edu"))
        assert r.status_code == 200, r.text
        assert len(FakeSMTP.sent) == 1
        msg = FakeSMTP.sent[0]
        assert msg["To"] == "me@example.edu" and msg["Subject"].startswith("[TEST] Certificate for Asha Rao")
        assert client.get(f"/api/jobs/{job_id}").json()["emails_sent"] == 0


def test_subject_cannot_inject_headers(tmp_path, make_xlsx, template_png):
    with make_client(tmp_path) as client:
        sid, job_id, _ = generated_job(client, make_xlsx, template_png)
        connect(client, sid)
        evil = compose(sid, job_id, subject="Hello\r\nBcc: attacker@evil.test {name}", authorized=True, confirm_count=3)
        wait_email(client, client.post("/api/email/send", json=evil).json()["email_job_id"])
        for msg in FakeSMTP.sent:
            assert msg["Bcc"] is None
            assert "\n" not in msg["Subject"] and msg["Subject"].startswith("Hello Bcc:")


def test_cancel_stops_remaining_emails(tmp_path, make_xlsx, template_png):
    rows = [["Student Name", "Email Address"]] + [[f"Student {i}", f"s{i}@example.edu"] for i in range(6)]
    with make_client(tmp_path, delay=0.5) as client:
        sid, job_id, _ = generated_job(client, make_xlsx, template_png, rows=rows)
        connect(client, sid)
        email_job_id = client.post("/api/email/send", json=compose(sid, job_id, authorized=True, confirm_count=6)).json()["email_job_id"]
        time.sleep(0.2)
        client.post(f"/api/email/jobs/{email_job_id}/cancel")
        result = wait_email(client, email_job_id)
        assert result["status"] == "cancelled"
        assert result["counts"]["cancelled"] >= 3
        assert result["counts"]["sent"] + result["counts"]["cancelled"] == 6
