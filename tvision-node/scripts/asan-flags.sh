#!/bin/sh
# Emits sanitizer flags when TVNODE_ASAN=1, nothing otherwise. binding.gyp
# calls this instead of using a gyp `condition`, because gyp -D values are
# strings and the comparison is easy to get subtly, silently wrong -- an ASAN
# build that is not actually instrumented passes every test for the wrong
# reason. A shell script either prints the flags or it does not.
[ "$TVNODE_ASAN" = "1" ] || exit 0
case "$1" in
    cflags)  echo "-fsanitize=address -fno-omit-frame-pointer -g" ;;
    ldflags) echo "-fsanitize=address" ;;
esac
