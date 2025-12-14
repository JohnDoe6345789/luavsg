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
