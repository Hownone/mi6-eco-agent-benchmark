from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import click

from benchmark.config import BenchmarkConfig, DEFAULT_CASES_DIR
from benchmark.models import MutationType
from benchmark.top_resolver import resolve_top_module


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@click.group()
def main() -> None:
    pass


@main.command("build-case")
@click.option(
    "--rtl-dir",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Directory containing RTL source files",
)
@click.option(
    "--output-dir",
    required=True,
    type=click.Path(path_type=Path),
    help="Output case directory (e.g. /path/to/cases/my_design-r0)",
)
@click.option("--top-module", default=None, help="Top module name (auto-detected if not specified)")
@click.option(
    "--top-config",
    default=None,
    type=click.Path(exists=True, path_type=Path),
    help="Path to config.py with design_top",
)
@click.option("--clock-period", default=None, type=float, help="Override clock period in ns")
@click.option(
    "--model", default=None, help="LLM model override (e.g. openrouter/deepseek/deepseek-chat)"
)
@click.option("--no-copy-rtl", is_flag=True, help="Don't copy RTL files, create symlinks instead")
@click.option("-v", "--verbose", is_flag=True)
def build_case_cmd(
    rtl_dir: Path,
    output_dir: Path,
    top_module: str | None,
    top_config: Path | None,
    clock_period: float | None,
    model: str | None,
    no_copy_rtl: bool,
    verbose: bool,
) -> None:
    _setup_logging(verbose)

    config = BenchmarkConfig()
    if model:
        config.primary_model = model

    from benchmark.case_builder import build_case

    resolved_top = resolve_top_module(
        explicit_top=top_module,
        rtl_dir=rtl_dir,
        top_config=top_config,
    )

    try:
        analysis = asyncio.run(
            build_case(
                rtl_source_dir=rtl_dir,
                output_dir=output_dir,
                config=config,
                top_module=resolved_top,
                clock_period=clock_period,
                copy_rtl=not no_copy_rtl,
            )
        )
        click.echo(f"\nCase built: {output_dir}")
        click.echo(f"  Top module: {analysis.top_module.name}")
        click.echo(f"  Files: {len(analysis.file_order)}")
        click.echo(f"  Clocks: {[p.name for p in analysis.clock_ports]}")
        click.echo(f"  Resets: {[p.name for p in analysis.reset_ports]}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command("gen-variant")
@click.option(
    "--r0-dir",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to r0 case directory",
)
@click.option(
    "--output-dir", required=True, type=click.Path(path_type=Path), help="Output r1 case directory"
)
@click.option(
    "--mutation-type",
    default=None,
    type=click.Choice([m.value for m in MutationType], case_sensitive=False),
    help="ECO mutation type (auto-selected if not specified)",
)
@click.option("--top-module", default=None, help="Top module name override")
@click.option(
    "--top-config",
    default=None,
    type=click.Path(exists=True, path_type=Path),
    help="Path to config.py with design_top",
)
@click.option("--model", default=None, help="LLM model override")
@click.option("-v", "--verbose", is_flag=True)
def gen_variant_cmd(
    r0_dir: Path,
    output_dir: Path,
    mutation_type: str | None,
    top_module: str | None,
    top_config: Path | None,
    model: str | None,
    verbose: bool,
) -> None:
    _setup_logging(verbose)

    config = BenchmarkConfig()
    if model:
        config.primary_model = model

    mt = MutationType(mutation_type) if mutation_type else None

    from benchmark.variant_gen import generate_variant

    resolved_top = resolve_top_module(
        explicit_top=top_module,
        rtl_dir=r0_dir / "rtl",
        case_dir=r0_dir,
        top_config=top_config,
    )

    try:
        result_dir = asyncio.run(
            generate_variant(
                r0_case_dir=r0_dir,
                r1_output_dir=output_dir,
                config=config,
                mutation_type=mt,
                top_module=resolved_top,
            )
        )
        click.echo(f"\nr1 variant generated: {result_dir}")
        changelog = result_dir / "CHANGELOG.md"
        if changelog.exists():
            click.echo(f"\nChangelog:\n{changelog.read_text()}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command("validate")
@click.option(
    "--case-dir",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Case directory to validate",
)
@click.option("--require-signoff", is_flag=True, help="Require signoff data files")
@click.option("-v", "--verbose", is_flag=True)
def validate_cmd(
    case_dir: Path,
    require_signoff: bool,
    verbose: bool,
) -> None:
    _setup_logging(verbose)

    from benchmark.validator import validate_case

    result = validate_case(case_dir, require_signoff=require_signoff)

    if result.errors:
        click.echo(f"FAIL: {case_dir}")
        for err in result.errors:
            click.echo(f"  ERROR: {err}")
    else:
        click.echo(f"PASS: {case_dir}")

    for warn in result.warnings:
        click.echo(f"  WARN: {warn}")

    if not result.is_valid:
        sys.exit(1)


@main.command("batch-build")
@click.option(
    "--source-dir",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Directory containing multiple RTL subdirectories",
)
@click.option(
    "--output-dir",
    required=True,
    type=click.Path(path_type=Path),
    help="Output cases base directory",
)
@click.option("--model", default=None, help="LLM model override")
@click.option("-v", "--verbose", is_flag=True)
def batch_build_cmd(
    source_dir: Path,
    output_dir: Path,
    model: str | None,
    verbose: bool,
) -> None:
    _setup_logging(verbose)

    config = BenchmarkConfig()
    if model:
        config.primary_model = model

    from benchmark.case_builder import build_case

    hdl_extensions = {".v", ".sv", ".vhd", ".vhdl"}
    subdirs = sorted(
        [
            d
            for d in source_dir.iterdir()
            if d.is_dir()
            and any(f.suffix.lower() in hdl_extensions for f in d.rglob("*") if f.is_file())
        ]
    )

    if not subdirs:
        click.echo(f"No RTL directories found under {source_dir}", err=True)
        sys.exit(1)

    click.echo(f"Found {len(subdirs)} RTL directories")

    success = 0
    failed = 0
    for rtl_dir in subdirs:
        case_name = rtl_dir.name
        case_output = output_dir / f"{case_name}-r0"
        click.echo(f"\nBuilding: {case_name}")
        try:
            asyncio.run(
                build_case(
                    rtl_source_dir=rtl_dir,
                    output_dir=case_output,
                    config=config,
                )
            )
            click.echo(f"  OK: {case_output}")
            success += 1
        except Exception as e:
            click.echo(f"  FAIL: {e}", err=True)
            failed += 1

    click.echo(f"\nDone: {success} succeeded, {failed} failed")


if __name__ == "__main__":
    main()
