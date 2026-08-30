#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"
ROOT="$(pwd)"
BUILD="$ROOT/build-appimage"
APPDIR="$BUILD/proxyswitch.AppDir"
ARCH="${ARCH:-$(uname -m)}"

echo "==> checking the source tree"
test -f pyproject.toml || { echo "run this from the proxyswitch folder"; exit 1; }
test -f proxyswitch/gui.py || { echo "proxyswitch/gui.py is missing"; exit 1; }

echo "==> checking python and tk"
python3 -c "import tkinter" 2>/dev/null || {
    echo "tkinter is missing on this machine, and the AppImage bundles it from here."
    echo "install it first:  sudo pacman -S tk"
    exit 1
}

PY_BIN="$(readlink -f "$(command -v python3)")"
PY_TAG="$(python3 -c 'import sys; print("python%d.%d" % sys.version_info[:2])')"
STDLIB="$(python3 -c 'import sysconfig; print(sysconfig.get_paths()["stdlib"])')"
TCL_DIR="$(python3 - <<'EOF'
import glob, os
for pattern in ("/usr/share/tcltk/tcl8.*", "/usr/lib/tcl8.*", "/usr/share/tcl8.*", "/usr/lib64/tcl8.*"):
    for path in sorted(glob.glob(pattern)):
        if os.path.isfile(os.path.join(path, "init.tcl")):
            print(path)
            raise SystemExit
EOF
)"
TK_DIR="$(python3 - <<'EOF'
import glob, os
for pattern in ("/usr/share/tcltk/tk8.*", "/usr/lib/tk8.*", "/usr/share/tk8.*", "/usr/lib64/tk8.*"):
    for path in sorted(glob.glob(pattern)):
        if os.path.isfile(os.path.join(path, "tk.tcl")):
            print(path)
            raise SystemExit
EOF
)"

test -n "$TCL_DIR" || { echo "could not find the tcl script directory"; exit 1; }
test -n "$TK_DIR" || { echo "could not find the tk script directory"; exit 1; }

echo "    python:  $PY_BIN ($PY_TAG)"
echo "    stdlib:  $STDLIB"
echo "    tcl:     $TCL_DIR"
echo "    tk:      $TK_DIR"

echo "==> building the AppDir"
rm -rf "$BUILD"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib" "$APPDIR/usr/share"

cp "$PY_BIN" "$APPDIR/usr/bin/python3"
chmod +x "$APPDIR/usr/bin/python3"

cp -r "$STDLIB" "$APPDIR/usr/lib/$PY_TAG"
rm -rf "$APPDIR/usr/lib/$PY_TAG/test" "$APPDIR/usr/lib/$PY_TAG/idlelib" "$APPDIR/usr/lib/$PY_TAG/turtledemo"
find "$APPDIR/usr/lib/$PY_TAG" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

cp -r "$TCL_DIR" "$APPDIR/usr/share/$(basename "$TCL_DIR")"
cp -r "$TK_DIR" "$APPDIR/usr/share/$(basename "$TK_DIR")"

cp -r proxyswitch "$APPDIR/usr/lib/proxyswitch"
find "$APPDIR/usr/lib/proxyswitch" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

echo "==> collecting shared libraries"
SKIP='^(libc|libm|libdl|libpthread|librt|libutil|libgcc_s|libstdc\+\+|ld-linux.*|libGL.*|libEGL.*|libX11.*|libxcb.*|libXext|libXrender|libXss|libXft|libXau|libXdmcp|libfontconfig|libfreetype|libexpat|libz|libbz2|libcrypt|libssl|libcrypto|libnsl|libresolv|libdrm)\.'

collect() {
    ldd "$1" 2>/dev/null | awk '/=> \//{print $3}' | while read -r lib; do
        base="$(basename "$lib")"
        echo "$base" | grep -Eq "$SKIP" && continue
        test -f "$APPDIR/usr/lib/$base" && continue
        cp -L "$lib" "$APPDIR/usr/lib/$base"
    done
}

collect "$APPDIR/usr/bin/python3"
for so in $(find "$APPDIR/usr/lib/$PY_TAG/lib-dynload" -name "*.so" 2>/dev/null); do
    collect "$so"
done

echo "==> writing AppRun"
cat > "$APPDIR/AppRun" << 'RUNEOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "${0}")")"

export PYTHONHOME="$HERE/usr"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$HERE/usr/lib:$PYTHONPATH"
export LD_LIBRARY_PATH="$HERE/usr/lib:$LD_LIBRARY_PATH"

for candidate in "$HERE"/usr/share/tcl8.*; do
    test -d "$candidate" && export TCL_LIBRARY="$candidate"
done
for candidate in "$HERE"/usr/share/tk8.*; do
    test -d "$candidate" && export TK_LIBRARY="$candidate"
done

if [ "$1" = "--cli" ]; then
    shift
    exec "$HERE/usr/bin/python3" -m proxyswitch "$@"
fi

exec "$HERE/usr/bin/python3" -m proxyswitch gui "$@"
RUNEOF
chmod +x "$APPDIR/AppRun"

cp proxyswitch.svg "$APPDIR/proxyswitch.svg"
mkdir -p "$APPDIR/usr/share/icons/hicolor/scalable/apps"
cp proxyswitch.svg "$APPDIR/usr/share/icons/hicolor/scalable/apps/proxyswitch.svg"

cat > "$APPDIR/proxyswitch.desktop" << 'EOF'
[Desktop Entry]
Type=Application
Name=proxyswitch
GenericName=Proxy Switcher
Comment=Local SOCKS5 router with switchable upstream proxies
Exec=AppRun
Icon=proxyswitch
Terminal=false
Categories=Network;Utility;
Keywords=proxy;socks;vpn;wireguard;
EOF
mkdir -p "$APPDIR/usr/share/applications"
cp "$APPDIR/proxyswitch.desktop" "$APPDIR/usr/share/applications/proxyswitch.desktop"

echo "==> smoke testing the AppDir"
"$APPDIR/AppRun" --cli ls > /dev/null || { echo "the bundled python could not run proxyswitch"; exit 1; }
"$APPDIR/usr/bin/python3" -c "
import os, sys
sys.path.insert(0, '$APPDIR/usr/lib')
import tkinter
print('    tkinter', tkinter.TkVersion, 'ok')
" || { echo "tkinter does not work inside the bundle"; exit 1; }

echo "==> getting appimagetool"
TOOL="$BUILD/appimagetool"
if command -v appimagetool >/dev/null 2>&1; then
    TOOL="$(command -v appimagetool)"
else
    curl -L -o "$TOOL" "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage"
    chmod +x "$TOOL"
fi

echo "==> packing"
export APPIMAGE_EXTRACT_AND_RUN=1
ARCH="$ARCH" "$TOOL" "$APPDIR" "$ROOT/proxyswitch-$ARCH.AppImage"

echo
echo "done: $ROOT/proxyswitch-$ARCH.AppImage"
echo "run it with:      ./proxyswitch-$ARCH.AppImage"
echo "cli mode:         ./proxyswitch-$ARCH.AppImage --cli ls"
