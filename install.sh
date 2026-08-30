#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "==> checking structure"
test -f pyproject.toml || { echo "pyproject.toml missing, are you in the right folder?"; exit 1; }
test -f proxyswitch/gui.py || { echo "proxyswitch/gui.py missing, the package folder is not where it should be"; exit 1; }

echo "==> checking tk"
if ! python3 -c "import tkinter" 2>/dev/null; then
    echo "tkinter is missing. On Arch install it with:  sudo pacman -S tk"
    exit 1
fi

echo "==> installing"
if command -v pipx >/dev/null 2>&1; then
    pipx install --force .
    echo
    echo "done. start it with:  proxyswitch-gui"
    echo "if the command is not found, run:  pipx ensurepath   and open a new terminal"
else
    echo "pipx not found. Install it with:  sudo pacman -S python-pipx"
    echo "or skip installing and run it straight from this folder:"
    echo "  python3 -m proxyswitch gui"
    exit 1
fi

echo "==> adding it to your application menu"
mkdir -p ~/.local/share/applications
mkdir -p ~/.local/share/icons/hicolor/scalable/apps
cp proxyswitch.svg ~/.local/share/icons/hicolor/scalable/apps/proxyswitch.svg
cp proxyswitch.desktop ~/.local/share/applications/proxyswitch.desktop

if ! command -v proxyswitch-gui >/dev/null 2>&1; then
    HERE="$(pwd)"
    sed -i "s|^Exec=.*|Exec=python3 -m proxyswitch gui|" ~/.local/share/applications/proxyswitch.desktop
    sed -i "/^Exec=/a Path=$HERE" ~/.local/share/applications/proxyswitch.desktop
fi

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database ~/.local/share/applications
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t ~/.local/share/icons/hicolor 2>/dev/null

echo
echo "it should now show up in your launcher. test it without one:"
echo "  gtk-launch proxyswitch"
