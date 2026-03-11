from __future__ import annotations

from benchmark.models import DesignAnalysis, HDLType


def generate_load_tcl(analysis: DesignAnalysis) -> str:
    rtl_dir = analysis.rtl_dir_name
    if rtl_dir == ".":
        rtl_dir = "rtl"

    file_names = []
    for f in analysis.file_order:
        file_names.append(f.name)

    hdl_flag = "-sv"
    if analysis.hdl_type == HDLType.VHDL:
        hdl_flag = "-vhdl"

    files_str = " ".join(file_names)

    lines = [
        f"set_db init_hdl_search_path {{{rtl_dir}}}",
        "",
        f"read_hdl {hdl_flag} {files_str}",
        "",
    ]

    return "\n".join(lines)
