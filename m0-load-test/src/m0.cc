// Milestone 0. The only question this answers: can a .node built by the
// system toolchain (Ubuntu g++/glibc) be dlopen'd by devbox's nix-provided
// node 22, and still call into a system shared library?
//
// ncursesw is the proxy for that second half on purpose -- it is exactly what
// libtvision links against, so if this loads, the tvision addon's link line
// is not the thing that will break.

#include <napi.h>
#include <ncurses.h>

static Napi::Value CursesVersion(const Napi::CallbackInfo &info)
{
    return Napi::String::New(info.Env(), curses_version());
}

static Napi::Value Add(const Napi::CallbackInfo &info)
{
    Napi::Env env = info.Env();
    if (info.Length() < 2 || !info[0].IsNumber() || !info[1].IsNumber())
        throw Napi::TypeError::New(env, "add(number, number)");
    return Napi::Number::New(env, info[0].As<Napi::Number>().DoubleValue() +
                                  info[1].As<Napi::Number>().DoubleValue());
}

static Napi::Object Init(Napi::Env env, Napi::Object exports)
{
    exports.Set("cursesVersion", Napi::Function::New(env, CursesVersion));
    exports.Set("add", Napi::Function::New(env, Add));
    return exports;
}

NODE_API_MODULE(m0, Init)
