#!/bin/bash
# Build tvdemo out of a tvision worktree, with the flags binding.gyp uses for
# the library.
#
# It exists for upstream bug reports: a finding here is worth more to magiblot
# as a picture of his own demo than as a description of ours, and tvdemo is not
# something this repo builds otherwise -- node-gyp compiles the library into
# the addon and stops there, and cmake is deliberately not a devbox package.
#
#     git -C tvision-node/tvision worktree add /tmp/wt-bug patches~1
#     devbox run -- bash tools/build-tvdemo.sh /tmp/wt-bug
#     (cd /tmp/wt-bug/examples/tvdemo && /tmp/wt-bug/tvdemo fileview.cpp)
#
# Two minutes a build: 207 sources, an `ar`, and a link. Build it in a
# worktree rather than in the submodule, so the checkout the addon builds from
# is untouched -- and take the *baseline* from `patches~1` rather than
# `master`, so the only difference from `patches` is the one commit under
# examination. A report photographed against master is arguing about every
# unlanded fix at once.
#
# `tvision-node/test/harness.py` drives what comes out (`Pty(argv, env, cwd,
# size=...)`, `.send()`, `.resize()`) and `tools/shot.py` photographs it, which
# is how the pictures in magiblot/tvision#239 were made.
set -e
WT="$1"
[ -d "$WT" ] || { echo "no worktree at $WT"; exit 1; }

OBJ="$WT/_obj"
mkdir -p "$OBJ"

INC=(-I"$WT/include" -I"$WT/include/tvision"
     -I"$WT/include/tvision/compat/borland"
     -I"$WT/include/tvision/compat/windows")
LIBFLAGS=(-std=c++17 -O1 -DHAVE_NCURSES -DTVISION_NO_STL -fPIC
          -Wno-deprecated -Wno-unknown-pragmas -Wno-pragmas
          -Wno-missing-field-initializers -w)

if [ ! -f "$WT/libtvision.a" ]; then
    find "$WT/source/tvision" "$WT/source/platform" -name '*.cpp' > "$OBJ/sources"
    wc -l < "$OBJ/sources" | tr -d ' ' | xargs echo "compiling library sources:"
    < "$OBJ/sources" xargs -P "$(nproc)" -I{} \
        bash -c 'src="$1"; shift; out="$1"; shift; g++ "$@" -c "$src" -o "$out/$(echo "$src" | md5sum | cut -c1-12).o"' \
            _ {} "$OBJ" "${LIBFLAGS[@]}" "${INC[@]}"
    ar rcs "$WT/libtvision.a" "$OBJ"/*.o
fi

echo "linking tvdemo"
g++ -std=c++17 -O1 "${INC[@]}" \
    "$WT"/examples/tvdemo/*.cpp \
    "$WT/libtvision.a" \
    $(pkg-config --libs ncursesw) -lpthread \
    -w -o "$WT/tvdemo"
echo "built $WT/tvdemo"
