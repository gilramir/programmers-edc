{
  "targets": [
    {
      "target_name": "m0",
      "sources": [ "src/m0.cc" ],
      "include_dirs": [ "<!@(node -p \"require('node-addon-api').include_dir\")" ],
      "cflags_cc": [ "-std=c++17", "-fexceptions", "<!@(pkg-config --cflags ncursesw)" ],
      "cflags_cc!": [ "-fno-exceptions" ],
      "defines": [ "NAPI_CPP_EXCEPTIONS" ],
      "libraries": [ "<!@(pkg-config --libs ncursesw)" ]
    }
  ]
}
