#!/usr/bin/env python3
"""
luavsg_diag.py (v3)

Purpose
-------
Brute-force repo intelligence for building a "master" CMakeLists.txt around
vendored dependencies.

Adds on top of v2:
- Per-lib "build entrypoints" discovery:
  - CMakeLists.txt (including nested: builds/cmake, cmake/, etc.)
  - Meson (meson.build), Autotools (configure.ac / configure), Makefile
  - Bazel (WORKSPACE, BUILD/BUILD.bazel), GN (BUILD.gn), Premake, etc.
  - pkg-config (*.pc, *.pc.in)
- "Key source markers" discovery:
  - common top-level headers: include/**, src/** (summary)
  - heuristic: look for main.c / main.cpp and library "entry" files
    (limited & non-invasive; does not parse the whole project)
- Improved "suggestions":
  - add_subdirectory candidate path (best CMakeLists location per lib)
  - -D<Pkg>_DIR hints (as before)

Usage
-----
  python luavsg_diag.py --repo .
  python luavsg_diag.py --repo . --auto-want
  python luavsg_diag.py --repo . --auto-want --json
  python luavsg_diag.py --repo . --auto-want --deep   (more scanning)

Notes
-----
- This tool is read-only: it does not modify your tree.
- For huge libs, --deep may take longer; default mode is conservative.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Hit:
    pkg: str
    path: Path


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class LibReport:
    name: str
    root: Path
    cmake_roots: List[str]
    other_build_files: List[str]
    pkg_config_files: List[str]
    example_mains: List[str]
    include_dirs: List[str]
    src_dirs: List[str]
    config_dir_suggestion: Optional[str]
    add_subdirectory_suggestion: Optional[str]


def _norm(p: Path) -> str:
    return str(p.resolve()).replace("\\", "/")


def _is_windows() -> bool:
    return platform.system().lower().startswith("win")


def _tmp_base() -> Path:
    if _is_windows():
        return Path(os.environ.get("TEMP") or os.environ.get("TMP") or "C:/Temp")
    return Path(os.environ.get("TMPDIR") or "/tmp")


def _infer_pkg_from_config_name(name: str) -> str:
    n = name
    if n.lower().endswith("-config.cmake"):
        n = n[: -len("-config.cmake")]
    elif n.lower().endswith("config.cmake"):
        # Preserve original casing before 'Config.cmake'
        n = n[: -len("Config.cmake")] if n.endswith("Config.cmake") else n[: -len("config.cmake")]
    return n


def _walk_configs(root: Path) -> List[Hit]:
    patterns = ("*Config.cmake", "*-config.cmake")
    hits: List[Hit] = []
    if not root.exists():
        return hits
    for pat in patterns:
        for p in root.rglob(pat):
            parts = {x.lower() for x in p.parts}
            if ".git" in parts or "cmakefiles" in parts:
                continue
            hits.append(Hit(pkg=_infer_pkg_from_config_name(p.name), path=p))
    return hits


def _best_config_dir(hits: Sequence[Hit], wanted: str) -> Optional[Path]:
    wanted_l = wanted.lower()
    candidates = [h.path.parent for h in hits if h.pkg.lower() == wanted_l]
    if not candidates:
        candidates = [
            h.path.parent
            for h in hits
            if wanted_l in h.pkg.lower() or wanted_l in h.path.name.lower()
        ]
    if not candidates:
        return None

    def score(p: Path) -> Tuple[int, int, int]:
        s = _norm(p).lower()
        good = int("/lib/" in s or "/lib64/" in s) + int("/cmake/" in s)
        bad = int("arm64" in s)
        return (good, -bad, -len(p.parts))

    return sorted(candidates, key=score, reverse=True)[0]


def _vulkan_sdk(repo: Path) -> Optional[Path]:
    env = os.environ.get("VULKAN_SDK")
    if env:
        p = Path(env)
        if p.exists():
            return p
    root = repo / "lib" / "VulkanSDK"
    if not root.exists():
        return None
    versions = [p for p in root.iterdir() if p.is_dir()]
    if not versions:
        return None
    versions.sort()
    return versions[-1]


def _vulkan_checks(vsdk: Path) -> List[Check]:
    inc = vsdk / "Include" / "vulkan" / "vulkan.h"
    lib = vsdk / "Lib" / "vulkan-1.lib"
    if not lib.exists():
        lib = vsdk / "Lib-ARM64" / "vulkan-1.lib"
    return [
        Check("VULKAN_SDK", True, _norm(vsdk)),
        Check("vulkan.h", inc.exists(), _norm(inc)),
        Check("vulkan-1.lib", lib.exists(), _norm(lib)),
    ]


def _collect_header_checks(repo: Path) -> List[Check]:
    lib = repo / "lib"
    return [
        Check(
            "glslang header (ShaderLang.h)",
            (lib / "glslang" / "glslang" / "Public" / "ShaderLang.h").exists(),
            _norm(lib / "glslang" / "glslang" / "Public" / "ShaderLang.h"),
        ),
        Check(
            "draco header (encode.h)",
            (lib / "draco" / "src" / "draco" / "compression" / "encode.h").exists(),
            _norm(lib / "draco" / "src" / "draco" / "compression" / "encode.h"),
        ),
        Check(
            "freetype header (freetype.h)",
            (lib / "freetype" / "include" / "freetype" / "freetype.h").exists(),
            _norm(lib / "freetype" / "include" / "freetype" / "freetype.h"),
        ),
        Check(
            "KTX header (ktx.h)",
            (lib / "KTX" / "include" / "KHR" / "ktx.h").exists(),
            _norm(lib / "KTX" / "include" / "KHR" / "ktx.h"),
        ),
        Check(
            "curl header (curl.h)",
            (lib / "curl" / "include" / "curl" / "curl.h").exists(),
            _norm(lib / "curl" / "include" / "curl" / "curl.h"),
        ),
    ]


def _in_source_build_artifacts(repo: Path) -> bool:
    return (repo / "CMakeCache.txt").exists() or (repo / "CMakeFiles").exists()


def _suggest_out_of_source(repo: Path) -> str:
    b = _tmp_base() / "luavsg_build"
    return f'cmake -S "{_norm(repo)}" -B "{_norm(b)}"'


def _lib_dirs(repo: Path) -> List[str]:
    root = repo / "lib"
    if not root.exists():
        return []
    return sorted([p.name for p in root.iterdir() if p.is_dir()], key=str.lower)


def _auto_want_from_lib_dirs(lib_dirs: Sequence[str]) -> List[str]:
    mapping = {
        "zlib": "ZLIB",
        "libpng": "PNG",
        "ktx": "Ktx",
        "vulkansdk": "Vulkan",
    }
    drop = {"lua", "vulkanscenegraph", "vsgxchange"}
    out: List[str] = []
    for d in lib_dirs:
        if d.lower() in drop:
            continue
        out.append(mapping.get(d.lower(), d))
    seen: set[str] = set()
    final: List[str] = []
    for x in out:
        xl = x.lower()
        if xl not in seen:
            seen.add(xl)
            final.append(x)
    return final


def _limited_rglob(root: Path, patterns: Sequence[str], max_hits: int) -> List[Path]:
    hits: List[Path] = []
    if not root.exists():
        return hits
    for pat in patterns:
        for p in root.rglob(pat):
            hits.append(p)
            if len(hits) >= max_hits:
                return hits
    return hits


def _find_build_entrypoints(lib_root: Path, deep: bool) -> Tuple[List[str], List[str], List[str]]:
    # CMake roots: directories containing CMakeLists.txt
    cmake_hits = _limited_rglob(lib_root, ["CMakeLists.txt"], 200 if deep else 40)
    cmake_dirs = sorted({_norm(p.parent) for p in cmake_hits}, key=str.lower)

    other = []
    other_files = [
        "meson.build",
        "configure",
        "configure.ac",
        "Makefile",
        "makefile",
        "BUILD.bazel",
        "BUILD",
        "WORKSPACE",
        "BUILD.gn",
        "premake5.lua",
        "CMakePresets.json",
    ]
    other_hits = _limited_rglob(lib_root, other_files, 200 if deep else 40)
    other = sorted({_norm(p) for p in other_hits}, key=str.lower)

    pc_hits = _limited_rglob(lib_root, ["*.pc", "*.pc.in"], 200 if deep else 40)
    pcs = sorted({_norm(p) for p in pc_hits}, key=str.lower)

    return cmake_dirs, other, pcs


def _find_source_markers(lib_root: Path, deep: bool) -> Tuple[List[str], List[str], List[str], List[str]]:
    # include/src directory presence (top 2 levels)
    include_dirs: List[str] = []
    src_dirs: List[str] = []
    for d in ("include", "Include", "inc"):
        p = lib_root / d
        if p.exists() and p.is_dir():
            include_dirs.append(_norm(p))
    for d in ("src", "Source", "sources", "lib"):
        p = lib_root / d
        if p.exists() and p.is_dir():
            src_dirs.append(_norm(p))

    # example mains: keep small; do not traverse entire tree unless deep
    mains = _limited_rglob(lib_root, ["main.c", "main.cpp", "main.cc"], 50 if deep else 10)
    mains_n = sorted({_norm(p) for p in mains}, key=str.lower)

    # heuristic entry files (limited)
    entry_patterns = ["*init*.c", "*init*.cpp", "*entry*.c", "*entry*.cpp"]
    entries = _limited_rglob(lib_root, entry_patterns, 30 if deep else 10)
    entries_n = sorted({_norm(p) for p in entries}, key=str.lower)

    return include_dirs, src_dirs, mains_n, entries_n


def _choose_add_subdirectory(cmake_dirs: Sequence[str], lib_root: Path) -> Optional[str]:
    # Prefer:
    # - <lib>/builds/cmake (freetype)
    # - <lib>/cmake
    # - <lib> (if it has CMakeLists)
    # - shortest path depth otherwise
    lr = _norm(lib_root).lower()

    def rel_score(d: str) -> Tuple[int, int]:
        dl = d.lower()
        good = 0
        if dl.endswith("/builds/cmake"):
            good += 50
        if dl.endswith("/cmake"):
            good += 25
        if dl == lr:
            good += 20
        # Prefer shallower dirs for add_subdirectory
        depth = dl.count("/")
        return (good, -depth)

    if not cmake_dirs:
        return None
    return sorted(list(cmake_dirs), key=rel_score, reverse=True)[0]


def _summarize_lib(repo: Path, lib_name: str, deep: bool, config_hits: Sequence[Hit]) -> LibReport:
    root = repo / "lib" / lib_name
    cmake_dirs, other_build, pcs = _find_build_entrypoints(root, deep=deep)
    include_dirs, src_dirs, mains, entries = _find_source_markers(root, deep=deep)

    # Suggest -D<Pkg>_DIR from config hits (if any), else None
    # Use directory name as wanted package by default.
    cfg_dir = _best_config_dir(config_hits, lib_name)

    add_subdir = _choose_add_subdirectory(cmake_dirs, root)

    # For reporting example entrypoints, include a couple of entries too.
    example_mains = (mains + entries)[:10]

    return LibReport(
        name=lib_name,
        root=root,
        cmake_roots=cmake_dirs[:30],
        other_build_files=other_build[:30],
        pkg_config_files=pcs[:30],
        example_mains=example_mains,
        include_dirs=include_dirs[:10],
        src_dirs=src_dirs[:10],
        config_dir_suggestion=_norm(cfg_dir) if cfg_dir else None,
        add_subdirectory_suggestion=add_subdir,
    )


def _summarize(repo: Path, vsdk: Optional[Path], hits: Sequence[Hit], want: Sequence[str], deep: bool) -> Dict[str, object]:
    data: Dict[str, object] = {}
    data["repo"] = _norm(repo)
    data["platform"] = platform.system().lower()
    data["python"] = sys.version.split()[0]
    data["in_source_build_artifacts"] = _in_source_build_artifacts(repo)
    data["suggested_out_of_source"] = _suggest_out_of_source(repo)
    data["lib_dirs"] = _lib_dirs(repo)

    if vsdk:
        data["vulkan"] = {c.name: {"ok": c.ok, "detail": c.detail} for c in _vulkan_checks(vsdk)}
    else:
        data["vulkan"] = {"VULKAN_SDK": {"ok": False, "detail": "missing"}}

    headers = _collect_header_checks(repo)
    data["headers"] = {c.name: {"ok": c.ok, "detail": c.detail} for c in headers}

    found: Dict[str, List[str]] = {}
    for h in hits:
        found.setdefault(h.pkg, []).append(_norm(h.path))
    data["configs_found"] = found

    missing: List[str] = []
    flags: List[str] = []
    for pkg in want:
        cfg = _best_config_dir(hits, pkg)
        if cfg is None:
            missing.append(pkg)
        else:
            flags.append(f'-D{pkg}_DIR="{_norm(cfg)}"')
    data["want"] = list(want)
    data["missing_configs"] = sorted(set(missing), key=str.lower)
    data["suggested_flags"] = flags

    # New: per-lib reports
    reports: List[Dict[str, object]] = []
    for lib_name in data["lib_dirs"]:
        lr = _summarize_lib(repo, lib_name, deep=deep, config_hits=hits)
        reports.append(
            {
                "name": lr.name,
                "root": _norm(lr.root),
                "add_subdirectory": lr.add_subdirectory_suggestion,
                "config_dir": lr.config_dir_suggestion,
                "cmake_roots": lr.cmake_roots,
                "other_build_files": lr.other_build_files,
                "pkg_config_files": lr.pkg_config_files,
                "include_dirs": lr.include_dirs,
                "src_dirs": lr.src_dirs,
                "example_entry_files": lr.example_mains,
            }
        )
    data["lib_reports"] = reports
    return data


def _print_human(data: Dict[str, object]) -> None:
    print(f"repo: {data['repo']}")
    print(f"platform: {data['platform']}")
    print(f"python: {data['python']}")
    if data.get("in_source_build_artifacts"):
        print("note: in-source build artifacts detected in repo root")
        print(f"recommended: {data['suggested_out_of_source']}")

    vulkan = data.get("vulkan", {})
    vsdk = vulkan.get("VULKAN_SDK", {}) if isinstance(vulkan, dict) else {}
    if isinstance(vsdk, dict) and vsdk.get("ok"):
        print(f"VULKAN_SDK: {vsdk.get('detail')}")
        for k in ("vulkan.h", "vulkan-1.lib"):
            d = vulkan.get(k, {})
            ok = "OK" if d.get("ok") else "MISSING"
            print(f"{k}: {ok} -> {d.get('detail')}")
    else:
        print("VULKAN_SDK: missing")

    lib_dirs = data.get("lib_dirs", [])
    if lib_dirs:
        print("\nlib folders:")
        print("  " + ", ".join(lib_dirs))

    miss_cfg = data.get("missing_configs", [])
    if miss_cfg:
        print("\nmissing Config.cmake (no config file found under repo/lib):")
        for m in miss_cfg:
            print(f"  - {m}")

    flags = data.get("suggested_flags", [])
    if flags:
        print("\nsuggested -D flags:")
        for f in flags:
            print(f"  {f}")

    reports = data.get("lib_reports", [])
    if isinstance(reports, list) and reports:
        print("\nlib build entrypoints (summary):")
        for r in reports:
            name = r.get("name")
            addsub = r.get("add_subdirectory")
            cfgdir = r.get("config_dir")
            cmake_roots = r.get("cmake_roots") or []
            other = r.get("other_build_files") or []
            pcs = r.get("pkg_config_files") or []
            print(f"\n[{name}]")
            if addsub:
                print(f"  add_subdirectory: {addsub}")
            if cfgdir:
                print(f"  config_dir:      {cfgdir}")
            if cmake_roots:
                print(f"  cmake_roots:     {len(cmake_roots)} (showing up to 3)")
                for x in cmake_roots[:3]:
                    print(f"    - {x}")
            if other:
                print(f"  other_build:     {len(other)} (showing up to 3)")
                for x in other[:3]:
                    print(f"    - {x}")
            if pcs:
                print(f"  pkg-config:      {len(pcs)} (showing up to 3)")
                for x in pcs[:3]:
                    print(f"    - {x}")
            entry = r.get("example_entry_files") or []
            if entry:
                print(f"  entry_files:     {len(entry)} (showing up to 2)")
                for x in entry[:2]:
                    print(f"    - {x}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="Path to luavsg repo root")
    ap.add_argument("--json", action="store_true", help="Emit JSON")
    ap.add_argument("--auto-want", action="store_true", help="Treat <repo>/lib directory names as wanted packages")
    ap.add_argument("--deep", action="store_true", help="Deeper scan (more hits; slower)")
    ap.add_argument(
        "--want",
        nargs="*",
        default=["glslang", "Ktx", "draco", "CURL", "Freetype"],
        help="Package names to look for (<Pkg>Config.cmake)",
    )
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve()
    if not repo.exists():
        print(f"error: repo not found: {repo}", file=sys.stderr)
        return 2

    hits = _walk_configs(repo / "lib")
    want = _auto_want_from_lib_dirs(_lib_dirs(repo)) if args.auto_want else list(args.want)
    vsdk = _vulkan_sdk(repo)

    data = _summarize(repo=repo, vsdk=vsdk, hits=hits, want=want, deep=args.deep)

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        _print_human(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
