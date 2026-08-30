{
  "targets": [
    {
      "target_name": "tvision",
      "sources": [ "src/tvnode.cc" ],
      "include_dirs": [
        "<!@(node -p \"require('node-addon-api').include_dir\")",
        "../tvision/include"
      ],
      "cflags_cc": [
        "-std=c++17",
        "-fexceptions",
        "<!@(pkg-config --cflags ncursesw)"
      ],
      "cflags_cc!": [ "-fno-exceptions" ],
      "defines": [ "NAPI_CPP_EXCEPTIONS" ],
      "libraries": [
        "<!(node -p \"require('path').resolve('../build-tvision/libtvision.a')\")",
        "<!@(pkg-config --libs ncursesw)"
      ]
    }
  ]
}
