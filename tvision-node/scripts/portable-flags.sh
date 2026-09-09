#!/bin/sh
# Emits the flags that make a *redistributable* addon when TVNODE_PORTABLE=1,
# nothing otherwise. Same shape as asan-flags.sh, and for the same reason: gyp
# -D values are strings and the comparison is easy to get silently wrong, and
# a portable build that quietly was not one is discovered on somebody else's
# machine rather than on this one.
#
# What it buys, and what it does not. Static libstdc++ and libgcc take
# libstdc++.so.6 and libgcc_s.so.1 out of the picture entirely, which is the
# dependency most likely to be *older* on the target than on the builder --
# a GLIBCXX_3.4.32 reference against a distro that has 3.4.30 is a hard
# failure at load time and says nothing useful. glibc itself cannot be
# statically linked here (it would break dlopen and NSS, and node loads this
# with dlopen), so the glibc floor is decided by the machine that compiles:
# see tools/pack/Containerfile, which is why that is a container and not this
# machine. ncurses is handled the same way -- by giving the container a static
# libncursesw.a -- because it is a link-time choice, not a flag.
[ "$TVNODE_PORTABLE" = "1" ] || exit 0
case "$1" in
    ldflags) echo "-static-libstdc++ -static-libgcc" ;;
esac
