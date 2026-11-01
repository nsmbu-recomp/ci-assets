#!/usr/bin/env python3
"""Build the SDL3 prefix that nsmbu-recomp release jobs download.

usage:
  build.py linux-packages
  build.py build --platform PLATFORM --prefix DIR
  build.py pack --prefix DIR --out FILE
  build.py manifest --dist DIR

The published manifest must match tools/release/sdl3.py in nsmbu-recomp:
SDL 3.4.18 source pin, and the llvm-mingw sha256 values in toolchains.json.
Windows prefixes are shared plus static (the setup program links the static library).
Linux prefixes are the shared library only, built on Ubuntu 22.04.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

VERSION = "3.4.18"
URL = "https://github.com/libsdl-org/SDL/releases/download/release-3.4.18/SDL3-3.4.18.tar.gz"
UPSTREAM_SHA256 = "9c75cf16330322c217dedd2e0609f1124f1b54b8633e763467b4684d0f4334a3"

MINGW = {
    "llvm-mingw-20260922": {
        "url": "https://github.com/mstorsjo/llvm-mingw/releases/download/20260922/llvm-mingw-20260922-ucrt-x86_64.zip",
        "sha256": "e3ad77d117a4bea19a7a3b333341824d79a5a371004a10e25b8504e7b3047666",
        "dir": "llvm-mingw-20260922-ucrt-x86_64",
        "triple": "x86_64-w64-mingw32",
    },
    "llvm-mingw-20260922-aarch64": {
        "url": "https://github.com/mstorsjo/llvm-mingw/releases/download/20260922/llvm-mingw-20260922-ucrt-aarch64.zip",
        "sha256": "a317514a7a63badd692032c0c2b8e165f630bbaebbe7a3254348051f43a64949",
        "dir": "llvm-mingw-20260922-ucrt-aarch64",
        "triple": "aarch64-w64-mingw32",
    },
}

PLATFORMS = {
    "windows-x86_64": "llvm-mingw-20260922",
    "windows-arm64": "llvm-mingw-20260922-aarch64",
    "linux-x86_64": None,
    "linux-aarch64": None,
}

LINUX_PACKAGES = (
    "build-essential", "cmake", "ninja-build", "pkg-config", "xz-utils", "libvulkan1",
    "libasound2-dev", "libpulse-dev", "libaudio-dev", "libfribidi-dev", "libjack-dev", "libsndio-dev",
    "libx11-dev", "libxext-dev", "libxrandr-dev", "libxcursor-dev", "libxfixes-dev", "libxi-dev", "libxss-dev",
    "libxtst-dev", "libxkbcommon-dev", "libdrm-dev", "libgbm-dev", "libgl1-mesa-dev", "libgles2-mesa-dev",
    "libegl1-mesa-dev", "libdbus-1-dev", "libibus-1.0-dev", "libudev-dev", "libthai-dev", "libusb-1.0-0-dev",
    "libpipewire-0.3-dev", "libwayland-dev", "libdecor-0-dev", "liburing-dev", "wayland-protocols",
    "mesa-vulkan-drivers", "xvfb",
)


def posix(path):
    return path.replace("\\", "/")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url, dest, sha256):
    request = urllib.request.Request(url, headers={"User-Agent": "nsmbu-ci-sdl3"})
    with urllib.request.urlopen(request) as response, open(dest, "wb") as handle:
        shutil.copyfileobj(response, handle)
    got = sha256_file(dest)
    if got != sha256:
        raise SystemExit("%s sha256 %s does not match %s" % (url, got, sha256))


def archive_name(platform):
    return "sdl3-%s.tar.gz" % platform


def assert_prefix(prefix, platform):
    cmake = os.path.join(prefix, "lib", "cmake", "SDL3")
    required = [
        os.path.join(prefix, "LICENSE.txt"),
        os.path.join(cmake, "SDL3Config.cmake"),
        os.path.join(cmake, "SDL3sharedTargets.cmake"),
    ]
    if platform.startswith("windows"):
        required.append(os.path.join(prefix, "bin", "SDL3.dll"))
        required.append(os.path.join(cmake, "SDL3staticTargets.cmake"))
    else:
        required.append(os.path.join(prefix, "lib", "libSDL3.so.0"))
    missing = [path for path in required if not os.path.exists(path)]
    if missing:
        raise SystemExit("SDL prefix is incomplete:\n" + "\n".join(missing))


def safe_extract(archive, dest):
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            parts = member.name.replace("\\", "/").split("/")
            if member.name.startswith("/") or ".." in parts:
                raise SystemExit("unsafe path in archive: " + member.name)
        if sys.version_info >= (3, 12):
            tar.extractall(dest, filter="data")
        else:
            tar.extractall(dest)


def run(args, env=None):
    print("+", " ".join(args), flush=True)
    subprocess.check_call(args, env=env)


def build(platform, prefix):
    if platform not in PLATFORMS:
        raise SystemExit("platform must be one of " + ", ".join(PLATFORMS))
    mingw_key = PLATFORMS[platform]
    if os.path.isdir(prefix):
        shutil.rmtree(prefix)
    os.makedirs(prefix)
    work = tempfile.mkdtemp(prefix="sdl3-build-")
    try:
        tarball = os.path.join(work, "SDL3.tar.gz")
        fetch(URL, tarball, UPSTREAM_SHA256)
        source_root = os.path.join(work, "src")
        os.makedirs(source_root)
        safe_extract(tarball, source_root)
        source = os.path.join(source_root, "SDL3-%s" % VERSION)
        env = os.environ.copy()
        cmake = [
            "cmake", "-S", posix(source), "-B", posix(os.path.join(work, "build")), "-G", "Ninja",
            "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_INSTALL_PREFIX=" + posix(prefix),
            "-DSDL_SHARED=ON",
            "-DSDL_STATIC=" + ("ON" if mingw_key else "OFF"),
            "-DSDL_TESTS=OFF",
            "-DSDL_TEST_LIBRARY=OFF",
            "-DSDL_EXAMPLES=OFF",
            "-DSDL_INSTALL_TESTS=OFF",
        ]
        if mingw_key:
            mingw = MINGW[mingw_key]
            zipped = os.path.join(work, "llvm-mingw.zip")
            fetch(mingw["url"], zipped, mingw["sha256"])
            with zipfile.ZipFile(zipped) as archive:
                archive.extractall(os.path.join(work, "mingw"))
            bindir = os.path.join(work, "mingw", mingw["dir"], "bin")
            triple = mingw["triple"]
            env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
            cmake.extend([
                "-DCMAKE_C_COMPILER=" + posix(os.path.join(bindir, triple + "-clang.exe")),
                "-DCMAKE_CXX_COMPILER=" + posix(os.path.join(bindir, triple + "-clang++.exe")),
                "-DCMAKE_RC_COMPILER=" + posix(os.path.join(bindir, triple + "-windres.exe")),
            ])
        run(cmake, env)
        run(["cmake", "--build", os.path.join(work, "build")], env)
        run(["cmake", "--install", os.path.join(work, "build")], env)
        shutil.copyfile(os.path.join(source, "LICENSE.txt"), os.path.join(prefix, "LICENSE.txt"))
        assert_prefix(prefix, platform)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def pack(prefix, out):
    if os.path.exists(out):
        os.remove(out)
    with tarfile.open(out, "w:gz") as tar:
        tar.add(prefix, arcname=".")


def write_manifest(dist):
    assets = {}
    for platform in PLATFORMS:
        name = archive_name(platform)
        archive = os.path.join(dist, name)
        if not os.path.isfile(archive):
            raise SystemExit("missing " + name)
        digest = sha256_file(archive)
        with open(archive + ".sha256", "w") as handle:
            handle.write("%s  %s\n" % (digest, name))
        assets[platform] = {"name": name, "sha256": digest}
    manifest = {
        "version": VERSION,
        "upstream_sha256": UPSTREAM_SHA256,
        "mingw_sha256": {key: value["sha256"] for key, value in MINGW.items()},
        "assets": assets,
    }
    with open(os.path.join(dist, "sdl3.json"), "w") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")
    print("wrote sdl3.json")


def main(argv):
    parser = argparse.ArgumentParser(description="Build the release-CI SDL3 prefix")
    parser.add_argument("command", choices=("linux-packages", "build", "pack", "manifest"))
    parser.add_argument("--platform")
    parser.add_argument("--prefix")
    parser.add_argument("--out")
    parser.add_argument("--dist")
    args = parser.parse_args(argv)
    if args.command == "linux-packages":
        print(" ".join(LINUX_PACKAGES))
        return
    if args.command == "build":
        if not args.platform or not args.prefix:
            raise SystemExit("build needs --platform and --prefix")
        build(args.platform, args.prefix)
        return
    if args.command == "pack":
        if not args.prefix or not args.out:
            raise SystemExit("pack needs --prefix and --out")
        pack(args.prefix, args.out)
        return
    if not args.dist:
        raise SystemExit("manifest needs --dist")
    write_manifest(args.dist)


if __name__ == "__main__":
    main(sys.argv[1:])
