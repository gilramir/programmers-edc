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
      "libraries": [ "<!@(pkg-config --libs ncursesw)" ]
    }
  ]
}
