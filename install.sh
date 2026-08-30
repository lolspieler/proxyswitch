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

echo
echo "==> optional: add it to your application menu"
echo "  cp proxyswitch.desktop ~/.local/share/applications/"
