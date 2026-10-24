from __future__ import annotations

import pytest

from app.excel_parser import ExcelParseError, analyze_records, clean_cell, match_header, parse_workbook
from conftest import student_rows


def test_detects_standard_headers_and_reads_all_rows(make_xlsx):
    parsed = parse_workbook(make_xlsx(student_rows(100)))
    assert parsed.header_row_number == 1
    assert parsed.detected_mapping == {"name": "Student Name", "department": "Department", "email": "Email Address"}
    assert len(parsed.records) == 100
    assert parsed.records[0].row_number == 2
    assert parsed.records[-1].row_number == 101
    assert [r.index for r in parsed.records] == list(range(100))


def test_rows_keep_their_own_values(make_xlsx):
    parsed = parse_workbook(make_xlsx(student_rows(50)))
    for rec in parsed.records:
        number = rec.values["Student Name"].rsplit(" ", 1)[1]
        assert rec.values["Email Address"] == f"student{number}@example.edu"
        assert rec.row_number == int(number) + 1


def test_header_below_title_rows(make_xlsx):
    rows = [["Annual Sports Meet 2026"], [], ["S.No", "Name of the Student", "Dept.", "E-mail ID"],
            [1, "Priya Raman", "ECE", "priya@example.com"], [2, "Liam Smith", "CSE", "liam@example.com"]]
    parsed = parse_workbook(make_xlsx(rows))
    assert parsed.header_row_number == 3
    assert parsed.detected_mapping == {"name": "Name of the Student", "department": "Dept.", "email": "E-mail ID"}
    assert [r.values["Name of the Student"] for r in parsed.records] == ["Priya Raman", "Liam Smith"]
    assert parsed.records[0].row_number == 4
    assert parsed.records[0].values["S.No"] == "1"


def test_unrecognised_headers_require_manual_mapping(make_xlsx):
    rows = [["Col1", "Col2"], ["Alice Wong", "Physics"], ["Bob Lee", "Maths"]]
    parsed = parse_workbook(make_xlsx(rows))
    assert parsed.detected_mapping["name"] is None
    assert parsed.columns == ["Col1", "Col2"]
    assert len(parsed.records) == 2


def test_email_column_guessed_from_content(make_xlsx):
    rows = [["Student Name", "Contact"], ["Alice", "alice@example.com"], ["Bob", "bob@example.com"]]
    assert parse_workbook(make_xlsx(rows)).detected_mapping["email"] == "Contact"


def test_header_matching_avoids_wrong_name_columns():
    assert match_header("Father's Name")[0] is None
    assert match_header("College Name")[0] is None
    assert match_header("Participant Name") == ("name", 3)
    assert match_header("Student_Name")[0] == "name"
    assert match_header("Branch / Department")[0] == "department"


def test_whitespace_cleaned_but_spelling_and_case_preserved(make_xlsx):
    rows = [["Name"], ["  mARY   ann\to'NEIL  "], [" DeShawn​  McALLISTER "]]
    names = [r.values["Name"] for r in parse_workbook(make_xlsx(rows)).records]
    assert names == ["mARY ann o'NEIL", "DeShawn McALLISTER"]


@pytest.mark.parametrize("name", [
    "José Álvarez", "Zoë Müller-Lüdenscheidt", "Nguyễn Thị Minh Khai", "அருண் குமார்", "王小明",
    "Ōtsuka Ren", "Siobhán Ní Bhriain", "Anne-Marie D'Souza", "Ægir Þórsson",
])
def test_special_characters_preserved(make_xlsx, name):
    parsed = parse_workbook(make_xlsx([["Student Name"], [name]]))
    assert parsed.records[0].values["Student Name"] == name


def test_literal_na_values_are_not_treated_as_blank(make_xlsx):
    parsed = parse_workbook(make_xlsx([["Name"], ["NA"], ["None"], ["null"]]))
    assert [r.values["Name"] for r in parsed.records] == ["NA", "None", "null"]


def test_blank_names_and_empty_rows(make_xlsx):
    rows = [["Name", "Department"], ["Asha", "CSE"], [None, "EEE"], [], ["   ", "MECH"], ["Ravi", "IT"], [], []]
    parsed = parse_workbook(make_xlsx(rows))
    assert [r.row_number for r in parsed.records] == [2, 3, 5, 6]
    assert parsed.ignored_empty_rows == 1   # trailing empty rows are not counted
    analysis = analyze_records(parsed.records, "Name", "Department")
    assert analysis.valid_names == 2
    assert analysis.blank_name_rows == [3, 5]


def test_duplicates_detected_case_insensitively(make_xlsx):
    rows = [["Name"], ["Kiran Das"], ["kiran das"], ["Meera"], ["Kiran  Das"]]
    analysis = analyze_records(parse_workbook(make_xlsx(rows)).records, "Name")
    assert analysis.duplicate_groups == [{"name": "Kiran Das", "rows": [2, 3, 5]}]


def test_invalid_emails_reported(make_xlsx):
    rows = [["Name", "Email"], ["A", "a@example.com"], ["B", "not-an-email"], ["C", ""]]
    analysis = analyze_records(parse_workbook(make_xlsx(rows)).records, "Name", email_column="Email")
    assert analysis.invalid_email_rows == [3]


def test_numeric_cells_are_clean_text():
    assert clean_cell(101.0) == "101"
    assert clean_cell(3.5) == "3.5"
    assert clean_cell(None) == ""
    assert clean_cell(float("nan")) == ""


def test_no_header_row_and_explicit_header_row(make_xlsx):
    path = make_xlsx([["Title"], ["Asha", "CSE"], ["Ravi", "IT"]])
    no_header = parse_workbook(path, header_row="none")
    assert no_header.columns == ["Column A", "Column B"]
    assert [r.values["Column A"] for r in no_header.records] == ["Title", "Asha", "Ravi"]
    explicit = parse_workbook(path, header_row="2")
    assert explicit.columns == ["Asha", "CSE"]
    assert len(explicit.records) == 1


def test_duplicate_and_blank_headers_get_unique_names(make_xlsx):
    parsed = parse_workbook(make_xlsx([["Name", "Name", None, "Email"], ["a", "b", "c", "d@x.io"]]))
    assert parsed.columns == ["Name", "Name (2)", "Column C", "Email"]


def test_sheet_selection(make_xlsx):
    path = make_xlsx([["Name"], ["First Sheet Student"]], extra_sheets={"Batch 2": [["Name"], ["Second Sheet Student"]]})
    parsed = parse_workbook(path, sheet="Batch 2")
    assert parsed.sheets == ["Students", "Batch 2"]
    assert parsed.records[0].values["Name"] == "Second Sheet Student"
    with pytest.raises(ExcelParseError):
        parse_workbook(path, sheet="Missing")


def test_legacy_xls_supported(tmp_path):
    xlwt = pytest.importorskip("xlwt")
    book = xlwt.Workbook()
    sheet = book.add_sheet("Sheet1")
    for r, row in enumerate([["Student Name", "Department"], ["Lakshmi Narayanan", "Civil"], ["Óscar Peña", "Arts"]]):
        for c, value in enumerate(row):
            sheet.write(r, c, value)
    path = tmp_path / "legacy.xls"
    book.save(str(path))
    parsed = parse_workbook(path)
    assert [r.values["Student Name"] for r in parsed.records] == ["Lakshmi Narayanan", "Óscar Peña"]


def test_rejects_non_excel_files(tmp_path):
    path = tmp_path / "fake.xlsx"
    path.write_text("name,email\nA,a@b.c")
    with pytest.raises(ExcelParseError):
        parse_workbook(path)


def test_row_limit(make_xlsx):
    with pytest.raises(ExcelParseError, match="more than 10"):
        parse_workbook(make_xlsx(student_rows(11)), max_rows=10)
