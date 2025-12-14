#!/usr/bin/env python3
"""luavsg_tools_codegen.py

Creates a new folder containing a CMake dependency diagnostic script.

User preferences respected:
- Single-file codegen tool in-chat (avoids multi-file canvas output).
- Does NOT modify the current working folder; creates a new output folder.

Run:
  python luavsg_tools_codegen.py --repo "C:/Users/richa/GitHub/luavsg"

Output:
  <cwd>/luavsg_tools_out_<timestamp>/luavsg_diag.py

Then:
  python <out>/luavsg_diag.py --repo "C:/Users/richa/GitHub/luavsg"
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True)
class FileCheck:
    label: str
    path: Path


@dataclass(frozen=True)
class ConfigSearch:
    label: str
    roots: tuple[Path, ...]
    patterns: tuple[str, ...]


def _now_stamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=False)


def _read_text(p: Path, limit: int = 200_000) -> str:
    try:
        data = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(data) > limit:
        return data[:limit] + "\n...<truncated>\n"
    return data


def _find_first(root: Path, rel_candidates: Iterable[str]) -> Optional[Path]:
    for rel in rel_candidates:
        cand = (root / rel).resolve()
        if cand.exists():
            return cand
    return None


def _glob_any(roots: Iterable[Path], patterns: Iterable[str]) -> list[Path]:
    hits: list[Path] = []
    for r in roots:
        if not r.exists():
            continue
        for pat in patterns:
            hits.extend(sorted(r.glob(pat)))
    # de-dupe while preserving order
    seen: set[Path] = set()
    out: list[Path] = []
    for h in hits:
        hr = h.resolve()
        if hr not in seen:
            seen.add(hr)
            out.append(hr)
    return out


def _is_windows() -> bool:
    return os.name == "nt"


def _cmake_cache_path(repo: Path) -> Optional[Path]:
    # Your current workflow uses in-source cmake '.', so CMakeCache.txt is at repo
    cache = (repo / "CMakeCache.txt")
    if cache.exists():
        return cache
    # Fallback: conventional out-of-source build
    for rel in ("build/CMakeCache.txt", "build/app/CMakeCache.txt"):
        p = (repo / rel)
        if p.exists():
            return p
    return None


def _parse_cache_vars(cache_text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in cache_text.splitlines():
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        # Format: KEY:TYPE=VALUE
        if ":" not in line or "=" not in line:
            continue
        key_type, value = line.split("=", 1)
        key = key_type.split(":", 1)[0].strip()
        out[key] = value.strip()
    return out


def _suggest_dir_var(name: str, config_hits: list[Path]) -> Optional[str]:
    # CMake expects <Pkg>_DIR set to the directory containing <Pkg>Config.cmake
    if not config_hits:
        return None
    # If the hit is the config file itself, set DIR to parent.
    p = config_hits[0]
    dirp = p.parent if p.is_file() else p
    return f"-D{name}_DIR=\"{dirp.as_posix()}\""


def _print_kv(title: str, items: list[tuple[str, str]]) -> None:
    print(f"\n== {title} ==")
    if not items:
        print("(none)")
        return
    w = max(len(k) for k, _ in items)
    for k, v in items:
        print(f"{k.ljust(w)} : {v}")


def _print_section(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def _status(ok: bool) -> str:
    return "OK" if ok else "MISSING"


def _detect_vulkan_sdk(repo: Path) -> Optional[Path]:
    env = os.environ.get("VULKAN_SDK", "").strip()
    if env:
        p = Path(env)
        if p.exists():
            return p

    vend = repo / "lib" / "VulkanSDK"
    if not vend.exists():
        return None

    versions = sorted([p for p in vend.iterdir() if p.is_dir()])
    if not versions:
        return None

    # Prefer lexicographically last (usually highest version)
    return versions[-1]


def _detect_vulkan_import_lib(vulkan_sdk: Path) -> Optional[Path]:
    if not _is_windows():
        return None

    candidates = [
        vulkan_sdk / "Lib" / "vulkan-1.lib",
        vulkan_sdk / "Lib" / "x64" / "vulkan-1.lib",
        vulkan_sdk / "Lib-ARM64" / "vulkan-1.lib",
        vulkan_sdk / "Lib-ARM64" / "arm64" / "vulkan-1.lib",
    ]
    return _find_first(Path("/"), [c.as_posix().lstrip("/") for c in candidates])


def _config_searches(repo: Path) -> list[tuple[str, ConfigSearch]]:
    # These match the errors you posted.
    return [
        (
            "glslang",
            ConfigSearch(
                label="glslang",
                roots=(repo / "lib" / "glslang", repo / "lib"),
                patterns=(
                    "**/glslangConfig.cmake",
                    "**/glslang-config.cmake",
                    "**/glslangConfigVersion.cmake",
                ),
            ),
        ),
        (
            "draco",
            ConfigSearch(
                label="draco",
                roots=(repo / "lib" / "draco", repo / "lib"),
                patterns=(
                    "**/dracoConfig.cmake",
                    "**/draco-config.cmake",
                ),
            ),
        ),
        (
            "Ktx",
            ConfigSearch(
                label="Ktx",
                roots=(repo / "lib" / "KTX", repo / "lib"),
                patterns=(
                    "**/KtxConfig.cmake",
                    "**/ktx-config.cmake",
                    "**/ktxConfig.cmake",
                    "**/KTXConfig.cmake",
                ),
            ),
        ),
        (
            "CURL",
            ConfigSearch(
                label="CURL",
                roots=(repo / "lib" / "curl", repo / "lib"),
                patterns=(
                    "**/CURLConfig.cmake",
                    "**/curl-config.cmake",
                    "**/curlConfig.cmake",
                ),
            ),
        ),
        (
            "Freetype",
            ConfigSearch(
                label="Freetype",
                roots=(repo / "lib" / "freetype", repo / "lib"),
                patterns=(
                    "**/freetype-config.cmake",
                    "**/FreetypeConfig.cmake",
                    "**/freetypeConfig.cmake",
                ),
            ),
        ),
    ]


def _header_checks(repo: Path) -> list[FileCheck]:
    return [
        FileCheck(
            label="Vulkan header",
            path=(repo / "lib" / "VulkanSDK"),
        ),
        FileCheck(
            label="glslang header (glslang/Public/ShaderLang.h)",
            path=(repo / "lib" / "glslang" / "glslang" / "Public" / "ShaderLang.h"),
        ),
        FileCheck(
            label="draco header (draco/compression/encode.h)",
            path=(repo / "lib" / "draco" / "src" / "draco" / "compression" / "encode.h"),
        ),
        FileCheck(
            label="freetype header (include/freetype/freetype.h)",
            path=(repo / "lib" / "freetype" / "include" / "freetype" / "freetype.h"),
        ),
        FileCheck(
            label="KTX header (include/KHR/ktx.h)",
            path=(repo / "lib" / "KTX" / "include" / "KHR" / "ktx.h"),
        ),
        FileCheck(
            label="curl header (include/curl/curl.h)",
            path=(repo / "lib" / "curl" / "include" / "curl" / "curl.h"),
        ),
    ]


def run(repo: Path, json_out: bool) -> int:
    _print_section("luavsg diagnostic")
    print(f"Repo           : {repo.as_posix()}")
    print(f"Platform       : {'Windows' if _is_windows() else os.name}")
    print(f"Python         : {'.'.join(map(str, (3,)))}")

    results: dict[str, object] = {
        "repo": repo.as_posix(),
        "platform": "windows" if _is_windows() else os.name,
        "checks": {},
        "config_hits": {},
        "suggestions": {},
        "cmake_cache": {},
    }

    vulkan_sdk = _detect_vulkan_sdk(repo)
    if vulkan_sdk is None:
        print("VULKAN_SDK      : MISSING")
        results["checks"]["VULKAN_SDK"] = None
    else:
        print(f"VULKAN_SDK      : {vulkan_sdk.as_posix()}")
        results["checks"]["VULKAN_SDK"] = vulkan_sdk.as_posix()

        vk_header = vulkan_sdk / "Include" / "vulkan" / "vulkan.h"
        vk_lib = _detect_vulkan_import_lib(vulkan_sdk)

        print(f"vulkan.h        : {_status(vk_header.exists())} ({vk_header.as_posix()})")
        results["checks"]["vulkan_h"] = vk_header.as_posix() if vk_header.exists() else None

        if vk_lib is None:
            print("vulkan-1.lib    : MISSING")
            results["checks"]["vulkan_1_lib"] = None
        else:
            print(f"vulkan-1.lib    : OK ({vk_lib.as_posix()})")
            results["checks"]["vulkan_1_lib"] = vk_lib.as_posix()

    _print_section("Header presence (vendored trees)")
    header_items: list[tuple[str, str]] = []
    for chk in _header_checks(repo):
        ok = chk.path.exists()
        header_items.append((chk.label, f"{_status(ok)} -> {chk.path.as_posix()}"))
        results["checks"][chk.label] = chk.path.as_posix() if ok else None
    _print_kv("Headers", header_items)

    _print_section("CMake config discovery")
    suggestions: list[tuple[str, str]] = []
    for pkg_name, search in _config_searches(repo):
        hits = _glob_any(search.roots, search.patterns)
        results["config_hits"][pkg_name] = [p.as_posix() for p in hits]
        print(f"\n[{pkg_name}] searched roots:")
        for r in search.roots:
            print(f"  - {r.as_posix()}")
        if not hits:
            print("  hits: (none)")
        else:
            print("  hits:")
            for h in hits[:20]:
                print(f"    - {h.as_posix()}")
            if len(hits) > 20:
                print(f"    ... ({len(hits) - 20} more)")

        sug = _suggest_dir_var(pkg_name, hits)
        if sug is not None:
            suggestions.append((pkg_name, sug))
            results["suggestions"][pkg_name] = sug

    _print_section("CMake cache snapshot")
    cache_path = _cmake_cache_path(repo)
    if cache_path is None:
        print("CMakeCache.txt  : (not found)")
    else:
        print(f"CMakeCache.txt  : {cache_path.as_posix()}")
        cache_vars = _parse_cache_vars(_read_text(cache_path))
        keep = [
            "CMAKE_GENERATOR",
            "CMAKE_GENERATOR_PLATFORM",
            "CMAKE_CXX_COMPILER",
            "VULKAN_SDK",
            "Vulkan_INCLUDE_DIR",
            "Vulkan_LIBRARY",
            "glslang_DIR",
            "draco_DIR",
            "Ktx_DIR",
            "CURL_DIR",
            "Freetype_DIR",
        ]
        cache_items: list[tuple[str, str]] = []
        for k in keep:
            if k in cache_vars:
                cache_items.append((k, cache_vars[k]))
        results["cmake_cache"] = {k: cache_vars.get(k, "") for k in keep}
        _print_kv("Selected cache variables", cache_items)

    _print_section("Suggested configure flags")
    if suggestions:
        for _, s in suggestions:
            print(s)
    else:
        print("(none)")

    _print_section("Interpretation")
    print(
        "- If config hits are empty, that dependency has not been built/installed yet.\n"
        "- If headers exist but config is missing, you likely have source only; build the\n"
        "  dependency to produce <Pkg>Config.cmake (or disable that plugin).\n"
        "- For VSG: glslang missing only disables shader compilation helpers.\n"
        "- For vsgXchange: draco/ktx/curl/freetype missing disables related import paths.\n"
        "  You can keep LUAVSG_VSGXCHANGE_MINIMAL=ON to avoid chasing them early.\n"
    )

    if json_out:
        out = json.dumps(results, indent=2)
        print("\n" + out)

    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--repo",
        required=True,
        help="Path to luavsg repo (e.g. C:/Users/richa/GitHub/luavsg)",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Also print JSON report to stdout",
    )
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    if not repo.exists():
        raise SystemExit(f"Repo not found: {repo}")

    return run(repo=repo, json_out=bool(args.json))


if __name__ == "__main__":
    raise SystemExit(main())


# -----------------------------------------------------------------------------
# Embedded output file(s)
# -----------------------------------------------------------------------------

DIAG_SCRIPT = r'''#!/usr/bin/env python3
"""luavsg_diag.py

Standalone diagnostics for luavsg CMake dependency discovery.

Why this exists:
- CMake's find_package() errors can be noisy; this script summarizes what you
  actually have in-tree (headers) vs what is missing (Config.cmake / .lib).

Usage:
  python luavsg_diag.py --repo "C:/Users/richa/GitHub/luavsg"
  python luavsg_diag.py --repo . --json
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True)
class ConfigSearch:
    roots: tuple[Path, ...]
    patterns: tuple[str, ...]


def _glob_any(roots: Iterable[Path], patterns: Iterable[str]) -> list[Path]:
    hits: list[Path] = []
    for r in roots:
        if not r.exists():
            continue
        for pat in patterns:
            hits.extend(sorted(r.glob(pat)))
    seen: set[Path] = set()
    out: list[Path] = []
    for h in hits:
        hr = h.resolve()
        if hr not in seen:
            seen.add(hr)
            out.append(hr)
    return out


def _find_first(root: Path, rel_candidates: Iterable[str]) -> Optional[Path]:
    for rel in rel_candidates:
        cand = (root / rel).resolve()
        if cand.exists():
            return cand
    return None


def _is_windows() -> bool:
    return os.name == "nt"


def _detect_vulkan_sdk(repo: Path) -> Optional[Path]:
    env = os.environ.get("VULKAN_SDK", "").strip()
    if env:
        p = Path(env)
        if p.exists():
            return p

    vend = repo / "lib" / "VulkanSDK"
    if not vend.exists():
        return None

    versions = sorted([p for p in vend.iterdir() if p.is_dir()])
    if not versions:
        return None
    return versions[-1]


def _detect_vulkan_import_lib(vulkan_sdk: Path) -> Optional[Path]:
    if not _is_windows():
        return None

    candidates = [
        vulkan_sdk / "Lib" / "vulkan-1.lib",
        vulkan_sdk / "Lib" / "x64" / "vulkan-1.lib",
        vulkan_sdk / "Lib-ARM64" / "vulkan-1.lib",
        vulkan_sdk / "Lib-ARM64" / "arm64" / "vulkan-1.lib",
    ]
    return _find_first(Path("/"), [c.as_posix().lstrip("/") for c in candidates])


def _searches(repo: Path) -> dict[str, ConfigSearch]:
    return {
        "glslang": ConfigSearch(
            roots=(repo / "lib" / "glslang", repo / "lib"),
            patterns=(
                "**/glslangConfig.cmake",
                "**/glslang-config.cmake",
                "**/glslangConfigVersion.cmake",
            ),
        ),
        "draco": ConfigSearch(
            roots=(repo / "lib" / "draco", repo / "lib"),
            patterns=("**/dracoConfig.cmake", "**/draco-config.cmake"),
        ),
        "Ktx": ConfigSearch(
            roots=(repo / "lib" / "KTX", repo / "lib"),
            patterns=(
                "**/KtxConfig.cmake",
                "**/ktx-config.cmake",
                "**/ktxConfig.cmake",
                "**/KTXConfig.cmake",
            ),
        ),
        "CURL": ConfigSearch(
            roots=(repo / "lib" / "curl", repo / "lib"),
            patterns=(
                "**/CURLConfig.cmake",
                "**/curl-config.cmake",
                "**/curlConfig.cmake",
            ),
        ),
        "Freetype": ConfigSearch(
            roots=(repo / "lib" / "freetype", repo / "lib"),
            patterns=(
                "**/freetype-config.cmake",
                "**/FreetypeConfig.cmake",
                "**/freetypeConfig.cmake",
            ),
        ),
    }


def _header_checks(repo: Path) -> dict[str, Path]:
    return {
        "glslang header": repo
        / "lib"
        / "glslang"
        / "glslang"
        / "Public"
        / "ShaderLang.h",
        "draco header": repo
        / "lib"
        / "draco"
        / "src"
        / "draco"
        / "compression"
        / "encode.h",
        "freetype header": repo / "lib" / "freetype" / "include" / "freetype" / "freetype.h",
        "KTX header": repo / "lib" / "KTX" / "include" / "KHR" / "ktx.h",
        "curl header": repo / "lib" / "curl" / "include" / "curl" / "curl.h",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    if not repo.exists():
        raise SystemExit(f"Repo not found: {repo}")

    report: dict[str, object] = {
        "repo": repo.as_posix(),
        "platform": "windows" if os.name == "nt" else os.name,
        "vulkan_sdk": None,
        "vulkan_h": None,
        "vulkan_1_lib": None,
        "headers": {},
        "configs": {},
        "suggest_flags": {},
    }

    vulkan_sdk = _detect_vulkan_sdk(repo)
    if vulkan_sdk is not None:
        report["vulkan_sdk"] = vulkan_sdk.as_posix()
        vk_h = vulkan_sdk / "Include" / "vulkan" / "vulkan.h"
        vk_lib = _detect_vulkan_import_lib(vulkan_sdk)
        report["vulkan_h"] = vk_h.as_posix() if vk_h.exists() else None
        report["vulkan_1_lib"] = vk_lib.as_posix() if vk_lib is not None else None

    for label, hp in _header_checks(repo).items():
        report["headers"][label] = hp.as_posix() if hp.exists() else None

    for pkg, search in _searches(repo).items():
        hits = _glob_any(search.roots, search.patterns)
        report["configs"][pkg] = [h.as_posix() for h in hits]
        if hits:
            report["suggest_flags"][pkg] = f"-D{pkg}_DIR=\"{hits[0].parent.as_posix()}\""

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print("luavsg dependency diagnostic")
    print(f"Repo: {report['repo']}")
    print(f"VULKAN_SDK: {report['vulkan_sdk']}")
    print(f"vulkan.h: {report['vulkan_h']}")
    print(f"vulkan-1.lib: {report['vulkan_1_lib']}")

    print("\nHeaders:")
    for k, v in report["headers"].items():
        print(f"- {k}: {'OK' if v else 'MISSING'}")

    print("\nCMake Config hits:")
    for k, v in report["configs"].items():
        print(f"- {k}: {'OK' if v else 'MISSING'}")
        if v:
            print(f"  {v[0]}")

    print("\nSuggested -D flags (only if config found):")
    for k, v in report["suggest_flags"].items():
        print(v)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _emit_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def _write_outputs(base: Path) -> None:
    diag = base / "luavsg_diag.py"
    _emit_file(diag, DIAG_SCRIPT)


def _codegen_main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--repo",
        required=False,
        default=".",
        help="Repo path only used for convenience in README content",
    )
    args = ap.parse_args()

    out_dir = Path.cwd() / f"luavsg_tools_out_{_now_stamp()}"
    _safe_mkdir(out_dir)
    _write_outputs(out_dir)

    # Small readme for convenience.
    readme = out_dir / "README.txt"
    _emit_file(
        readme,
        "\n".join(
            [
                "luavsg tools output",
                "",
                f"Repo used: {Path(args.repo).expanduser().resolve().as_posix()}",
                "",
                "Run diagnostics:",
                "  python luavsg_diag.py --repo <path-to-luavsg>",
                "  python luavsg_diag.py --repo <path-to-luavsg> --json",
                "",
            ]
        ),
    )

    print(out_dir.as_posix())
    return 0


if __name__ == "__main__":
    # If invoked directly, behave as codegen tool.
    raise SystemExit(_codegen_main())
