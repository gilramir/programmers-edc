{
  # Two targets: Turbo Vision itself, then the addon that binds it.
  #
  # Turbo Vision used to be built by a separate `cmake` invocation into
  # ../build-tvision/libtvision.a, which this file then named as a library.
  # That cost two things. It made **cmake a requirement for anybody installing
  # the package** who has no prebuilt binary for their platform -- node-gyp
  # every npm user already has, cmake they do not. And it put the archive
  # outside gyp's dependency graph, so `node-gyp build` did not relink when
  # only the library had changed: the addon under test stayed the one built
  # before it, which looks exactly like a library change having no effect.
  # A gyp `dependencies` edge fixes the second for free.
  #
  # ------------------------------------------------------------------------
  # PLATFORMS
  #
  # Only Linux is built and tested here. The macOS and Windows arms are
  # written from `tvision/CMakeLists.txt` and `tvision/source/CMakeLists.txt`,
  # which do support all three, and they are HERE RATHER THAN IN A BRANCH
  # because a CI matrix cannot be started without them. Treat them as a first
  # draft that has never been compiled: see docs/publishing.md.
  #
  # What the cmake files say, and what each arm below is copying:
  #
  #   sources          all 206 on every platform. `win32con.cpp` is
  #                    `#ifdef _WIN32` from its second line to its last and
  #                    `ncurdisp.cpp`/`ncursinp.cpp` are `#ifdef HAVE_NCURSES`
  #                    the same way, so each compiles to an empty object where
  #                    it does not belong. cmake globs with no platform
  #                    filtering for exactly this reason.
  #   compat/windows   included when NOT Windows (it is the shim FOR Windows
  #                    headers, which Windows itself does not need)
  #   compat/malloc    included when not Windows and not Linux/Android --
  #                    which in practice means macOS, and is one `malloc.h`
  #   HAVE_NCURSES     non-Windows only; there is no ncurses on Windows at all
  #   ncurses          `ncursesw` everywhere, falling back to plain `ncurses`
  #                    on Apple, which ships no wide-suffixed library
  #   MSVC             /permissive- and the three /Zc: options are PUBLIC in
  #                    cmake, so they apply to the addon as well as to the
  #                    library, and the /wd list is the library's own
  #
  # `pkg-config` is asked only on Linux. On macOS ncurses is in the SDK and
  # needs no include flag, and a bare CI runner may have no pkg-config at all;
  # on Windows there is neither.
  # ------------------------------------------------------------------------
  #
  # The Linux flags below are `build-tvision/source/CMakeFiles/tvision.dir/
  # flags.make` as cmake generated it, and are meant to stay that way:
  #   -DHAVE_NCURSES -DTVISION_NO_STL
  #   -I include -I include/tvision -I include/tvision/compat/borland
  #                                 -I include/tvision/compat/windows
  #   -fPIC -Wall -Wextra -Wno-deprecated -Wno-unknown-pragmas -Wno-pragmas
  #         -Wno-missing-field-initializers
  #
  # Build with AddressSanitizer:  TVNODE_ASAN=1 npx node-gyp configure && \
  #                               TVNODE_ASAN=1 npx node-gyp build
  # Then run node under it:       test/asan.sh node examples/hello.js
  # Worth having: this addon does manual memory management against a C++
  # library from 1994, and a one-byte overflow here aborts somewhere else
  # entirely, minutes later. The sanitizer goes on the addon and not on
  # Turbo Vision, which is what the cmake build did too -- instrumenting the
  # library as well is a one-line change and a much slower suite. Linux only,
  # because `scripts/asan-flags.sh` is a shell script and because that is the
  # only platform it has ever been run on.
  "includes": [ "tvision-sources.gypi" ],
  "targets": [
    {
      "target_name": "tvision_lib",
      "type": "static_library",
      "sources": [ "<@(tvision_sources)" ],
      # TVISION_NO_STL keeps Turbo Vision's headers from pulling in STL
      # headers it does not need. It is PRIVATE in cmake -- it belongs to the
      # library's own translation units and must not reach src/*.cc, which
      # include <string> and <vector> and mean it.
      "defines": [ "TVISION_NO_STL" ],
      "include_dirs": [
        "tvision/include",
        "tvision/include/tvision",
        "tvision/include/tvision/compat/borland"
      ],
      "conditions": [
        ["OS!='win'", {
          "defines": [ "HAVE_NCURSES" ],
          "include_dirs": [ "tvision/include/tvision/compat/windows" ],
          # Turbo Vision is from 1994 by way of a 2020s fork and does not
          # compile warning-clean under -Wall -Wextra. These are cmake's own
          # suppressions, not ours to widen.
          "cflags_cc": [
            "-fexceptions",
            "-Wno-deprecated",
            "-Wno-unknown-pragmas",
            "-Wno-pragmas",
            "-Wno-missing-field-initializers"
          ],
          "cflags_cc!": [ "-fno-exceptions" ]
        }],
        ["OS=='linux'", {
          # PIC is not optional and is not a default for a gyp
          # `static_library`: a non-PIC archive cannot be linked into a shared
          # object, which is what a .node is. The cmake build passed
          # -DCMAKE_POSITION_INDEPENDENT_CODE=ON for this reason. macOS
          # compiles PIC always, so it is named only here.
          "cflags": [ "-fPIC" ],
          "cflags_cc": [ "-fPIC", "<!@(pkg-config --cflags ncursesw)" ]
        }],
        ["OS=='mac'", {
          # One header, and the reason it is macOS-only is cmake's own
          # condition: not Windows, and not Linux or Android.
          "include_dirs": [ "tvision/include/tvision/compat/malloc" ],
          "xcode_settings": {
            "GCC_ENABLE_CPP_EXCEPTIONS": "YES",
            "CLANG_CXX_LIBRARY": "libc++",
            "CLANG_CXX_LANGUAGE_STANDARD": "c++17",
            "MACOSX_DEPLOYMENT_TARGET": "11.0",
            "WARNING_CFLAGS": [
              "-Wno-deprecated",
              "-Wno-unknown-pragmas",
              "-Wno-pragmas",
              "-Wno-missing-field-initializers"
            ]
          }
        }],
        ["OS=='win'", {
          "defines": [
            "_CRT_NONSTDC_NO_WARNINGS",
            "_CRT_SECURE_NO_WARNINGS",
            # Vista console symbols are needed at compile time
            # (GetCurrentConsoleFontEx and friends) even though the program
            # may still run on older Windows. PRIVATE in cmake.
            "_WIN32_WINNT=0x0600"
          ],
          # Node's own common.gypi defines _HAS_EXCEPTIONS=0, which switches
          # exceptions off inside MSVC's standard library. Turbo Vision throws
          # and this addon relies on it, so the define has to be taken back
          # out -- `ExceptionHandling: 1` alone does not undo it. This is the
          # documented pattern for a node-addon-api addon that uses C++
          # exceptions on Windows, and it was found by running gyp with
          # -DOS=win rather than by reading anything.
          "defines!": [ "_HAS_EXCEPTIONS=0" ],
          "msvs_settings": {
            "VCCLCompilerTool": {
              "ExceptionHandling": 1,
              "AdditionalOptions": [
                "/std:c++17",
                "/permissive-",
                "/Zc:__cplusplus",
                "/Zc:externConstexpr",
                "/Zc:inline"
              ],
              "DisableSpecificWarnings": [
                "4068",
                "4146",
                "4166",
                "4244",
                "4250",
                "4267"
              ]
            }
          }
        }]
      ]
    },
    {
      "target_name": "tvision",
      "dependencies": [ "tvision_lib" ],
      "sources": [ "src/app.cc", "src/views.cc" ],
      "include_dirs": [
        "<!@(node -p \"require('node-addon-api').include_dir\")",
        "tvision/include"
      ],
      # NAPI_VERSION is the support floor, and naming it is the point.
      # Without it the addon compiles against whatever level the installed
      # headers happen to offer, so the oldest Node it runs on is an accident
      # of the machine it was built on rather than a decision. Level 9 is Node
      # 18.17 and up, which `engines` in package.json repeats; level 8 reaches
      # back to Node 12 and buys nothing used here.
      #
      # This is also what makes one prebuilt binary enough. Node-API is
      # ABI-stable across Node majors by contract, so a .node built at level 9
      # loads on 18, 20, 22, 24 and whatever follows -- the per-Node-version
      # build matrix that native addons are remembered for is a cost this
      # project does not pay.
      "defines": [ "NAPI_CPP_EXCEPTIONS", "NAPI_VERSION=9" ],
      "conditions": [
        ["OS!='win'", {
          "cflags_cc": [ "-std=c++17", "-fexceptions" ],
          "cflags_cc!": [ "-fno-exceptions" ]
        }],
        ["OS=='linux'", {
          "cflags_cc": [
            "<!@(pkg-config --cflags ncursesw)",
            "<!@(sh scripts/asan-flags.sh cflags)"
          ],
          "ldflags": [
            "<!@(sh scripts/asan-flags.sh ldflags)",
            "<!@(sh scripts/portable-flags.sh ldflags)"
          ],
          "libraries": [ "<!@(pkg-config --libs ncursesw)" ]
        }],
        ["OS=='mac'", {
          # macOS ships ncurses without the wide suffix, which is the fallback
          # tvision's own CMakeLists takes on APPLE. The headers are in the
          # SDK, so there is nothing to add to the include path and no reason
          # to require pkg-config on a CI runner that may not have it.
          "libraries": [ "-lncurses" ],
          "xcode_settings": {
            "GCC_ENABLE_CPP_EXCEPTIONS": "YES",
            "CLANG_CXX_LIBRARY": "libc++",
            "CLANG_CXX_LANGUAGE_STANDARD": "c++17",
            "MACOSX_DEPLOYMENT_TARGET": "11.0"
          }
        }],
        ["OS=='win'", {
          # No libraries named on purpose. Turbo Vision's own CMakeLists adds
          # none for Windows either -- the console API lives in kernel32 and
          # user32, both of which are in the default set gyp's msvs generator
          # links against.
          #
          # The four options are PUBLIC in cmake, which means they are the
          # library's requirements on whoever compiles against its headers.
          # That is this target.
          "defines": [ "_CRT_NONSTDC_NO_WARNINGS", "_CRT_SECURE_NO_WARNINGS" ],
          "defines!": [ "_HAS_EXCEPTIONS=0" ],
          "msvs_settings": {
            "VCCLCompilerTool": {
              "ExceptionHandling": 1,
              "AdditionalOptions": [
                "/std:c++17",
                "/permissive-",
                "/Zc:__cplusplus",
                "/Zc:externConstexpr",
                "/Zc:inline"
              ]
            }
          }
        }]
      ]
    }
  ]
}
