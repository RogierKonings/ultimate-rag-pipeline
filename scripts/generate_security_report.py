#!/usr/bin/env python3
"""
Security Report Generator for RAG Pipeline.

Parses results from various security scanners (Bandit, Trivy, Gitleaks, Semgrep)
and generates a consolidated report in JSON and Markdown formats.

Usage:
    python scripts/generate_security_report.py --input-dir ./security-reports --output report.md
"""

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class Finding:
    """Represents a security finding."""

    scanner: str
    severity: str
    title: str
    description: str
    file_path: str | None = None
    line_number: int | None = None
    cwe: str | None = None
    remediation: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class ScanResults:
    """Aggregated scan results."""

    findings: list[Finding] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)
    scanners_run: list[str] = field(default_factory=list)
    scan_time: str = ""
    total_files_scanned: int = 0


def parse_bandit_results(file_path: Path) -> list[Finding]:
    """Parse Bandit JSON results."""
    findings = []

    try:
        with open(file_path) as f:
            data = json.load(f)

        for result in data.get("results", []):
            finding = Finding(
                scanner="Bandit",
                severity=result.get("issue_severity", "UNKNOWN").upper(),
                title=result.get("issue_text", "Unknown Issue"),
                description=f"Test ID: {result.get('test_id', 'N/A')} - {result.get('issue_text', '')}",
                file_path=result.get("filename"),
                line_number=result.get("line_number"),
                cwe=result.get("issue_cwe", {}).get("id") if result.get("issue_cwe") else None,
                remediation=result.get("more_info"),
                raw=result,
            )
            findings.append(finding)

    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Warning: Could not parse Bandit results from {file_path}: {e}")

    return findings


def parse_trivy_results(file_path: Path) -> list[Finding]:
    """Parse Trivy JSON results."""
    findings = []

    try:
        with open(file_path) as f:
            data = json.load(f)

        for result in data.get("Results", []):
            target = result.get("Target", "unknown")
            for vuln in result.get("Vulnerabilities", []):
                finding = Finding(
                    scanner="Trivy",
                    severity=vuln.get("Severity", "UNKNOWN").upper(),
                    title=f"{vuln.get('VulnerabilityID', 'Unknown')} in {vuln.get('PkgName', 'unknown')}",
                    description=vuln.get("Description", "No description"),
                    file_path=target,
                    cwe=vuln.get("CweIDs", [None])[0] if vuln.get("CweIDs") else None,
                    remediation=f"Update to version {vuln.get('FixedVersion', 'N/A')}"
                    if vuln.get("FixedVersion")
                    else "No fix available",
                    raw=vuln,
                )
                findings.append(finding)

    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Warning: Could not parse Trivy results from {file_path}: {e}")

    return findings


def parse_gitleaks_results(file_path: Path) -> list[Finding]:
    """Parse Gitleaks JSON results."""
    findings = []

    try:
        with open(file_path) as f:
            data = json.load(f)

        if isinstance(data, list):
            for leak in data:
                finding = Finding(
                    scanner="Gitleaks",
                    severity="HIGH",  # Secrets are always high severity
                    title=f"Secret Detected: {leak.get('RuleID', 'Unknown')}",
                    description=leak.get("Description", "Potential secret or credential exposed"),
                    file_path=leak.get("File"),
                    line_number=leak.get("StartLine"),
                    remediation="Rotate the exposed credential immediately and remove from codebase",
                    raw=leak,
                )
                findings.append(finding)

    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Warning: Could not parse Gitleaks results from {file_path}: {e}")

    return findings


def parse_semgrep_results(file_path: Path) -> list[Finding]:
    """Parse Semgrep JSON results."""
    findings = []

    try:
        with open(file_path) as f:
            data = json.load(f)

        for result in data.get("results", []):
            severity_map = {
                "ERROR": "HIGH",
                "WARNING": "MEDIUM",
                "INFO": "LOW",
            }

            extra = result.get("extra", {})
            metadata = extra.get("metadata", {})

            finding = Finding(
                scanner="Semgrep",
                severity=severity_map.get(extra.get("severity", "INFO"), "LOW"),
                title=result.get("check_id", "Unknown Check"),
                description=extra.get("message", "No description"),
                file_path=result.get("path"),
                line_number=result.get("start", {}).get("line"),
                cwe=metadata.get("cwe"),
                remediation=metadata.get("fix"),
                raw=result,
            )
            findings.append(finding)

    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Warning: Could not parse Semgrep results from {file_path}: {e}")

    return findings


def parse_safety_results(file_path: Path) -> list[Finding]:
    """Parse Safety JSON results."""
    findings = []

    try:
        with open(file_path) as f:
            content = f.read()

        # Safety output might have multiple JSON objects
        for line in content.split("\n"):
            if line.strip().startswith("{"):
                try:
                    data = json.loads(line.strip())
                    for vuln in data.get("vulnerabilities", []):
                        finding = Finding(
                            scanner="Safety",
                            severity=vuln.get("severity", "UNKNOWN").upper(),
                            title=f"{vuln.get('vulnerability_id', 'Unknown')} in {vuln.get('package_name', 'unknown')}",
                            description=vuln.get("advisory", "No description"),
                            remediation=f"Update to version {vuln.get('analyzed_requirement', {}).get('specifier', 'N/A')}",
                            raw=vuln,
                        )
                        findings.append(finding)
                except json.JSONDecodeError:
                    continue

    except FileNotFoundError as e:
        print(f"Warning: Could not parse Safety results from {file_path}: {e}")

    return findings


def aggregate_results(input_dir: Path) -> ScanResults:
    """Aggregate results from all scanners."""
    results = ScanResults()
    results.scan_time = datetime.now(tz=UTC).isoformat()

    parsers = {
        "bandit": parse_bandit_results,
        "trivy": parse_trivy_results,
        "gitleaks": parse_gitleaks_results,
        "semgrep": parse_semgrep_results,
        "safety": parse_safety_results,
    }

    for file_path in input_dir.glob("*.json"):
        for scanner_name, parser in parsers.items():
            if scanner_name in file_path.name.lower():
                findings = parser(file_path)
                results.findings.extend(findings)
                if scanner_name not in results.scanners_run:
                    results.scanners_run.append(scanner_name)
                break

    # Calculate summary
    severity_counts: dict[str, int] = defaultdict(int)
    for finding in results.findings:
        severity_counts[finding.severity] += 1

    results.summary = dict(severity_counts)

    return results


def generate_json_report(results: ScanResults) -> dict[str, Any]:
    """Generate JSON report."""
    return {
        "metadata": {
            "generated_at": results.scan_time,
            "scanners": results.scanners_run,
            "total_findings": len(results.findings),
        },
        "summary": results.summary,
        "findings": [
            {
                "scanner": f.scanner,
                "severity": f.severity,
                "title": f.title,
                "description": f.description,
                "file_path": f.file_path,
                "line_number": f.line_number,
                "cwe": f.cwe,
                "remediation": f.remediation,
            }
            for f in results.findings
        ],
    }


def generate_markdown_report(results: ScanResults) -> str:
    """Generate Markdown report."""
    lines = [
        "# Security Scan Report",
        "",
        f"**Generated:** {results.scan_time}",
        f"**Scanners Run:** {', '.join(results.scanners_run)}",
        f"**Total Findings:** {len(results.findings)}",
        "",
        "## Summary",
        "",
        "| Severity | Count |",
        "|----------|-------|",
    ]

    severity_order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO", "UNKNOWN"]
    for severity in severity_order:
        if severity in results.summary:
            emoji = {
                "CRITICAL": "🔴",
                "HIGH": "🟠",
                "MEDIUM": "🟡",
                "LOW": "🟢",
                "INFO": "🔵",
            }.get(severity, "⚪")
            lines.append(f"| {emoji} {severity} | {results.summary[severity]} |")

    lines.extend(
        [
            "",
            "## Findings by Severity",
            "",
        ],
    )

    # Group findings by severity
    findings_by_severity: dict[str, list[Finding]] = defaultdict(list)
    for finding in results.findings:
        findings_by_severity[finding.severity].append(finding)

    for severity in severity_order:
        if severity not in findings_by_severity:
            continue

        lines.extend(
            [
                f"### {severity}",
                "",
            ],
        )

        for i, finding in enumerate(findings_by_severity[severity], 1):
            lines.extend(
                [
                    f"#### {i}. {finding.title}",
                    "",
                    f"- **Scanner:** {finding.scanner}",
                ],
            )

            if finding.file_path:
                location = finding.file_path
                if finding.line_number:
                    location += f":{finding.line_number}"
                lines.append(f"- **Location:** `{location}`")

            if finding.cwe:
                lines.append(f"- **CWE:** {finding.cwe}")

            lines.extend(
                [
                    "",
                    f"**Description:** {finding.description}",
                    "",
                ],
            )

            if finding.remediation:
                lines.extend(
                    [
                        f"**Remediation:** {finding.remediation}",
                        "",
                    ],
                )

    lines.extend(
        [
            "---",
            "",
            "## Recommendations",
            "",
            "1. **Critical/High Severity:** Address these issues immediately before deployment",
            "2. **Medium Severity:** Plan to fix in the next sprint",
            "3. **Low/Info Severity:** Review and address as time permits",
            "4. **Secrets:** Rotate any exposed credentials immediately",
            "5. **Dependencies:** Update vulnerable packages to patched versions",
            "",
            "## Next Steps",
            "",
            "- [ ] Review all findings with the security team",
            "- [ ] Create tickets for each issue to track remediation",
            "- [ ] Re-run scans after fixes to verify resolution",
            "- [ ] Update security baseline documentation",
            "",
        ],
    )

    return "\n".join(lines)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate consolidated security report from scanner results",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("./security-reports"),
        help="Directory containing scanner result files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output file path (extension determines format: .json or .md)",
    )
    parser.add_argument(
        "--format",
        choices=["json", "markdown", "both"],
        default="both",
        help="Output format",
    )
    parser.add_argument(
        "--fail-on",
        choices=["critical", "high", "medium", "low", "none"],
        default="none",
        help="Fail with exit code 1 if findings at this severity or higher exist",
    )

    args = parser.parse_args()

    if not args.input_dir.exists():
        print(f"Error: Input directory does not exist: {args.input_dir}")
        sys.exit(1)

    print(f"Scanning results in: {args.input_dir}")
    results = aggregate_results(args.input_dir)

    print(f"Found {len(results.findings)} total findings")
    print(f"Summary: {results.summary}")

    # Generate reports
    if args.output:
        output_base = args.output.stem
        output_dir = args.output.parent
    else:
        output_base = f"security-report-{datetime.now(tz=UTC).strftime('%Y%m%d')}"
        output_dir = args.input_dir

    if args.format in ("json", "both"):
        json_path = output_dir / f"{output_base}.json"
        with open(json_path, "w") as f:
            json.dump(generate_json_report(results), f, indent=2)
        print(f"JSON report saved to: {json_path}")

    if args.format in ("markdown", "both"):
        md_path = output_dir / f"{output_base}.md"
        with open(md_path, "w") as f:
            f.write(generate_markdown_report(results))
        print(f"Markdown report saved to: {md_path}")

    # Check fail conditions
    severity_levels = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    if args.fail_on != "none":
        fail_index = severity_levels.index(args.fail_on.upper())
        relevant_severities = severity_levels[: fail_index + 1]

        fail_count = sum(results.summary.get(s, 0) for s in relevant_severities)

        if fail_count > 0:
            print(
                f"\nError: Found {fail_count} findings at {args.fail_on.upper()} severity or higher",
            )
            sys.exit(1)

    print("\nReport generation complete!")


if __name__ == "__main__":
    main()
