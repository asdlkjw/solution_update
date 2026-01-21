# %% [markdown]
# # LaTeX -> SVG (inline) renderer (TeX Live + dvisvgm)
#
# Requirements (system):
# - latex (TeX Live)
# - dvisvgm
#
# macOS (brew):
#   brew install --cask mactex-no-gui
#   brew install dvisvgm
#
# Ubuntu:
#   sudo apt-get update
#   sudo apt-get install -y texlive-latex-base texlive-latex-recommended texlive-latex-extra dvisvgm
#
# Notes:
# - This pipeline supports \tabular, \multicolumn, \cline, etc. (true LaTeX output).
# - Output SVG can be embedded inline in HTML (no MathJax limitations).

# %%
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

# Progress bar (optional)
try:
    from tqdm.auto import tqdm
except Exception:
    tqdm = None

# %%
@dataclass(frozen=True)
class LatexToSvgConfig:
    latex_cmd: str = "latex"       # or "xelatex" (but then switch pipeline to pdf->svg)
    dvisvgm_cmd: str = "dvisvgm"
    cache_dir: Path = Path(".latex_svg_cache")
    dpi: int = 300                 # affects some font sizing; SVG is vector but dpi can influence some calculations
    font_format: str = "woff2"     # embed fonts
    no_fonts: bool = False         # if True, do not embed fonts (smaller output but may change appearance)
    sanitize: bool = True          # basic macro filtering (recommended if input is untrusted)
    timeout_sec: int = 30

# %%
_DEFAULT_PREAMBLE = r"""
\documentclass[preview,border=1pt]{standalone}
\usepackage{amsmath,amssymb}
\usepackage{array}
\usepackage{booktabs}
\usepackage{multirow}
\usepackage{xcolor}
\begin{document}
%s
\end{document}
""".strip()

# %%
class LatexToSvgError(RuntimeError):
    pass

# %%
def _which_or_raise(cmd: str) -> str:
    path = shutil.which(cmd)
    if not path:
        raise LatexToSvgError(
            f"Required command not found in PATH: {cmd}\n"
            f"- Install TeX Live (latex) and dvisvgm\n"
            f"- Then ensure `{cmd}` is available in your PATH"
        )
    return path

# %%
_DANGEROUS_LATEX_PATTERNS = [
    r"\\write18\b",        # shell escape
    r"\\input\b",
    r"\\include\b",
    r"\\openout\b",
    r"\\read\b",
    r"\\usepackage\s*\{.*shellesc.*\}",
    r"\\catcode\b",
]

def _basic_sanitize(latex_src: str) -> str:
    # This is NOT a perfect sandbox. For untrusted input, you must sandbox at OS/container level.
    for pat in _DANGEROUS_LATEX_PATTERNS:
        if re.search(pat, latex_src, flags=re.IGNORECASE):
            raise LatexToSvgError(f"Blocked potentially dangerous LaTeX pattern: {pat}")
    return latex_src

# %%
def _hash_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]

# %%
def latex_to_svg(
    latex_math_or_document_body: str,
    *,
    config: LatexToSvgConfig = LatexToSvgConfig(),
    wrap_display_math: bool = True,
    extra_preamble_packages: Optional[str] = None,
) -> str:
    r"""
    Convert LaTeX (math or body) into SVG using latex -> dvi -> dvisvgm.

    Parameters
    ----------
    latex_math_or_document_body:
        If wrap_display_math=True, this is treated as math/body and wrapped with \[ ... \].
        If wrap_display_math=False, you can pass full LaTeX body content.
    wrap_display_math:
        True: wrap with \[ ... \]
        False: take input as-is as body content
    extra_preamble_packages:
        Extra LaTeX preamble lines (e.g., \\usepackage{...})

    Returns
    -------
    svg_str: str
        SVG content as a string (suitable for inline embedding)
    """
    _which_or_raise(config.latex_cmd)
    _which_or_raise(config.dvisvgm_cmd)

    config.cache_dir.mkdir(parents=True, exist_ok=True)

    body = latex_math_or_document_body
    if config.sanitize:
        body = _basic_sanitize(body)

    if wrap_display_math:
        body = r"\[" + "\n" + body + "\n" + r"\]"

    preamble = _DEFAULT_PREAMBLE
    if extra_preamble_packages:
        # inject right before \begin{document}
        preamble = preamble.replace(r"\begin{document}", extra_preamble_packages + "\n" + r"\begin{document}")

    tex_src = preamble % body

    key = _hash_key(tex_src + f"|dpi={config.dpi}|fonts={config.font_format}|nofonts={config.no_fonts}")
    cached_svg = config.cache_dir / f"{key}.svg"
    if cached_svg.exists():
        return cached_svg.read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tex_path = tmp / "input.tex"
        tex_path.write_text(tex_src, encoding="utf-8")

        # latex -> dvi
        # -halt-on-error: stop at first error
        # -interaction=nonstopmode: no interactive prompts
        latex_cmd = [
            config.latex_cmd,
            "-halt-on-error",
            "-interaction=nonstopmode",
            tex_path.name,
        ]
        try:
            p1 = subprocess.run(
                latex_cmd,
                cwd=tmp,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=config.timeout_sec,
                check=False,
                text=True,
            )
        except subprocess.TimeoutExpired as e:
            raise LatexToSvgError(f"LaTeX timed out after {config.timeout_sec}s") from e

        if p1.returncode != 0:
            log = (tmp / "input.log").read_text(encoding="utf-8", errors="ignore") if (tmp / "input.log").exists() else p1.stdout
            raise LatexToSvgError(f"LaTeX compile failed.\n--- LaTeX output/log ---\n{log[-4000:]}")

        dvi_path = tmp / "input.dvi"
        if not dvi_path.exists():
            raise LatexToSvgError("Expected DVI not found (input.dvi). LaTeX compile may have failed unexpectedly.")

        # dvi -> svg
        dvisvgm_cmd = [
            config.dvisvgm_cmd,
            dvi_path.name,
            "-n",  # no font paths in output (cleaner)
            "-o", "output.svg",
        ]

        try:
            p2 = subprocess.run(
                dvisvgm_cmd,
                cwd=tmp,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=config.timeout_sec,
                check=False,
                text=True,
            )
        except subprocess.TimeoutExpired as e:
            raise LatexToSvgError(f"dvisvgm timed out after {config.timeout_sec}s") from e

        out_svg = tmp / "output.svg"
        if p2.returncode != 0 or not out_svg.exists():
            raise LatexToSvgError(f"dvisvgm failed.\n--- dvisvgm output ---\n{p2.stdout[-4000:]}")

        svg_str = out_svg.read_text(encoding="utf-8")

    cached_svg.write_text(svg_str, encoding="utf-8")
    return svg_str

# %%
def svg_inline_html(svg_str: str, *, max_width_px: Optional[int] = None) -> str:
    """
    Wrap SVG string into a div for inline embedding in HTML.
    """
    style = []
    if max_width_px is not None:
        style.append(f"max-width:{int(max_width_px)}px;")
        style.append("height:auto;")
    style_attr = f' style="{" ".join(style)}"' if style else ""
    return f'<div{style_attr}>{svg_str}</div>'


# %% [markdown]
# ## Example: your synthetic division / tabular with multicolumn + cline (works in true LaTeX)

# %%
latex_body = r"""
\[
\begin{tabular}{c|rrrr}
$\frac{1}{2}$ & 2 & 3 & -4 & 1 \\
\multicolumn{1}{r}{} &  & 1 & 2 & -1 \\
\cline{2-5}
\multicolumn{1}{r}{} & 2 & 4 & -2 & 0
\end{tabular}
\]
"""

svg = latex_to_svg(latex_body, wrap_display_math=False)
len(svg), svg[:200]

# %% [markdown]
# ## Batch conversion with progress bar (tqdm)

# %%
import re

def add_white_background(svg: str) -> str:
    # <svg ...> 태그 끝 위치를 찾아 그 다음에 rect 삽입
    m = re.search(r"<svg\b[^>]*>", svg)
    if not m:
        return svg

    svg_open_tag = m.group(0)

    # viewBox 있으면 그 좌표/크기로 rect를 맞추고, 없으면 100% 사용
    vb = re.search(r'viewBox="([^"]+)"', svg_open_tag)
    if vb:
        x, y, w, h = vb.group(1).split()
        rect = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="white"/>'
    else:
        rect = '<rect x="0" y="0" width="100%" height="100%" fill="white"/>'

    insert_pos = m.end()
    return svg[:insert_pos] + "\n" + rect + "\n" + svg[insert_pos:]


def batch_latex_to_svg(
    latex_list: Sequence[str],
    *,
    config: LatexToSvgConfig = LatexToSvgConfig(),
    wrap_display_math: bool = True,
    show_progress: bool = True,
) -> list[str]:
    iterator: Iterable[str] = latex_list
    if show_progress and tqdm is not None:
        iterator = tqdm(latex_list, desc="Rendering LaTeX -> SVG")

    out = []
    for s in iterator:
        out.append(latex_to_svg(s, config=config, wrap_display_math=wrap_display_math))
    return out

# Example batch:
samples = [
    r"\frac{a}{b}",
    r"\begin{tabular}{c|cc} \rm{x} & 1 & 2\\ \cline{2-3} & 3 & 4 \end{tabular}",
]

svgs = batch_latex_to_svg(samples, wrap_display_math=True, show_progress=True)
# display(HTML(svg_inline_html(svgs[1], max_width_px=600)))

out_dir = Path("out_svgs")
out_dir.mkdir(exist_ok=True)

for i, svg in enumerate(svgs, 1):
    p = out_dir / f"{i:03d}.svg"
    # svg = add_white_background(svg)
    p.write_text(svg, encoding="utf-8")

print(f"Saved {len(svgs)} SVGs to {out_dir.resolve()}")
