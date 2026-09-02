"""§5.2's drawdown record: the plan and the brief must quote the same figures (2026-09-02).

Every constant traces to the plan (`.claude/rules/trading-code.md`). The brief quotes the record
rather than deriving it, so the one way the two can drift is an edit to one without the other.
This holds §5.2's own text and `brief.DD_RECORD_*` to each other, digit for digit.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import brief  # noqa: E402


def _section_5_2():
    plan = (ROOT / "docs" / "yuna_plan.md").read_text()
    start = plan.index("**5.2 Drawdown milestones")
    end = plan.index("**5.3 ", start)
    return plan[start:end].replace("\u2212", "-")        # the plan writes a true minus sign


def test_every_share_the_brief_quotes_is_in_ss5_2():
    s = _section_5_2()
    for depth, share in brief.DD_RECORD_SHARE.items():
        assert f"| {abs(int(round(depth * 100)))}% | {share:.1%} |" in s, (depth, share)
    assert f"run {brief.DD_RECORD_RUN}" in s
    assert f"{brief.DD_RECORD_SESSIONS:,} sessions" in s


def test_both_recoveries_the_brief_quotes_are_in_ss5_2():
    s = _section_5_2()
    for t in brief.DD_RECORD_TROUGHS:
        assert f"{t['depth']:.1%} on {t['trough']}" in s, t
        assert t["new_high"] in s and f"{t['took']} later" in s, t


def test_the_reminder_reads_the_deepest_milestone_passed_and_never_computes():
    lines = brief.record_lines(-0.35)
    assert "at least 30% below its high is 26.2%" in lines[0]
    assert "at least 10% below is 68.4%" in lines[0]
    assert brief.record_lines(-0.02)[0].endswith("today is one of the other 31.6%")
    assert brief.record_lines(None)[0].endswith("today is one of the other 31.6%")
    assert brief.record_lines(-0.61)[0].startswith("  the record (§5.2, run 624): a book at least 50% below")
    for dd in (-0.35, -0.02, None):
        assert brief.record_lines(dd)[-1].startswith("  the bet is the rotation, not the name")
