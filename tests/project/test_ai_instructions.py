import importlib.util
from pathlib import Path

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


def test_claude_imports_ai_md_and_copilot_is_pointed_at_it():
    assert (ROOT / "CLAUDE.md").read_text(encoding="utf-8").splitlines()[0] == "@AI.md"
    assert "(../AI.md)" in (ROOT / ".github" / "copilot-instructions.md").read_text("utf-8")


def test_ai_md_stays_short_enough_to_be_followed():
    # Claude Code's guidance: under 200 lines, or adherence drops.
    assert len((ROOT / "AI.md").read_text(encoding="utf-8").splitlines()) < 200


def test_check_reports_a_stale_copy_and_writing_fixes_it(tmp_path, capsys):
    (tmp_path / "AI.md").write_text("# Rules\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("old\n", encoding="utf-8")
    assert ai_instructions.main(["--check", "--root", str(tmp_path)]) == 1
    assert "run 'just ai'" in capsys.readouterr().err
    assert ai_instructions.main(["--root", str(tmp_path)]) == 0
    assert ai_instructions.main(["--check", "--root", str(tmp_path)]) == 0
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8").endswith("# Rules\n")
