cmake_minimum_required(VERSION 3.24)

# Enable modern find_package() behavior for <PackageName>_ROOT hints.
cmake_policy(SET CMP0074 NEW)

# Silence legacy Python module lookup warning on newer CMake (draco).
if(POLICY CMP0148)
    cmake_policy(SET CMP0148 NEW)
endif()

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
option(LUAVSG_VSGXCHANGE_MINIMAL "Disable most vsgXchange plugins" ON)

# B.2 mode: build vendored deps (draco/curl/freetype/KTX) as subprojects.
option(LUAVSG_VENDORED_DEPS "Build vendored deps" ON)

# For curl, keep dependencies minimal on Windows.
option(LUAVSG_CURL_MINIMAL "Configure curl for minimal dependency surface" ON)

# -----------------------------------------------------------------------------
# Helper: set cache values only if caller did not provide them
# -----------------------------------------------------------------------------

function(_luavsg_cache_default name type value)
    if(NOT DEFINED ${name} OR "${${name}}" STREQUAL "")
        set(${name} "${value}" CACHE ${type} "" FORCE)
    endif()
endfunction()

# -----------------------------------------------------------------------------
# Helper: vendored deps build dir routing
# -----------------------------------------------------------------------------
# Some deps (notably freetype) forbid build dirs inside their source tree.
# If you insist on in-source builds (cmake .), route dependency build dirs to a
# sibling folder outside the repo.

set(_luavsg_deps_binary_base "${CMAKE_BINARY_DIR}")
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_BINARY_DIR)
    set(_luavsg_deps_binary_base "${CMAKE_SOURCE_DIR}/../luavsg_deps_build")
    message(STATUS "luavsg: in-source build detected; deps build under: ${_luavsg_deps_binary_base}")
endif()

file(MAKE_DIRECTORY "${_luavsg_deps_binary_base}")

function(_luavsg_add_subdir name relpath bindir)
    if(NOT EXISTS "${CMAKE_SOURCE_DIR}/${relpath}/CMakeLists.txt")
        set(${name}_VENDORED OFF PARENT_SCOPE)
        return()
    endif()

    message(STATUS "luavsg: using vendored ${name} from ${relpath}")

    if(IS_ABSOLUTE "${bindir}")
        set(_luavsg_bdir "${bindir}")
    else()
        set(_luavsg_bdir "${_luavsg_deps_binary_base}/${bindir}")
    endif()

    file(MAKE_DIRECTORY "${_luavsg_bdir}")

    add_subdirectory(
        "${CMAKE_SOURCE_DIR}/${relpath}"
        "${_luavsg_bdir}"
    )

    set(${name}_VENDORED ON PARENT_SCOPE)
endfunction()

function(_luavsg_alias_if_target alias_name existing_name)
    if(TARGET "${existing_name}" AND NOT TARGET "${alias_name}")
        add_library(${alias_name} ALIAS ${existing_name})
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

_luavsg_cache_default(VULKAN_SDK PATH "${VULKAN_SDK}")
_luavsg_cache_default(Vulkan_INCLUDE_DIR PATH "${_vulkan_include}")
_luavsg_cache_default(Vulkan_LIBRARY FILEPATH "${_vulkan_lib}")

message(STATUS "Using VULKAN_SDK: ${VULKAN_SDK}")
message(STATUS "Vulkan include:  ${Vulkan_INCLUDE_DIR}")
message(STATUS "Vulkan library:  ${Vulkan_LIBRARY}")

# -----------------------------------------------------------------------------
# B.2: Vendored deps as subprojects
# -----------------------------------------------------------------------------

if(LUAVSG_VENDORED_DEPS)

    # Draco
    _luavsg_add_subdir(draco lib/draco _deps/draco)
    _luavsg_alias_if_target(draco::draco draco)
    _luavsg_alias_if_target(draco::draco draco_static)
    _luavsg_alias_if_target(draco::draco draco_shared)

    # Freetype: use builds/cmake when present.
    if(EXISTS "${CMAKE_SOURCE_DIR}/lib/freetype/builds/cmake/CMakeLists.txt")
        message(STATUS "luavsg: using vendored freetype from lib/freetype/builds/cmake")
        add_subdirectory(
            "${CMAKE_SOURCE_DIR}/lib/freetype/builds/cmake"
            "${_luavsg_deps_binary_base}/_deps/freetype"
        )
        set(freetype_VENDORED ON)
    else()
        _luavsg_add_subdir(freetype lib/freetype _deps/freetype)
    endif()
    _luavsg_alias_if_target(Freetype::Freetype freetype)
    _luavsg_alias_if_target(Freetype::Freetype freetype-static)
    _luavsg_alias_if_target(Freetype::Freetype freetype-lib)

    # KTX
    _luavsg_add_subdir(ktx lib/KTX _deps/ktx)
    _luavsg_alias_if_target(Ktx::ktx ktx)
    _luavsg_alias_if_target(KTX::ktx ktx)
    _luavsg_alias_if_target(Ktx::ktx libktx)
    _luavsg_alias_if_target(KTX::ktx libktx)

    # curl
    if(LUAVSG_CURL_MINIMAL)
        _luavsg_cache_default(BUILD_CURL_EXE BOOL OFF)
        _luavsg_cache_default(BUILD_SHARED_LIBS BOOL OFF)
        _luavsg_cache_default(CURL_USE_SCHANNEL BOOL ON)
        _luavsg_cache_default(CURL_USE_OPENSSL BOOL OFF)
        _luavsg_cache_default(CURL_ZLIB BOOL OFF)
        _luavsg_cache_default(CURL_DISABLE_LDAP BOOL ON)
        _luavsg_cache_default(CURL_DISABLE_LDAPS BOOL ON)
        _luavsg_cache_default(CURL_DISABLE_RTSP BOOL ON)
        _luavsg_cache_default(CURL_DISABLE_DICT BOOL ON)
        _luavsg_cache_default(CURL_DISABLE_TELNET BOOL ON)
        _luavsg_cache_default(CURL_DISABLE_TFTP BOOL ON)
        _luavsg_cache_default(CURL_DISABLE_POP3 BOOL ON)
        _luavsg_cache_default(CURL_DISABLE_IMAP BOOL ON)
        _luavsg_cache_default(CURL_DISABLE_SMTP BOOL ON)
        _luavsg_cache_default(CURL_DISABLE_GOPHER BOOL ON)
    endif()
    _luavsg_add_subdir(curl lib/curl _deps/curl)
    _luavsg_alias_if_target(CURL::libcurl libcurl)
    _luavsg_alias_if_target(CURL::libcurl libcurl_static)
    _luavsg_alias_if_target(CURL::libcurl libcurl_shared)

endif()

# -----------------------------------------------------------------------------
# Dependencies (Option B: subprojects)
# -----------------------------------------------------------------------------

add_subdirectory(lib/VulkanSceneGraph)

if(LUAVSG_ENABLE_VSGXCHANGE AND EXISTS "${CMAKE_SOURCE_DIR}/lib/vsgXchange/CMakeLists.txt")

    if(LUAVSG_VSGXCHANGE_MINIMAL)
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

add_executable(myfirstvsgapplication
    src/main.cpp
)

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
