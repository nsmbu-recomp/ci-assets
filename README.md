# CI assets

Build inputs for [nsmbu-recomp](https://github.com/nsmbu-recomp/nsmbu-recomp).
These releases are not game downloads.

## AppImage runtime

The tag `appimage-runtime-<commit>` holds `runtime-x86_64` and `runtime-aarch64`.
Those are the pinned type2-runtime files the Linux AppImage is built with.

## Android compiler

The tag `android-clang` holds the compiler that runs on the phone.
Run the Android compiler workflow in this repo to replace that release.
Game release builds download it.
They do not compile LLVM.
