#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ "$(uname -s)" == Darwin ]] || { echo 'macOS required' >&2; exit 1; }
export PYINSTALLER_CONFIG_DIR="$PWD/build/pyinstaller-cache"
version="1.1"
mkdir -p "$PYINSTALLER_CONFIG_DIR"
python3 scripts/make_icon.py
python3 -m PyInstaller --noconfirm --clean ConfigDiff.spec
mkdir -p "release/$version"
# The app bundle is an intermediate build artifact; only the DMG is published.
rm -rf "release/$version/ConfigDiff.app"
rm -f "release/$version/ConfigDiff-$version.dmg"
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
cp -R dist/ConfigDiff.app "$stage/"
ln -s /Applications "$stage/Applications"
cp LICENSE THIRD_PARTY_NOTICES.md "$stage/"
if ! hdiutil create -volname "ConfigDiff $version" -srcfolder "$stage" -ov -format UDZO "release/$version/ConfigDiff-$version.dmg"; then
  # Some managed Macs do not expose DiskManagement; makehybrid writes a valid
  # (larger, uncompressed) HFS disk image without mounting a temporary device.
  rm -f "release/$version/ConfigDiff-$version.dmg"
  hdiutil makehybrid -o "release/$version/ConfigDiff-$version.dmg" -hfs -hfs-volume-name "ConfigDiff $version" "$stage"
fi
