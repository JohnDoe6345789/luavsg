#!/usr/bin/env python3
"""
luavsg_diag.py (v2)

What it detects:
- Any *Config.cmake / *-config.cmake under <repo>/lib (always).
- Vulkan SDK (env or vendored) + vulkan.h + vulkan-1.lib (Windows).
- A small set of "known header markers" (glslang/draco/freetype/KTX/curl).

How "does it detect all these lib folders?":
- The script can auto-populate a "wanted packages" list from the directory names
  under <repo>/lib via --auto-want. It then reports which of those have a
  Config.cmake and suggests -D<Pkg>_DIR where possible.

Usage:
  python luavsg_diag.py --repo .
  python luavsg_diag.py --repo . --auto-want
  python luavsg_diag.py --repo . --auto-want --json
  python luavsg_diag.py --repo . --want ZLIB PNG nghttp2

Notes:
- Many libraries vendored as source won't have a Config.cmake until built or
  installed. That is normal (e.g., curl deps: brotli, zlib, zstd, nghttp2, etc.).
- Out-of-source build is recommended (freetype forbids top-level in-source).
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
        n = n[: -len("Config.cmake")]
        n = n[: -len("config.cmake")] if n.lower().endswith("config.cmake") else n
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
        bad = int("arm64" in s)  # prefer non-arm64
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
    # Directory name != CMake package name sometimes.
    mapping = {
        "zlib": "ZLIB",
        "libpng": "PNG",
        "ktx": "Ktx",
        "vulkansdk": "Vulkan",
    }
    out: List[str] = []
    for d in lib_dirs:
        key = d.lower()
        out.append(mapping.get(key, d))
    # Remove obvious non-deps / meta folders.
    drop = {"lua", "vulkanscenegraph", "vsgxchange"}
    out = [x for x in out if x.lower() not in drop]
    # De-dupe preserving order.
    seen: set[str] = set()
    final: List[str] = []
    for x in out:
        xl = x.lower()
        if xl not in seen:
            seen.add(xl)
            final.append(x)
    return final


def _summarize(
    repo: Path,
    vsdk: Optional[Path],
    hits: Sequence[Hit],
    want: Sequence[str],
) -> Dict[str, object]:
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="Path to luavsg repo root")
    ap.add_argument("--json", action="store_true", help="Emit JSON")
    ap.add_argument("--auto-want", action="store_true", help="Treat <repo>/lib directory names as wanted packages")
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
    data = _summarize(repo=repo, vsdk=vsdk, hits=hits, want=want)

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        _print_human(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
