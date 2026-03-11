from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from benchmark.config import BenchmarkConfig
from benchmark.llm import call_llm, extract_json_from_response
from benchmark.models import (
    DesignAnalysis,
    MutationType,
    MUTATION_DESCRIPTIONS,
)
from benchmark.rtl_analyzer.hierarchy import analyze_design

logger = logging.getLogger(__name__)

VARIANT_SYSTEM_PROMPT = """\
You are an expert IC/ASIC RTL design engineer performing an ECO (Engineering Change Order) \
modification on existing Verilog/SystemVerilog/VHDL RTL code.

Your task: given the original RTL files and a mutation type, produce a MODIFIED version \
that represents a realistic ECO scenario. The change must be:
1. Functionally meaningful (not trivial comment changes)
2. Localized — affect 1-3 files maximum, typical for real ECO
3. Syntactically correct Verilog/SV/VHDL
4. Representative of what an engineer would actually change in that ECO category
5. Preserving the module interface (same top-level ports) unless the mutation type \
   explicitly requires interface changes

Return a JSON object with this exact structure:
{
  "mutation_type": "<type>",
  "summary": "<1-2 sentence description of what was changed and why>",
  "changed_files": [
    {
      "filename": "<file.v>",
      "description": "<what changed in this file>",
      "new_content": "<complete new file content>"
    }
  ],
  "unchanged_files": ["<file1.v>", "<file2.v>"]
}

CRITICAL: "new_content" must contain the COMPLETE file content (not a diff). \
The file must be syntactically valid and compilable."""


def _select_mutation_type(
    analysis: DesignAnalysis,
    requested: MutationType | None = None,
) -> MutationType:
    if requested:
        return requested

    has_fsm = False
    has_multi_clock = len(analysis.clock_ports) > 1

    for mod in analysis.all_modules.values():
        for p in mod.parameters:
            if "state" in p.lower():
                has_fsm = True
                break

    if has_multi_clock:
        return MutationType.CLOCK_DOMAIN_FIX
    if has_fsm:
        return MutationType.FSM_REFACTOR
    if len(analysis.all_modules) > 5:
        return MutationType.PIPELINE_INSERT
    return MutationType.BUG_FIX


def _build_variant_prompt(
    analysis: DesignAnalysis,
    rtl_contents: dict[str, str],
    mutation_type: MutationType,
) -> str:
    file_sections = []
    for fname, content in rtl_contents.items():
        line_count = content.count("\n") + 1
        file_sections.append(f"### {fname} ({line_count} lines)\n```verilog\n{content}\n```")

    files_text = "\n\n".join(file_sections)

    port_list = []
    for p in analysis.top_module.ports:
        width = f"[{p.msb}:{p.lsb}]" if p.width > 1 else ""
        port_list.append(f"  {p.direction.value} {width} {p.name}")

    hierarchy_lines = [f"Top: {analysis.top_module.name}"]
    for inst in analysis.top_module.instances:
        hierarchy_lines.append(f"  └─ {inst}")

    return f"""\
## Mutation Type: {mutation_type.value}
## Mutation Description: {MUTATION_DESCRIPTIONS[mutation_type]}

## Design Info
- Top module: {analysis.top_module.name}
- Modules: {', '.join(analysis.all_modules.keys())}
- Hierarchy:
{chr(10).join(hierarchy_lines)}

## Top Module Ports
{chr(10).join(port_list)}

## RTL Source Files
{files_text}

## Instructions
Apply a realistic {mutation_type.value} ECO change to this design. \
Follow the mutation description above. Change only what is necessary. \
Return the complete JSON response as specified in the system prompt."""


async def generate_variant(
    r0_case_dir: Path,
    r1_output_dir: Path,
    config: BenchmarkConfig,
    mutation_type: MutationType | None = None,
    top_module: str | None = None,
) -> Path:
    r0_case_dir = r0_case_dir.resolve()
    r1_output_dir = r1_output_dir.resolve()

    r0_rtl_dir = r0_case_dir / "rtl"
    if not r0_rtl_dir.exists():
        raise FileNotFoundError(f"r0 RTL directory not found: {r0_rtl_dir}")

    analysis = analyze_design(r0_rtl_dir, top_module)
    logger.info("Analyzed r0: top=%s, %d modules", analysis.top_module.name, len(analysis.all_modules))

    selected_mutation = _select_mutation_type(analysis, mutation_type)
    logger.info("Selected mutation type: %s", selected_mutation.value)

    rtl_contents: dict[str, str] = {}
    for f in analysis.file_order:
        rtl_contents[f.name] = f.read_text(encoding="utf-8", errors="ignore")

    user_prompt = _build_variant_prompt(analysis, rtl_contents, selected_mutation)

    raw_response = await call_llm(
        config=config,
        system_prompt=VARIANT_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.4,
        max_tokens=16384,
        json_mode=True,
    )

    logger.debug("LLM variant response length: %d", len(raw_response))

    result = extract_json_from_response(raw_response)

    r1_output_dir.mkdir(parents=True, exist_ok=True)
    r1_rtl_dir = r1_output_dir / "rtl"
    r1_rtl_dir.mkdir(parents=True, exist_ok=True)

    changed_files_info: list[dict[str, str]] = result.get("changed_files", [])
    unchanged_files: list[str] = result.get("unchanged_files", [])
    summary = result.get("summary", "No summary provided")

    changed_names = set()
    for cf in changed_files_info:
        fname = cf["filename"]
        new_content = cf["new_content"]
        changed_names.add(fname)
        (r1_rtl_dir / fname).write_text(new_content, encoding="utf-8")
        logger.info("Written modified file: %s", fname)

    for f in analysis.file_order:
        if f.name not in changed_names:
            shutil.copy2(f, r1_rtl_dir / f.name)

    for config_file in ["func.sdc", "load.tcl", "mi6.flist"]:
        src = r0_case_dir / config_file
        if src.exists():
            shutil.copy2(src, r1_output_dir / config_file)

    r0_design_dir = r0_case_dir / "design"
    if r0_design_dir.exists():
        r1_design_dir = r1_output_dir / "design"
        r1_design_dir.mkdir(parents=True, exist_ok=True)

        design_json_src = r0_design_dir / "design.json"
        if design_json_src.exists():
            shutil.copy2(design_json_src, r1_design_dir / "design.json")

        (r1_design_dir / "data").mkdir(parents=True, exist_ok=True)

    _write_changelog(
        r1_output_dir,
        selected_mutation,
        summary,
        changed_files_info,
        unchanged_files,
        analysis,
    )

    logger.info("r1 variant generated at %s", r1_output_dir)
    return r1_output_dir


def _write_changelog(
    output_dir: Path,
    mutation_type: MutationType,
    summary: str,
    changed_files: list[dict[str, str]],
    unchanged_files: list[str],
    analysis: DesignAnalysis,
) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        f"# ECO Variant Changelog",
        "",
        f"**Generated**: {timestamp}",
        f"**Base design**: {analysis.top_module.name}",
        f"**Mutation type**: `{mutation_type.value}`",
        f"**Category**: {MUTATION_DESCRIPTIONS[mutation_type].split('.')[0]}",
        "",
        "## Summary",
        "",
        summary,
        "",
        "## Changed Files",
        "",
    ]

    for cf in changed_files:
        lines.append(f"### `{cf['filename']}`")
        lines.append("")
        lines.append(cf.get("description", "No description"))
        lines.append("")

    if unchanged_files:
        lines.append("## Unchanged Files")
        lines.append("")
        for uf in unchanged_files:
            lines.append(f"- `{uf}`")
        lines.append("")

    lines.extend([
        "## Mutation Type Reference",
        "",
        f"> {MUTATION_DESCRIPTIONS[mutation_type]}",
        "",
    ])

    (output_dir / "CHANGELOG.md").write_text("\n".join(lines), encoding="utf-8")
    logger.info("Written CHANGELOG.md")
