{
  # Build with AddressSanitizer:  TVNODE_ASAN=1 npx node-gyp rebuild
  # Then run node under it:       test/asan.sh node examples/hello.js
  # Worth having: this addon does manual memory management against a C++
  # library from 1994, and a one-byte overflow here aborts somewhere else
  # entirely, minutes later.
  "targets": [
    {
      "target_name": "tvision",
      "sources": [ "src/app.cc", "src/views.cc" ],
      "include_dirs": [
        "<!@(node -p \"require('node-addon-api').include_dir\")",
        "../tvision/include"
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
      "libraries": [
        "<!(node -p \"require('path').resolve('../build-tvision/libtvision.a')\")",
        "<!@(pkg-config --libs ncursesw)"
      ]
    }
  ]
}
