"""DocEngine — Markdown Fidelity Validation Script.

Validates the fidelity of Markdown output produced by DocEngine
against a reference or against quality metrics.

Usage:
    python scripts/validate_fidelity.py <markdown_file>
    python scripts/validate_fidelity.py outputs/<doc_id>/<file>.md
    python scripts/validate_fidelity.py outputs/<doc_id>/<file>.md --reference reference.md

Exit codes:
    0: All checks passed
    1: One or more quality issues detected
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import click


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class FidelityCheck:
    """Result of a single fidelity check.

    Attributes:
        name: Check name.
        passed: Whether the check passed.
        score: Optional numeric score (0.0–1.0).
        message: Human-readable description.
    """

    name: str
    passed: bool
    score: float | None
    message: str


@dataclass
class FidelityReport:
    """Aggregate fidelity report for a Markdown document.

    Attributes:
        filepath: Path to the Markdown file.
        checks: List of individual check results.
        overall_score: Weighted average of all check scores.
        passed: True if all checks passed.
    """

    filepath: Path
    checks: list[FidelityCheck] = field(default_factory=list)
    overall_score: float = 0.0
    passed: bool = True

    def to_dict(self) -> dict:
        """Serialize the report to a dictionary."""
        return {
            "filepath": str(self.filepath),
            "overall_score": round(self.overall_score, 3),
            "passed": self.passed,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "score": c.score,
                    "message": c.message,
                }
                for c in self.checks
            ],
        }


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------


def check_not_empty(markdown: str) -> FidelityCheck:
    """Check that the Markdown file is not empty."""
    passed = len(markdown.strip()) > 100
    return FidelityCheck(
        name="content_not_empty",
        passed=passed,
        score=1.0 if passed else 0.0,
        message=(
            f"Document has {len(markdown)} characters."
            if passed
            else f"Document is too short ({len(markdown)} chars). May be empty or corrupted."
        ),
    )


def check_heading_structure(markdown: str) -> FidelityCheck:
    """Check that the document has at least one heading."""
    headings = re.findall(r"^#{1,6}\s+.+", markdown, re.MULTILINE)
    count = len(headings)
    passed = count > 0
    return FidelityCheck(
        name="heading_structure",
        passed=passed,
        score=min(1.0, count / 5),
        message=(
            f"Found {count} heading(s). Document structure detected."
            if passed
            else "No headings found. Document structure may be unrecognized."
        ),
    )


def check_no_column_mixing(markdown: str) -> FidelityCheck:
    """Heuristic check for column mixing artifacts.

    Column mixing produces short alternating lines from different columns.
    Detects when > 30% of lines are very short (< 20 chars) in a document
    with substantial content.
    """
    lines = [l for l in markdown.splitlines() if l.strip()]
    if len(lines) < 20:
        return FidelityCheck(
            name="no_column_mixing",
            passed=True,
            score=1.0,
            message="Document too short for column mixing analysis.",
        )

    short_lines = sum(1 for l in lines if 0 < len(l.strip()) < 20)
    ratio = short_lines / len(lines)
    passed = ratio < 0.30

    return FidelityCheck(
        name="no_column_mixing",
        passed=passed,
        score=1.0 - ratio,
        message=(
            f"Short line ratio: {ratio:.0%}. {'Possible column mixing detected.' if not passed else 'OK.'}"
        ),
    )


def check_table_integrity(markdown: str) -> FidelityCheck:
    """Check that Markdown tables have consistent column counts."""
    table_blocks = re.findall(
        r"((?:\|.+\|\n)+(?:\|[-:| ]+\|\n)(?:\|.+\|\n)*)", markdown
    )

    if not table_blocks:
        return FidelityCheck(
            name="table_integrity",
            passed=True,
            score=1.0,
            message="No tables found (or tables present but no issues).",
        )

    malformed = 0
    for block in table_blocks:
        rows = [r for r in block.strip().splitlines() if r.startswith("|")]
        if not rows:
            continue
        col_counts = [r.count("|") for r in rows]
        if len(set(col_counts)) > 1:
            malformed += 1

    passed = malformed == 0
    score = 1.0 - (malformed / len(table_blocks)) if table_blocks else 1.0

    return FidelityCheck(
        name="table_integrity",
        passed=passed,
        score=score,
        message=(
            f"{len(table_blocks)} table(s) found. {malformed} malformed."
            if malformed
            else f"{len(table_blocks)} table(s) found. All well-formed."
        ),
    )


def check_no_duplicate_content(markdown: str) -> FidelityCheck:
    """Check for excessive duplicate lines (repetitive headers/footers not removed)."""
    lines = [l.strip() for l in markdown.splitlines() if l.strip() and len(l.strip()) > 10]
    if not lines:
        return FidelityCheck(
            name="no_duplicate_content",
            passed=True,
            score=1.0,
            message="No content to analyze.",
        )

    from collections import Counter  # noqa: PLC0415

    counts = Counter(lines)
    duplicates = {text: count for text, count in counts.items() if count > 5}

    score = max(0.0, 1.0 - (len(duplicates) / max(1, len(set(lines)))))
    passed = score >= 0.90

    return FidelityCheck(
        name="no_duplicate_content",
        passed=passed,
        score=score,
        message=(
            f"Found {len(duplicates)} lines repeated >5 times. Score: {score:.1%}."
            if duplicates
            else "No problematic duplicates detected."
        ),
    )


def check_content_density(markdown: str, expected_pages: int | None = None) -> FidelityCheck:
    """Check chars-per-page density if page count is available."""
    chars = len(markdown)
    if expected_pages and expected_pages > 0:
        chars_per_page = chars / expected_pages
        passed = chars_per_page >= 100
        score = min(1.0, chars_per_page / 500)
        message = f"{chars_per_page:.0f} chars/page (min expected: 100)."
    else:
        passed = chars > 200
        score = 1.0 if passed else 0.3
        message = f"Total content: {chars} characters."

    return FidelityCheck(
        name="content_density",
        passed=passed,
        score=score,
        message=message,
    )


def compare_with_reference(markdown: str, reference: str) -> FidelityCheck:
    """Compare extracted Markdown against a reference file."""
    md_words = set(markdown.lower().split())
    ref_words = set(reference.lower().split())

    if not ref_words:
        return FidelityCheck(
            name="reference_comparison",
            passed=True,
            score=1.0,
            message="Reference file is empty.",
        )

    overlap = len(md_words & ref_words)
    recall = overlap / len(ref_words)
    precision = overlap / len(md_words) if md_words else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    passed = f1 >= 0.70
    return FidelityCheck(
        name="reference_comparison",
        passed=passed,
        score=f1,
        message=(
            f"F1 score vs reference: {f1:.2%} "
            f"(precision={precision:.2%}, recall={recall:.2%}). "
            f"{'PASS' if passed else 'FAIL — below 70% threshold.'}"
        ),
    )


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------


def validate_fidelity(
    md_path: Path,
    reference_path: Path | None = None,
    page_count: int | None = None,
) -> FidelityReport:
    """Run all fidelity checks against a Markdown file.

    Args:
        md_path: Path to the Markdown file to validate.
        reference_path: Optional path to a reference Markdown file.
        page_count: Optional expected page count for density check.

    Returns:
        FidelityReport with results of all checks.
    """
    markdown = md_path.read_text(encoding="utf-8")
    report = FidelityReport(filepath=md_path)

    report.checks.append(check_not_empty(markdown))
    report.checks.append(check_heading_structure(markdown))
    report.checks.append(check_no_column_mixing(markdown))
    report.checks.append(check_table_integrity(markdown))
    report.checks.append(check_no_duplicate_content(markdown))
    report.checks.append(check_content_density(markdown, page_count))

    if reference_path and reference_path.exists():
        reference = reference_path.read_text(encoding="utf-8")
        report.checks.append(compare_with_reference(markdown, reference))

    # Compute overall score
    scores = [c.score for c in report.checks if c.score is not None]
    report.overall_score = sum(scores) / len(scores) if scores else 0.0
    report.passed = all(c.passed for c in report.checks)

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command()
@click.argument("markdown_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--reference",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional reference Markdown file for comparison.",
)
@click.option(
    "--pages",
    type=int,
    default=None,
    help="Expected number of pages for density validation.",
)
@click.option(
    "--json-output",
    is_flag=True,
    default=False,
    help="Output report as JSON.",
)
@click.option(
    "--metadata",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional metadata.json to read page count from.",
)
def main(
    markdown_file: Path,
    reference: Path | None,
    pages: int | None,
    json_output: bool,
    metadata: Path | None,
) -> None:
    """Validate fidelity of DocEngine Markdown output.

    MARKDOWN_FILE: Path to the .md file to validate.
    """
    # Try to read page count from metadata if provided
    page_count = pages
    if metadata and metadata.exists() and page_count is None:
        try:
            meta_data = json.loads(metadata.read_text(encoding="utf-8"))
            page_count = meta_data.get("page_count")
        except Exception:
            pass

    # Force UTF-8 on Windows console streams
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    report = validate_fidelity(
        md_path=markdown_file,
        reference_path=reference,
        page_count=page_count,
    )

    if json_output:
        click.echo(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        _print_report(report)

    sys.exit(0 if report.passed else 1)


def _print_report(report: FidelityReport) -> None:
    """Print a formatted fidelity report to stdout."""
    overall_icon = "[OK]" if report.passed else "[FAIL]"
    click.echo(f"\n{'='*60}")
    click.echo(f"  DocEngine - Fidelity Validation Report")
    click.echo(f"{'='*60}")
    click.echo(f"  File       : {report.filepath}")
    click.echo(f"  Overall    : {overall_icon} {report.overall_score:.1%}")
    click.echo(f"{'='*60}\n")

    for check in report.checks:
        icon = "[OK]" if check.passed else "[FAIL]"
        score_str = f"{check.score:.2%}" if check.score is not None else " N/A"
        click.echo(f"  {icon} [{score_str}] {check.name}")
        click.echo(f"         {check.message}")

    click.echo(f"\n{'='*60}")
    if report.passed:
        click.echo("  [PASS] VALIDATION PASSED — Markdown fidelity is acceptable.")
    else:
        click.echo("  [FAIL] VALIDATION FAILED — Review warnings above.")
    click.echo(f"{'='*60}\n")


if __name__ == "__main__":
    main()
