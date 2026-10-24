"""Generate SAMPLE test data: two Excel files and a sample certificate template.

All people are fictional; emails use the reserved example.edu domain.
Run from the project root:  backend\\.venv\\Scripts\\python samples\\make_samples.py
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FONTS = HERE.parent / "backend" / "app" / "fonts"

FIRST = ["Aarav", "Priya", "José", "Mei", "Oluwaseun", "Zoë", "Liam", "Fatima", "Arjun", "Sofía",
         "Kenji", "Aisha", "Mateo", "Ananya", "Noah", "Chiara", "Rahul", "Elif", "Lucas", "Divya"]
LAST = ["Sharma", "O'Connor", "García", "Nguyễn", "Okafor", "Müller", "Krishnan", "Al-Sayed", "Rossi", "Tanaka",
        "Iyer", "Kowalski", "Fernández", "Das", "Smith", "Haddad", "Venkataraman", "Yılmaz", "Dubois", "Menon"]
DEPARTMENTS = ["Computer Science", "Electronics & Communication", "Mechanical Engineering", "Civil Engineering",
               "Information Technology", "Electrical & Electronics", "Biotechnology"]


def ascii_slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(ch for ch in text.lower() if ch.isalnum())


def students(n: int = 100) -> list[tuple[str, str, str]]:
    rows = []
    for i in range(n):
        first, last = FIRST[i % 20], LAST[(i * 7 + i // 20) % 20]
        name = f"{first} {last}"
        if i == 17:
            name = "Venkata Lakshmi Narasimha Subrahmanya Sharma"   # very long name
        if i == 42:
            name = "Anne-Marie de la Cruz-Villanueva"
        rows.append((name, DEPARTMENTS[i % len(DEPARTMENTS)], f"{ascii_slug(name.split()[0])}.{ascii_slug(name.split()[-1])}{i + 1}@example.edu"))
    names = [r[0] for r in rows]
    assert len(set(names)) == len(names), "sample names must be unique"
    return rows


def style_header(ws, row: int) -> None:
    for cell in ws[row]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="4F46E5")


def make_main_excel(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Students"
    ws.append(["Student Name", "Department", "Email Address"])
    style_header(ws, 1)
    for i, (name, dept, email) in enumerate(students(100)):
        if i == 5:
            name = f"  {name}  "        # stray spaces are cleaned automatically
        ws.append([name, dept, email])
    for col, width in zip("ABC", (42, 32, 44)):
        ws.column_dimensions[col].width = width
    wb.save(path)


def make_edge_case_excel(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Batch A"
    ws.append(["Workshop on Applied AI - Participants (SAMPLE DATA)"])
    ws.append([])
    ws.append(["S.No", "Name of the Student", "Dept.", "E-mail ID"])
    style_header(ws, 3)
    rows = [
        ("Kavya Raghunathan", "CSE", "kavya@example.edu"),
        (None, "ECE", "missing.name@example.edu"),              # blank name -> skipped & reported
        ("Kavya Raghunathan", "IT", "kavya.r2@example.edu"),    # duplicate name -> separate file _2
        ("  rOHAN   mEHTA ", "MECH", "rohan@example.edu"),      # spacing fixed, odd capitalisation preserved
        ("Siobhán Ní Bhriain", "CIVIL", "siobhan@example.edu"),
        ("அருண் குமார்", "EEE", "arun@example.edu"),             # Tamil script (use an Indic-capable font)
        ("Bartholomew Maximilian Featherstonehaugh-Worthington", "BIO", "bart@example.edu"),
        ("NA", "CSE", "na.surname@example.edu"),                  # literal NA is a real value
        ("Chloé D'Souza", "CSE", "not-an-email"),
    ]
    for i, row in enumerate(rows, start=1):
        ws.append([i, *row])
    ws.append([])
    ws.append([10, "Último Estudiante", "ECE", "ultimo@example.edu"])
    wb.create_sheet("Batch B").append(["Student Name", "Department"])
    wb["Batch B"].append(["Second Sheet Student", "Physics"])
    wb.save(path)


def font(name: str, size: int, variation: str | None = None):
    path = FONTS / name
    if not path.exists():
        return ImageFont.load_default(size=size)
    f = ImageFont.truetype(str(path), size)
    if variation:
        f.set_variation_by_name(variation)
    return f


def make_template(path: Path, size=(2480, 1754)) -> None:
    w, h = size
    img = Image.new("RGB", size, (252, 248, 238))
    d = ImageDraw.Draw(img)
    navy, gold = (27, 42, 74), (184, 146, 64)
    d.rectangle([40, 40, w - 41, h - 41], outline=navy, width=14)
    d.rectangle([80, 80, w - 81, h - 81], outline=gold, width=5)
    for cx, cy in [(80, 80), (w - 81, 80), (80, h - 81), (w - 81, h - 81)]:
        d.ellipse([cx - 28, cy - 28, cx + 28, cy + 28], fill=gold)

    centre = w // 2
    d.text((centre, 300), "CERTIFICATE", font=font("Cinzel[wght].ttf", 150, "Bold"), fill=navy, anchor="mm")
    d.text((centre, 430), "OF ACHIEVEMENT", font=font("Cinzel[wght].ttf", 70, "Regular"), fill=gold, anchor="mm")
    d.line([(centre - 420, 500), (centre + 420, 500)], fill=gold, width=4)
    d.text((centre, 610), "This certificate is proudly presented to", font=font("Lora[wght].ttf", 56), fill=(70, 70, 80), anchor="mm")
    # Name area is intentionally left blank; a thin guide line sits under it.
    d.line([(centre - 750, 950), (centre + 750, 950)], fill=(150, 150, 160), width=3)
    body = font("Lora[wght].ttf", 48)
    d.text((centre, 1060), "for outstanding performance and successful completion of the", font=body, fill=(70, 70, 80), anchor="mm")
    d.text((centre, 1130), "Annual Technical Symposium 2026", font=font("Lora[wght].ttf", 52, "Bold"), fill=navy, anchor="mm")

    small = font("Lora[wght].ttf", 40)
    for x, label in [(620, "Principal"), (w - 620, "Event Coordinator")]:
        d.line([(x - 260, 1440), (x + 260, 1440)], fill=navy, width=3)
        d.text((x, 1495), label, font=small, fill=navy, anchor="mm")
    d.ellipse([centre - 130, 1330, centre + 130, 1590], outline=gold, width=10)
    d.text((centre, 1460), "SEAL", font=font("Cinzel[wght].ttf", 56, "Bold"), fill=gold, anchor="mm")
    d.text((centre, h - 120), "SAMPLE TEMPLATE FOR TESTING ONLY", font=font("Lora[wght].ttf", 28), fill=(180, 175, 165), anchor="mm")
    img.save(path, format="PNG", dpi=(300, 300))


if __name__ == "__main__":
    make_main_excel(HERE / "sample_students.xlsx")
    make_edge_case_excel(HERE / "sample_students_edge_cases.xlsx")
    make_template(HERE / "sample_certificate_template.png")
    print("Created sample_students.xlsx, sample_students_edge_cases.xlsx and sample_certificate_template.png in", HERE)
