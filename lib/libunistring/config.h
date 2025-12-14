/* Auto-generated minimal config.h for the CMake shim build.
 *
 * Upstream libunistring uses Autoconf to generate a feature-rich config.h.
 * This file provides the subset commonly needed to build on Windows/MSVC.
 *
 * If you hit missing #define errors, add them here (keep it minimal).
 */

#pragma once

/* Basic headers */
#define HAVE_STDINT_H 1
#define HAVE_STDLIB_H 1
#define HAVE_STRING_H 1
#define HAVE_MEMORY_H 1
#define HAVE_LIMITS_H 1
#define HAVE_ERRNO_H 1

/* C99 */
#define HAVE_INLINE 1

/* Endianness: assume little-endian on Windows/x86_64 and ARM64 */
#if defined(_WIN32)
  #define WORDS_LITTLEENDIAN 1
#endif

/* Wide char support is present on Windows */
#define HAVE_WCHAR_T 1
#define HAVE_WCHAR_H 1

/* Use snprintf variants */
#define HAVE_SNPRINTF 1
#define HAVE_VSNPRINTF 1

/* libunistring internal */
#define GNULIB_STRERROR 1
