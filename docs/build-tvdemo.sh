#!/bin/bash
# Build tvdemo out of a tvision worktree, with the flags binding.gyp uses for
# the library. Two of these get built -- one commit apart -- so the screenshots
# differ in exactly the zoom fix and nothing else.
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
