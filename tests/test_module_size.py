"""The source-size gate includes nested modules and counts all physical lines."""

from scripts.check_module_size import main


def test_source_modules_stay_within_limit():
    assert main() == 0


def test_module_size_accepts_900_lines_including_comments_and_blanks(tmp_path):
    (tmp_path / "module.py").write_text("# comment\n\n" * 450, encoding="utf-8")
    assert main(tmp_path) == 0


def test_module_size_reports_all_oversized_nested_modules(tmp_path, capsys):
    package = tmp_path / "package"
    package.mkdir()
    # A final line without a newline counts; Windows CRLF counts once per line.
    (package / "__init__.py").write_bytes(b"# comment\r\n" * 900 + b"# last line")
    (package / "module.py").write_text("\n" * 902, encoding="utf-8")
    assert main(tmp_path) == 1
    errors = capsys.readouterr().err
    assert "package/__init__.py: 901 lines (maximum 900)" in errors
    assert "package/module.py: 902 lines (maximum 900)" in errors


def test_module_size_rejects_missing_source_tree(tmp_path):
    assert main(tmp_path / "missing") == 1
