cmake_minimum_required(VERSION 3.15)

project(libunistring
  VERSION 0.0.0
  LANGUAGES C
)

# This is a pragmatic CMake shim for the vendored GNU libunistring source
# tree. Upstream libunistring is Autotools-first; this file aims to produce a
# usable static library on Windows/MSVC (and generally on CMake toolchains)
# for dependency graphs that expect to link against libunistring.
#
# Notes:
# - It builds the library from the sources under ./lib via broad globbing.
# - It generates a minimal config.h (most sources include "config.h").
# - It exports a CONFIG package so parent projects can use:
#     find_package(LibUnistring CONFIG REQUIRED)
#     target_link_libraries(app PRIVATE LibUnistring::LibUnistring)
#
# If you later replace this with an official upstream CMake build, delete
# this shim and prefer the upstream package.

include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

option(LIBUNISTRING_BUILD_SHARED "Build shared library" OFF)
option(LIBUNISTRING_BUILD_TESTS "Build libunistring tests" OFF)

# -------------------------------------------------------------------------
# config.h generation (minimal)
# -------------------------------------------------------------------------

set(_cfg_in "${CMAKE_CURRENT_LIST_DIR}/cmake/config.h.in")
set(_cfg_out "${CMAKE_CURRENT_BINARY_DIR}/config.h")
configure_file("${_cfg_in}" "${_cfg_out}" @ONLY)

# -------------------------------------------------------------------------
# Sources
# -------------------------------------------------------------------------
# Upstream layout:
#   - lib/*.c, lib/*.h
#   - lib/*/*.c (varies by version)
# This shim uses GLOB_RECURSE with an allowlist approach for C sources.
# If you hit build failures, add excludes below as required.

file(GLOB_RECURSE _unistring_c_sources
  CONFIGURE_DEPENDS
  "${CMAKE_CURRENT_LIST_DIR}/lib/*.c"
)

# Some trees contain test programs in lib/; exclude common patterns.
set(_unistring_excludes
  ".*[/\\\\]test-.*\\.c$"
  ".*[/\\\\]tests[/\\\\].*"
  ".*[/\\\\]bench[/\\\\].*"
)

set(_unistring_sources "")
foreach(_src IN LISTS _unistring_c_sources)
  set(_skip OFF)
  foreach(_re IN LISTS _unistring_excludes)
    if(_src MATCHES "${_re}")
      set(_skip ON)
    endif()
  endforeach()
  if(NOT _skip)
    list(APPEND _unistring_sources "${_src}")
  endif()
endforeach()

if(NOT _unistring_sources)
  message(FATAL_ERROR "libunistring shim: no C sources found under lib/.")
endif()

# -------------------------------------------------------------------------
# Library target
# -------------------------------------------------------------------------

set(_libtype STATIC)
if(LIBUNISTRING_BUILD_SHARED)
  set(_libtype SHARED)
endif()

add_library(LibUnistring ${_libtype} ${_unistring_sources})
add_library(LibUnistring::LibUnistring ALIAS LibUnistring)

target_include_directories(LibUnistring
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_LIST_DIR}/lib>
    $<BUILD_INTERFACE:${CMAKE_CURRENT_BINARY_DIR}>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)

target_compile_features(LibUnistring PUBLIC c_std_99)

# Many Autotools projects expect these on MSVC.
if(MSVC)
  target_compile_definitions(LibUnistring PRIVATE
    _CRT_SECURE_NO_WARNINGS
    _CRT_NONSTDC_NO_WARNINGS
  )
endif()

# Provide a predictable name for consumers that look for "unistring".
set_target_properties(LibUnistring PROPERTIES
  OUTPUT_NAME "unistring"
)

# -------------------------------------------------------------------------
# Installation + CMake package config
# -------------------------------------------------------------------------

# Headers: install everything under lib/ plus the generated config.h.
install(
  DIRECTORY "${CMAKE_CURRENT_LIST_DIR}/lib/"
  DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}"
  FILES_MATCHING
    PATTERN "*.h"
)

install(FILES "${_cfg_out}"
  DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}"
)

install(TARGETS LibUnistring
  EXPORT LibUnistringTargets
  ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
  LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
  RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}"
)

install(EXPORT LibUnistringTargets
  NAMESPACE LibUnistring::
  DESTINATION "${CMAKE_INSTALL_LIBDIR}/cmake/LibUnistring"
)

set(_pkg_dir "${CMAKE_INSTALL_LIBDIR}/cmake/LibUnistring")

configure_package_config_file(
  "${CMAKE_CURRENT_LIST_DIR}/cmake/LibUnistringConfig.cmake.in"
  "${CMAKE_CURRENT_BINARY_DIR}/LibUnistringConfig.cmake"
  INSTALL_DESTINATION "${_pkg_dir}"
)

write_basic_package_version_file(
  "${CMAKE_CURRENT_BINARY_DIR}/LibUnistringConfigVersion.cmake"
  VERSION "${PROJECT_VERSION}"
  COMPATIBILITY AnyNewerVersion
)

install(FILES
  "${CMAKE_CURRENT_BINARY_DIR}/LibUnistringConfig.cmake"
  "${CMAKE_CURRENT_BINARY_DIR}/LibUnistringConfigVersion.cmake"
  DESTINATION "${_pkg_dir}"
)

# -------------------------------------------------------------------------
# Optional: tests (disabled by default)
# -------------------------------------------------------------------------

if(LIBUNISTRING_BUILD_TESTS AND EXISTS "${CMAKE_CURRENT_LIST_DIR}/tests")
  enable_testing()
  add_subdirectory(tests)
endif()
