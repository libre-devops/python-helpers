import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ai_instructions.py"
spec = importlib.util.spec_from_file_location("ai_instructions", SCRIPT)
ai_instructions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai_instructions)


def test_agents_md_is_ai_md_with_a_note_on_top():
    # Codex, Copilot's coding agent and the rest read AGENTS.md; AI.md is what people edit.
    assert (ROOT / "AGENTS.md").read_text(encoding="utf-8") == ai_instructions.render(ROOT), (
        "AGENTS.md is out of date: run 'just ai'"
    )


def test_kiros_steering_files_are_ai_mds_sections_each_loaded_when_it_applies():
    steering = ROOT / ".kiro" / "steering"
    expected = ai_instructions.steering(ROOT)
    assert {path.name for path in steering.glob("*.md")} == set(expected)
    for name, text in expected.items():
        assert (steering / name).read_text(encoding="utf-8") == text, (
            f".kiro/steering/{name} is out of date: run 'just ai'"
        )
        front, body = text.removeprefix("---\n").split("\n---\n", 1)
        settings = yaml.safe_load(front)
        assert settings["inclusion"] in {"always", "fileMatch"}, name
        if settings["inclusion"] == "fileMatch":
            assert isinstance(settings["fileMatchPattern"], list), name
        assert ai_instructions.HEADER in body
    # Kiro's own three, loaded always.
    for name in ("product.md", "tech.md", "structure.md"):
        assert expected[name].startswith("---\ninclusion: always\n---")


def test_a_section_without_a_steering_file_is_an_error(tmp_path):
    titles = [*ai_instructions.STEERING, "Something new"]
    (tmp_path / "AI.md").write_text("".join(f"## {title}\nx\n" for title in titles), "utf-8")
    with pytest.raises(SystemExit, match="sections without a steering file \\['Something new'\\]"):
        ai_instructions.steering(tmp_path)


def test_a_heading_in_a_code_block_is_not_a_section():
    text = "## One\n```text\n## not a heading\n```\n## Two\nb\n"
    assert ai_instructions.sections(text) == {
        "One": "```text\n## not a heading\n```\n",
        "Two": "b\n",
    }


def test_claude_imports_ai_md_and_copilot_is_pointed_at_it():
    assert (ROOT / "CLAUDE.md").read_text(encoding="utf-8").splitlines()[0] == "@AI.md"
    assert "(../AI.md)" in (ROOT / ".github" / "copilot-instructions.md").read_text("utf-8")


def test_ai_md_stays_short_enough_to_be_followed():
    # Claude Code's guidance: under 200 lines, or adherence drops.
    assert len((ROOT / "AI.md").read_text(encoding="utf-8").splitlines()) < 200


def test_check_reports_a_stale_copy_and_writing_fixes_it(tmp_path, capsys):
    rules = "# Rules\n" + "".join(f"## {title}\nx\n" for title in ai_instructions.STEERING)
    (tmp_path / "AI.md").write_text(rules, encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("old\n", encoding="utf-8")
    assert ai_instructions.main(["--check", "--root", str(tmp_path)]) == 1
    errors = capsys.readouterr().err
    assert "AGENTS.md is out of date with AI.md: run 'just ai'" in errors
    assert ".kiro/steering/code.md is out of date" in errors.replace("\\", "/")
    assert ai_instructions.main(["--root", str(tmp_path)]) == 0
    assert ai_instructions.main(["--check", "--root", str(tmp_path)]) == 0
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8").endswith(rules)
    assert (
        (tmp_path / ".kiro" / "steering" / "tests.md").read_text("utf-8").endswith("# Tests\n\nx\n")
    )
