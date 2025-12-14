cmake_minimum_required(VERSION 3.24)

# Enable modern find_package() behavior for <PackageName>_ROOT hints.
# This suppresses the CMP0074 warnings you are seeing and makes *_ROOT work.
cmake_policy(SET CMP0074 NEW)

project(MyFirstVsgApplication
    VERSION 0.0.0
    DESCRIPTION "Template of how to create a program using VulkanSceneGraph and CMake"
    LANGUAGES CXX
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

# If ON, we aggressively turn off optional vsgXchange plugins that tend to drag
# in large dependency trees. Turn this OFF once you are ready to hunt deps.
option(LUAVSG_VSGXCHANGE_MINIMAL
    "Disable most vsgXchange plugins (easier first build)"
    ON
)

# -----------------------------------------------------------------------------
# Helper: set cache values only if caller did not provide them
# -----------------------------------------------------------------------------

function(_luavsg_cache_default name type value)
    if(NOT DEFINED ${name} OR "${${name}}" STREQUAL "")
        set(${name} "${value}" CACHE ${type} "" FORCE)
    endif()
endfunction()

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

# Prefer x64 libs; fall back to ARM64 layout if present.
set(_vulkan_lib_dir "${VULKAN_SDK}/Lib")
if(NOT EXISTS "${_vulkan_lib_dir}/vulkan-1.lib")
    if(EXISTS "${VULKAN_SDK}/Lib-ARM64/vulkan-1.lib")
        set(_vulkan_lib_dir "${VULKAN_SDK}/Lib-ARM64")
    endif()
endif()

set(_vulkan_lib "${_vulkan_lib_dir}/vulkan-1.lib")

if(NOT EXISTS "${_vulkan_include}/vulkan/vulkan.h")
    message(FATAL_ERROR
        "Vulkan headers not found at: ${_vulkan_include}/vulkan/vulkan.h\n"
        "VULKAN_SDK is: ${VULKAN_SDK}"
    )
endif()

if(NOT EXISTS "${_vulkan_lib}")
    message(FATAL_ERROR
        "Vulkan import library not found at: ${_vulkan_lib}\n"
        "VULKAN_SDK is: ${VULKAN_SDK}"
    )
endif()

# Push hints into cache so subprojects (vsg / vsgXchange) pick them up.
_luavsg_cache_default(VULKAN_SDK PATH "${VULKAN_SDK}")
_luavsg_cache_default(Vulkan_INCLUDE_DIR PATH "${_vulkan_include}")
_luavsg_cache_default(Vulkan_LIBRARY FILEPATH "${_vulkan_lib}")

message(STATUS "Using VULKAN_SDK: ${VULKAN_SDK}")
message(STATUS "Vulkan include:  ${Vulkan_INCLUDE_DIR}")
message(STATUS "Vulkan library:  ${Vulkan_LIBRARY}")

# -----------------------------------------------------------------------------
# Dependency hints (vendored source trees)
# -----------------------------------------------------------------------------
# These do NOT magically build the deps; they just help find_package() when the
# dependency provides a CMake config/package, or when the project supports *_ROOT.

if(EXISTS "${CMAKE_SOURCE_DIR}/lib/curl/CMakeLists.txt")
    _luavsg_cache_default(CURL_ROOT PATH "${CMAKE_SOURCE_DIR}/lib/curl")
endif()

if(EXISTS "${CMAKE_SOURCE_DIR}/lib/freetype/CMakeLists.txt")
    _luavsg_cache_default(FREETYPE_ROOT PATH "${CMAKE_SOURCE_DIR}/lib/freetype")
endif()

if(EXISTS "${CMAKE_SOURCE_DIR}/lib/KTX/CMakeLists.txt")
    _luavsg_cache_default(KTX_ROOT PATH "${CMAKE_SOURCE_DIR}/lib/KTX")
endif()

if(EXISTS "${CMAKE_SOURCE_DIR}/lib/draco/CMakeLists.txt")
    _luavsg_cache_default(DRACO_ROOT PATH "${CMAKE_SOURCE_DIR}/lib/draco")
endif()

if(EXISTS "${CMAKE_SOURCE_DIR}/lib/glslang/CMakeLists.txt")
    _luavsg_cache_default(glslang_ROOT PATH "${CMAKE_SOURCE_DIR}/lib/glslang")
endif()

# -----------------------------------------------------------------------------
# Dependencies (Option B: subprojects)
# -----------------------------------------------------------------------------

add_subdirectory(lib/VulkanSceneGraph)

if(LUAVSG_ENABLE_VSGXCHANGE AND EXISTS "${CMAKE_SOURCE_DIR}/lib/vsgXchange/CMakeLists.txt")

    if(LUAVSG_VSGXCHANGE_MINIMAL)
        # The exact option names vary by vsgXchange version. We set a broad set
        # of commonly-used toggles; unknown vars are harmless.
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

# NOTE: VulkanSceneGraph defines a "clobber" custom target already.
# We use a repo-scoped name to avoid CMP0002 target collisions.

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
