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
  # The flags below are `build-tvision/source/CMakeFiles/tvision.dir/flags.make`
  # as cmake generated it, and are meant to stay that way:
  #   -DHAVE_NCURSES -DTVISION_NO_STL
  #   -I include -I include/tvision -I include/tvision/compat/borland
  #                                 -I include/tvision/compat/windows
  #   -fPIC -Wall -Wextra -Wno-deprecated -Wno-unknown-pragmas -Wno-pragmas
  #         -Wno-missing-field-initializers
  #
  # Build with AddressSanitizer:  TVNODE_ASAN=1 npx node-gyp rebuild
  # Then run node under it:       test/asan.sh node examples/hello.js
  # Worth having: this addon does manual memory management against a C++
  # library from 1994, and a one-byte overflow here aborts somewhere else
  # entirely, minutes later. The sanitizer goes on the addon and not on
  # Turbo Vision, which is what the cmake build did too -- instrumenting the
  # library as well is a one-line change and a much slower suite.
  "includes": [ "tvision-sources.gypi" ],
  "targets": [
    {
      "target_name": "tvision_lib",
      "type": "static_library",
      "sources": [ "<@(tvision_sources)" ],
      # PIC is not optional and is not a default: a non-PIC archive cannot be
      # linked into a shared object, which is what a .node is. The cmake build
      # passed -DCMAKE_POSITION_INDEPENDENT_CODE=ON for this reason.
      "cflags": [ "-fPIC" ],
      "cflags_cc": [
        "-fPIC",
        "-fexceptions",
        "<!@(pkg-config --cflags ncursesw)"
      ],
      "cflags_cc!": [ "-fno-exceptions" ],
      # TVISION_NO_STL keeps Turbo Vision's headers from pulling in STL
      # headers it does not need. It is PRIVATE in cmake -- it belongs to the
      # library's own translation units and must not reach src/*.cc, which
      # include <string> and <vector> and mean it.
      "defines": [ "HAVE_NCURSES", "TVISION_NO_STL" ],
      "include_dirs": [
        "tvision/include",
        "tvision/include/tvision",
        "tvision/include/tvision/compat/borland",
        "tvision/include/tvision/compat/windows"
      ],
      # Turbo Vision is from 1994 by way of a 2020s fork and does not compile
      # warning-clean under -Wall -Wextra. These are cmake's own suppressions,
      # not ours to widen.
      "cflags_cc+": [
        "-Wno-deprecated",
        "-Wno-unknown-pragmas",
        "-Wno-pragmas",
        "-Wno-missing-field-initializers"
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
      "cflags_cc": [
        "-std=c++17",
        "-fexceptions",
        "<!@(pkg-config --cflags ncursesw)",
        "<!@(sh scripts/asan-flags.sh cflags)"
      ],
      "ldflags": [ "<!@(sh scripts/asan-flags.sh ldflags)" ],
      "cflags_cc!": [ "-fno-exceptions" ],
      "defines": [ "NAPI_CPP_EXCEPTIONS" ],
      "libraries": [ "<!@(pkg-config --libs ncursesw)" ]
    }
  ]
}
