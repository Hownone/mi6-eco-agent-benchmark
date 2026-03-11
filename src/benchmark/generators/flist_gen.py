from __future__ import annotations

from benchmark.models import DesignAnalysis


def generate_flist(analysis: DesignAnalysis) -> str:
    rtl_dir = analysis.rtl_dir_name
    if rtl_dir == ".":
        rtl_dir = "rtl"

    lines = [f"+incdir+${{MI6_PREFIX}}/{rtl_dir}"]

    for f in analysis.file_order:
        lines.append(f"${{MI6_PREFIX}}/{rtl_dir}/{f.name}")

    return "\n".join(lines) + "\n"
