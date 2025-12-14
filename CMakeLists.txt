cmake_minimum_required(VERSION 3.24)

# Modern find_package() behavior for <PackageName>_ROOT hints.
cmake_policy(SET CMP0074 NEW)

# Some vendored projects still use legacy FindPythonInterp/FindPythonLibs.
# With CMake 4.x this can warn; setting OLD preserves compatibility.
if(POLICY CMP0148)
  cmake_policy(SET CMP0148 OLD)
endif()

project(luavsg
  VERSION 0.0.0
  DESCRIPTION "LUAVSG master build (vendored deps)"
  LANGUAGES C CXX
)

# -----------------------------------------------------------------------------
# Global configuration
# -----------------------------------------------------------------------------

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${PROJECT_BINARY_DIR}/bin)

# -----------------------------------------------------------------------------
# Options
# -----------------------------------------------------------------------------

option(LUAVSG_ENABLE_VSGXCHANGE "Build vsgXchange subproject" ON)
option(LUAVSG_VSGXCHANGE_MINIMAL
  "Disable most vsgXchange plugins (easier first build)"
  ON
)

# Allow configuring from the repo root with: cmake .
option(LUAVSG_ALLOW_IN_SOURCE "Permit in-source top-level configure (cmake .)" ON)

# If ON, skip deps known to hard-fail under top-level in-source config.
option(LUAVSG_SKIP_IN_SOURCE_FORBIDDEN_DEPS
  "Skip deps that forbid in-source builds"
  ON
)

# Optional: build a few vendored libraries explicitly.
option(LUAVSG_BUILD_CURL "Build vendored curl" OFF)

# -----------------------------------------------------------------------------
# Helper: set cache values only if caller did not provide them
# -----------------------------------------------------------------------------

function(_luavsg_cache_default name type value)
  if(NOT DEFINED ${name} OR "${${name}}" STREQUAL "")
    set(${name} "${value}" CACHE ${type} "" FORCE)
  endif()
endfunction()

# -----------------------------------------------------------------------------
# Top-level in-source detection
# -----------------------------------------------------------------------------

set(LUAVSG_IN_SOURCE OFF)
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_BINARY_DIR)
  set(LUAVSG_IN_SOURCE ON)
endif()

if(LUAVSG_IN_SOURCE AND NOT LUAVSG_ALLOW_IN_SOURCE)
  message(FATAL_ERROR
    "In-source build detected (CMAKE_SOURCE_DIR == CMAKE_BINARY_DIR).
"
    "Use an out-of-source build instead, e.g.:
"
    "  cmake -S \"${CMAKE_SOURCE_DIR}\" -B \"${CMAKE_SOURCE_DIR}/build\"
"
  )
endif()

if(LUAVSG_IN_SOURCE)
  message(STATUS "luavsg: in-source build detected")
endif()

# -----------------------------------------------------------------------------
# Vulkan (baked-in fallback to vendored SDK under lib/VulkanSDK)
# -----------------------------------------------------------------------------

if(NOT DEFINED VULKAN_SDK OR VULKAN_SDK STREQUAL "")
  if(DEFINED ENV{VULKAN_SDK} AND NOT "$ENV{VULKAN_SDK}" STREQUAL "")
    set(VULKAN_SDK "$ENV{VULKAN_SDK}")
  else()
    file(GLOB _vulkan_sdk_candidates
      LIST_DIRECTORIES true
      "${CMAKE_SOURCE_DIR}/lib/VulkanSDK/*"
    )
    list(SORT _vulkan_sdk_candidates)
    list(REVERSE _vulkan_sdk_candidates)
    if(_vulkan_sdk_candidates)
      list(GET _vulkan_sdk_candidates 0 VULKAN_SDK)
    endif()
  endif()
endif()

if(NOT DEFINED VULKAN_SDK OR VULKAN_SDK STREQUAL "")
  message(FATAL_ERROR
    "VULKAN_SDK not set and no vendored SDK found at "
    "${CMAKE_SOURCE_DIR}/lib/VulkanSDK/<version>."
  )
endif()

set(_vulkan_include "${VULKAN_SDK}/Include")
set(_vulkan_lib_dir "${VULKAN_SDK}/Lib")
if(NOT EXISTS "${_vulkan_lib_dir}/vulkan-1.lib")
  if(EXISTS "${VULKAN_SDK}/Lib-ARM64/vulkan-1.lib")
    set(_vulkan_lib_dir "${VULKAN_SDK}/Lib-ARM64")
  endif()
endif()
set(_vulkan_lib "${_vulkan_lib_dir}/vulkan-1.lib")

if(NOT EXISTS "${_vulkan_include}/vulkan/vulkan.h")
  message(FATAL_ERROR
    "Vulkan headers not found at: ${_vulkan_include}/vulkan/vulkan.h
"
    "VULKAN_SDK is: ${VULKAN_SDK}"
  )
endif()

if(NOT EXISTS "${_vulkan_lib}")
  message(FATAL_ERROR
    "Vulkan import library not found at: ${_vulkan_lib}
"
    "VULKAN_SDK is: ${VULKAN_SDK}"
  )
endif()

_luavsg_cache_default(VULKAN_SDK PATH "${VULKAN_SDK}")
_luavsg_cache_default(Vulkan_INCLUDE_DIR PATH "${_vulkan_include}")
_luavsg_cache_default(Vulkan_LIBRARY FILEPATH "${_vulkan_lib}")

message(STATUS "Using VULKAN_SDK: ${VULKAN_SDK}")
message(STATUS "Vulkan include:  ${Vulkan_INCLUDE_DIR}")
message(STATUS "Vulkan library:  ${Vulkan_LIBRARY}")

# -----------------------------------------------------------------------------
# Prefer vendored package configs when present
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# CMake module shims (avoid configure-time find_package() failures)
# -----------------------------------------------------------------------------
# Some upstream projects (e.g. libpng) call find_package(ZLIB REQUIRED).
# The stock FindZLIB.cmake requires an on-disk zlib library *at configure time*.
# When we build zlib via add_subdirectory(), the library does not exist yet,
# so configuration fails.
#
# Workaround: provide our own FindZLIB.cmake that satisfies find_package(ZLIB)
# by mapping ZLIB::ZLIB to the vendored zlib target.
set(_luavsg_cmake_shims_dir "${CMAKE_BINARY_DIR}/luavsg_cmake_shims")
file(MAKE_DIRECTORY "${_luavsg_cmake_shims_dir}")
file(WRITE "${_luavsg_cmake_shims_dir}/FindZLIB.cmake" [=[
# Auto-generated by luavsg top-level CMakeLists.txt
# Prefer vendored zlib targets over filesystem probing.

if(TARGET zlibstatic)
  if(NOT TARGET ZLIB::ZLIB)
    add_library(ZLIB::ZLIB ALIAS zlibstatic)
  endif()
  set(ZLIB_FOUND TRUE)
  set(ZLIB_INCLUDE_DIR "${CMAKE_SOURCE_DIR}/lib/zlib")
  set(ZLIB_INCLUDE_DIRS "${CMAKE_SOURCE_DIR}/lib/zlib")
  return()
endif()

if(TARGET zlib)
  if(NOT TARGET ZLIB::ZLIB)
    add_library(ZLIB::ZLIB ALIAS zlib)
  endif()
  set(ZLIB_FOUND TRUE)
  set(ZLIB_INCLUDE_DIR "${CMAKE_SOURCE_DIR}/lib/zlib")
  set(ZLIB_INCLUDE_DIRS "${CMAKE_SOURCE_DIR}/lib/zlib")
  return()
endif()

# Fall back: let the caller handle absence (or provide ZLIB_ROOT/ZLIB_LIBRARY).
set(ZLIB_FOUND FALSE)
]=])

# PkgConfig support (Windows-friendly)
# Many third-party projects use FindPkgConfig.cmake. On Windows you often do not
# have a system pkg-config, and building pkg-config from source is circular.
#
# Workaround: generate a small pkg-config shim that reads *.pc files from the
# vendored tree and answers the subset of queries CMake typically performs.
find_package(Python3 COMPONENTS Interpreter REQUIRED)

file(WRITE "${_luavsg_cmake_shims_dir}/luavsg_pkg_config.py" [=[
"""Minimal pkg-config shim for CMake configure-time discovery.

Implements enough for FindPkgConfig.cmake and common project checks:
  --version
  --exists <pkg>
  --modversion <pkg>
  --cflags <pkg...>
  --libs <pkg...>

Search strategy:
  1) PKG_CONFIG_PATH entries (directories; searched recursively)
  2) <repo>/lib (searched recursively)

This is intentionally minimal and permissive: it is designed to unblock
configuration when vendoring deps.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


_VERSION = "0.0.0-luavsg"


@dataclass(frozen=True)
class PcFile:
    name: str
    path: Path
    vars: Dict[str, str]
    fields: Dict[str, str]


_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def _split_path_list(raw: str) -> List[Path]:
    if not raw:
        return []
    return [Path(p) for p in raw.split(os.pathsep) if p.strip()]


def _repo_root() -> Path:
    # shim dir is <build>/luavsg_cmake_shims; repo root is CMAKE_SOURCE_DIR
    # passed via env var for robustness.
    env = os.environ.get("LUAVSG_REPO_ROOT", "")
    if env:
        return Path(env)
    return Path.cwd()


def _candidate_roots() -> List[Path]:
    roots: List[Path] = []
    roots.extend(_split_path_list(os.environ.get("PKG_CONFIG_PATH", "")))
    roots.append(_repo_root() / "lib")
    # Common extra pc locations
    roots.append(_repo_root() / "lib" / "zstd_build")
    roots.append(_repo_root() / "lib" / "zstd_build" / "lib")
    return [r for r in roots if r.exists()]


def _find_pc_files(roots: Iterable[Path]) -> Dict[str, Path]:
    out: Dict[str, Path] = {}
    for root in roots:
        try:
            for pc in root.rglob("*.pc"):
                name = pc.stem
                out.setdefault(name, pc)
        except Exception:
            continue
    return out


def _parse_pc(path: Path) -> PcFile:
    vars_: Dict[str, str] = {}
    fields: Dict[str, str] = {}

    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line and not line.split(":", 1)[0].strip().endswith("="):
            k, v = line.split(":", 1)
            fields[k.strip()] = v.strip()
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            vars_[k.strip()] = v.strip()

    name = fields.get("Name", path.stem)
    return PcFile(name=name, path=path, vars=vars_, fields=fields)


def _expand(s: str, vars_: Dict[str, str]) -> str:
    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        return vars_.get(key, "")

    prev = None
    cur = s
    for _ in range(10):
        if prev == cur:
            break
        prev = cur
        cur = _VAR_RE.sub(repl, cur)
    return cur


def _collect(pkgs: List[str]) -> Tuple[List[str], List[str]]:
    roots = _candidate_roots()
    index = _find_pc_files(roots)

    cflags: List[str] = []
    libs: List[str] = []

    for pkg in pkgs:
        pc_path = index.get(pkg)
        if not pc_path:
            raise FileNotFoundError(pkg)
        pc = _parse_pc(pc_path)
        vars_ = dict(pc.vars)

        # seed a few common vars
        if "pcfiledir" not in vars_:
            vars_["pcfiledir"] = str(pc_path.parent)

        c = pc.fields.get("Cflags", "")
        l = pc.fields.get("Libs", "")
        cflags.extend(_expand(c, vars_).split())
        # Keep this shim conservative: avoid Libs.private by default.
        libs.extend(_expand(l, vars_).split())

    return cflags, libs


def _main(argv: List[str]) -> int:
    if "--version" in argv:
        sys.stdout.write(_VERSION)
        return 0

    # Normalize: FindPkgConfig passes flags first, then pkg names.
    want_exists = "--exists" in argv
    want_mod = "--modversion" in argv
    want_cflags = "--cflags" in argv
    want_libs = "--libs" in argv

    pkgs = [a for a in argv if a and not a.startswith("-")]

    if want_exists or want_mod or want_cflags or want_libs:
        if not pkgs:
            return 1

    roots = _candidate_roots()
    index = _find_pc_files(roots)

    if want_exists:
        for p in pkgs:
            if p not in index:
                return 1
        return 0

    if want_mod:
        p = pkgs[0]
        pc_path = index.get(p)
        if not pc_path:
            return 1
        pc = _parse_pc(pc_path)
        sys.stdout.write(pc.fields.get("Version", "0"))
        return 0

    if want_cflags or want_libs:
        try:
            cflags, libs = _collect(pkgs)
        except FileNotFoundError:
            return 1
        if want_cflags:
            sys.stdout.write(" ".join(cflags))
        elif want_libs:
            sys.stdout.write(" ".join(libs))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
]=])

file(WRITE "${_luavsg_cmake_shims_dir}/pkg-config.cmd" "@echo off
\"${Python3_EXECUTABLE}\" \"${_luavsg_cmake_shims_dir}/luavsg_pkg_config.py\" %*
")

# Ensure the shim sees the repo root even when invoked from nested build dirs.
set(ENV{LUAVSG_REPO_ROOT} "${CMAKE_SOURCE_DIR}")

# Prefer our shim during configure.
set(PKG_CONFIG_EXECUTABLE "${_luavsg_cmake_shims_dir}/pkg-config.cmd" CACHE FILEPATH "" FORCE)

list(PREPEND CMAKE_MODULE_PATH "${_luavsg_cmake_shims_dir}")


# Helps config-mode find_package() calls locate vendored config packages.
list(APPEND CMAKE_PREFIX_PATH
  "${CMAKE_SOURCE_DIR}/lib/KTX/cmake"
  "${CMAKE_SOURCE_DIR}/lib/libidn2/cmake"
  "${VULKAN_SDK}/Lib/cmake"
)

# Helpful explicit hints (from your diag output).
_luavsg_cache_default(glslang_DIR PATH "${VULKAN_SDK}/Lib/cmake/glslang/glslang")
_luavsg_cache_default(Ktx_DIR PATH "${CMAKE_SOURCE_DIR}/lib/KTX/cmake")
_luavsg_cache_default(libidn2_DIR PATH "${CMAKE_SOURCE_DIR}/lib/libidn2/cmake")
_luavsg_cache_default(PNG_DIR PATH "${CMAKE_SOURCE_DIR}/lib/libpng/scripts/cmake")

# -----------------------------------------------------------------------------
# Vendored deps (best-effort)
# -----------------------------------------------------------------------------

# FreeType: forbids top-level in-source builds by checking CMAKE_SOURCE_DIR ==
# CMAKE_BINARY_DIR (top-level vars). If you insist on `cmake .`, do NOT add it
# as a subdirectory. Keep vsgXchange minimal (no freetype plugin) until you use
# an out-of-source configure.
set(_skip_freetype OFF)
if(LUAVSG_IN_SOURCE AND LUAVSG_SKIP_IN_SOURCE_FORBIDDEN_DEPS)
  set(_skip_freetype ON)
endif()

if(_skip_freetype)
  message(STATUS "luavsg: skipping freetype (forbids top-level in-source builds)")
else()
  if(EXISTS "${CMAKE_SOURCE_DIR}/lib/freetype/CMakeLists.txt")
    add_subdirectory(lib/freetype)
  endif()
endif()

# Draco: has CMake.
if(EXISTS "${CMAKE_SOURCE_DIR}/lib/draco/CMakeLists.txt")
  message(STATUS "luavsg: using vendored draco from lib/draco")
  add_subdirectory(lib/draco)
endif()

# zlib: has CMake.
if(EXISTS "${CMAKE_SOURCE_DIR}/lib/zlib/CMakeLists.txt")
  add_subdirectory(lib/zlib)
endif()

# zstd: prefers build/cmake.
if(EXISTS "${CMAKE_SOURCE_DIR}/lib/zstd/build/cmake/CMakeLists.txt")
  add_subdirectory(lib/zstd/build/cmake lib/zstd_build)
endif()

# brotli: has CMake.
if(EXISTS "${CMAKE_SOURCE_DIR}/lib/brotli/CMakeLists.txt")
  add_subdirectory(lib/brotli)
endif()

# bzip2: you added CMake support.
if(EXISTS "${CMAKE_SOURCE_DIR}/lib/bzip2/CMakeLists.txt")
  add_subdirectory(lib/bzip2)
endif()

# libpng: has CMake.
if(EXISTS "${CMAKE_SOURCE_DIR}/lib/libpng/CMakeLists.txt")
  add_subdirectory(lib/libpng)
endif()

# libidn2: you added CMake support.
if(EXISTS "${CMAKE_SOURCE_DIR}/lib/libidn2/CMakeLists.txt")
  add_subdirectory(lib/libidn2)
endif()

# nghttp2: has CMake.
if(EXISTS "${CMAKE_SOURCE_DIR}/lib/nghttp2/CMakeLists.txt")
  add_subdirectory(lib/nghttp2)
endif()

# curl: has CMake at root.
# NOTE: Your diag reported add_subdirectory=curl/tests/cmake, but that is the
# test harness; the actual project entry is at lib/curl/CMakeLists.txt.
if(LUAVSG_BUILD_CURL AND EXISTS "${CMAKE_SOURCE_DIR}/lib/curl/CMakeLists.txt")
  _luavsg_cache_default(BUILD_CURL_EXE BOOL OFF)
  _luavsg_cache_default(BUILD_SHARED_LIBS BOOL OFF)
  _luavsg_cache_default(BUILD_TESTING BOOL OFF)
  _luavsg_cache_default(CURL_DISABLE_TESTS BOOL ON)
  _luavsg_cache_default(CURL_USE_LIBSSH2 BOOL OFF)
  _luavsg_cache_default(CURL_USE_SCHANNEL BOOL ON)
  _luavsg_cache_default(CURL_USE_OPENSSL BOOL OFF)
  add_subdirectory(lib/curl)
endif()

# -----------------------------------------------------------------------------
# VulkanSceneGraph and vsgXchange (subprojects)
# -----------------------------------------------------------------------------

# VSG itself (defines vsg::vsg)
add_subdirectory(lib/VulkanSceneGraph)

set(HAVE_VSGXCHANGE OFF)
if(LUAVSG_ENABLE_VSGXCHANGE AND EXISTS "${CMAKE_SOURCE_DIR}/lib/vsgXchange/CMakeLists.txt")

  if(LUAVSG_VSGXCHANGE_MINIMAL)
    # The exact option names vary by vsgXchange version.
    # We set a broad set of commonly-used toggles; unknown vars are harmless.
    _luavsg_cache_default(vsgXchange_BUILD_APPLICATIONS BOOL OFF)
    _luavsg_cache_default(vsgXchange_BUILD_TESTS BOOL OFF)

    _luavsg_cache_default(vsgXchange_SUPPORTS_3DTILES BOOL OFF)

    _luavsg_cache_default(vsgXchange_SUPPORTS_ASSIMP BOOL OFF)
    _luavsg_cache_default(vsgXchange_SUPPORTS_CURL BOOL OFF)
    _luavsg_cache_default(vsgXchange_SUPPORTS_FREETYPE BOOL OFF)
    _luavsg_cache_default(vsgXchange_SUPPORTS_GDAL BOOL OFF)
    _luavsg_cache_default(vsgXchange_SUPPORTS_GLSLANG BOOL OFF)
    _luavsg_cache_default(vsgXchange_SUPPORTS_KTX BOOL OFF)
    _luavsg_cache_default(vsgXchange_SUPPORTS_OPENEXR BOOL OFF)
    _luavsg_cache_default(vsgXchange_SUPPORTS_DRACO BOOL OFF)

    _luavsg_cache_default(vsgXchange_WITH_ASSIMP BOOL OFF)
    _luavsg_cache_default(vsgXchange_WITH_CURL BOOL OFF)
    _luavsg_cache_default(vsgXchange_WITH_FREETYPE BOOL OFF)
    _luavsg_cache_default(vsgXchange_WITH_GDAL BOOL OFF)
    _luavsg_cache_default(vsgXchange_WITH_GLSLANG BOOL OFF)
    _luavsg_cache_default(vsgXchange_WITH_KTX BOOL OFF)
    _luavsg_cache_default(vsgXchange_WITH_OPENEXR BOOL OFF)
    _luavsg_cache_default(vsgXchange_WITH_DRACO BOOL OFF)
  endif()

  add_subdirectory(lib/vsgXchange)
  set(HAVE_VSGXCHANGE ON)
endif()

# -----------------------------------------------------------------------------
# Application
# -----------------------------------------------------------------------------

set(SOURCES
  src/main.cpp
)

add_executable(myfirstvsgapplication ${SOURCES})

target_link_libraries(myfirstvsgapplication
  PRIVATE
    vsg::vsg
)

if(HAVE_VSGXCHANGE)
  target_compile_definitions(myfirstvsgapplication PRIVATE vsgXchange_FOUND)
  target_link_libraries(myfirstvsgapplication PRIVATE vsgXchange::vsgXchange)
endif()

# -----------------------------------------------------------------------------
# Utility targets
# -----------------------------------------------------------------------------

# VulkanSceneGraph defines a "clobber" target; avoid collisions.
add_custom_target(luavsg_clobber
  COMMAND git clean -d -f -x
  WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)

# -----------------------------------------------------------------------------
# Install
# -----------------------------------------------------------------------------

install(TARGETS myfirstvsgapplication
  RUNTIME DESTINATION bin
)
