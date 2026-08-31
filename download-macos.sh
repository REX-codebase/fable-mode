#!/bin/sh
# Download and install the latest checksum-verified (but unsigned)
# Fable-Mode macOS release for the current CPU architecture.
set -eu

REPO='REX-codebase/fable-mode'
API_URL="https://api.github.com/repos/$REPO/releases/latest"
INSTALL_DIR=${1:-"$HOME/.local/bin"}
TMP_DIR=''
TEMP_OUTPUT=''

fail() {
    printf 'download-macos: ERROR: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "required macOS command '$1' was not found"
}

# These are the standard macOS tools used below.  In particular, plutil is
# used as a JSON parser; no API response is ever interpreted as shell code.
for command_name in curl mktemp uname plutil unzip shasum awk grep rm cp mkdir chmod mv; do
    require_command "$command_name"
done

[ "$(uname -s)" = 'Darwin' ] || fail 'this downloader supports macOS only'

MACHINE=$(uname -m)
case "$MACHINE" in
    x86_64) ARCH='x86_64' ;;
    arm64) ARCH='arm64' ;;
    *) fail "unsupported macOS architecture '$MACHINE' (supported: x86_64, arm64)" ;;
esac

# mktemp creates a private directory (umask also protects downloaded files).
umask 077
TMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/fable-mode-download.XXXXXX") || fail 'could not create a secure temporary directory'
cleanup() {
    if [ -n "$TEMP_OUTPUT" ]; then
        rm -f "$TEMP_OUTPUT"
    fi
    if [ -n "$TMP_DIR" ]; then
        rm -rf "$TMP_DIR"
    fi
}
trap cleanup EXIT HUP INT TERM

API_FILE="$TMP_DIR/release.json"
ASSETS_FILE="$TMP_DIR/assets.json"

# Keep the status code separate so a genuine GitHub 404 can be reported as
# "no release", while network and server errors remain distinct failures.
HTTP_STATUS=$(curl -sS -L --proto '=https' --proto-redir '=https' \
    -H 'Accept: application/vnd.github+json' \
    -H 'User-Agent: fable-mode-release-downloader' \
    -o "$API_FILE" -w '%{http_code}' "$API_URL") \
    || fail 'could not contact the GitHub Releases API'
case "$HTTP_STATUS" in
    200) ;;
    404) fail 'no GitHub Release exists yet for this repository' ;;
    *) fail "GitHub Releases API returned HTTP $HTTP_STATUS" ;;
esac

plutil -lint -o /dev/null "$API_FILE" >/dev/null 2>&1 \
    || fail 'GitHub returned an invalid release JSON response'

TAG=$(plutil -extract tag_name raw -o - "$API_FILE" 2>/dev/null) \
    || fail 'latest release did not contain a tag name'
printf '%s\n' "$TAG" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$' \
    || fail "latest release has an unsupported tag '$TAG'"

ASSET_NAME="fable-mode-${TAG}-macos-${ARCH}.zip"
EXPECTED_ARCHIVE_URL="https://github.com/${REPO}/releases/download/${TAG}/${ASSET_NAME}"
EXPECTED_SUMS_URL="https://github.com/${REPO}/releases/download/${TAG}/SHA256SUMS"

plutil -extract assets json -o "$ASSETS_FILE" "$API_FILE" 2>/dev/null \
    || fail 'latest release did not contain a usable assets list'

archive_url=''
sums_url=''
asset_index=0
while asset_name=$(plutil -extract "${asset_index}.name" raw -o - "$ASSETS_FILE" 2>/dev/null); do
    asset_url=$(plutil -extract "${asset_index}.browser_download_url" raw -o - "$ASSETS_FILE" 2>/dev/null) \
        || fail "release asset '$asset_name' did not contain a download URL"
    case "$asset_name" in
        "$ASSET_NAME")
            [ -z "$archive_url" ] || fail "release contains duplicate asset '$ASSET_NAME'"
            [ "$asset_url" = "$EXPECTED_ARCHIVE_URL" ] \
                || fail "release asset '$ASSET_NAME' has an unexpected download URL"
            archive_url=$asset_url
            ;;
        SHA256SUMS)
            [ -z "$sums_url" ] || fail 'release contains duplicate SHA256SUMS assets'
            [ "$asset_url" = "$EXPECTED_SUMS_URL" ] \
                || fail 'release SHA256SUMS asset has an unexpected download URL'
            sums_url=$asset_url
            ;;
    esac
    asset_index=$((asset_index + 1))
done

[ -n "$archive_url" ] || fail "latest release has no macOS $ARCH asset named '$ASSET_NAME'"
[ -n "$sums_url" ] || fail 'latest release has no SHA256SUMS asset'

ARCHIVE_FILE="$TMP_DIR/$ASSET_NAME"
SUMS_FILE="$TMP_DIR/SHA256SUMS"
curl -fsS -L --proto '=https' --proto-redir '=https' \
    -H 'User-Agent: fable-mode-release-downloader' -o "$ARCHIVE_FILE" "$archive_url" \
    || fail "could not download '$ASSET_NAME'"
curl -fsS -L --proto '=https' --proto-redir '=https' \
    -H 'User-Agent: fable-mode-release-downloader' -o "$SUMS_FILE" "$sums_url" \
    || fail 'could not download SHA256SUMS'

# Accept only a conventional SHA-256 line for this exact, generated basename.
# The checksum text is data: it is never interpreted or passed to a shell.
CHECKSUM=$(awk -v target="$ASSET_NAME" '
    NF == 2 && length($1) == 64 && $1 !~ /[^[:xdigit:]]/ {
        name = $2
        sub(/^\*/, "", name)
        if (name == target) {
            if (found) exit 2
            value = $1
            found = 1
        }
    }
    END {
        if (!found) exit 3
        print value
    }
' "$SUMS_FILE") || fail "SHA256SUMS has no unambiguous checksum for '$ASSET_NAME'"

# Verify through shasum itself, using a generated one-line check file whose
# basename and hash have both been validated above.
VERIFY_FILE="$TMP_DIR/verify.txt"
printf '%s  %s\n' "$CHECKSUM" "$ASSET_NAME" > "$VERIFY_FILE"
(
    cd "$TMP_DIR" || exit 1
    shasum -a 256 -c "$VERIFY_FILE"
) || fail 'SHA-256 checksum mismatch; archive was not extracted'

# The release builder puts exactly one executable at the archive root.  Reject
# all other layouts before unzip, including path traversal entries.
ARCHIVE_ENTRIES=$(unzip -Z1 "$ARCHIVE_FILE" 2>/dev/null) \
    || fail 'downloaded archive is not a readable ZIP file'
[ "$ARCHIVE_ENTRIES" = 'fable-mode' ] \
    || fail 'downloaded archive has an unexpected layout; refusing to extract'
EXTRACT_DIR="$TMP_DIR/extracted"
mkdir "$EXTRACT_DIR"
unzip -q "$ARCHIVE_FILE" -d "$EXTRACT_DIR" \
    || fail 'could not extract the verified archive'
[ -f "$EXTRACT_DIR/fable-mode" ] || fail "archive did not contain executable 'fable-mode'"

if [ -e "$INSTALL_DIR" ] && [ ! -d "$INSTALL_DIR" ]; then
    fail "install path exists but is not a directory: $INSTALL_DIR"
fi
mkdir -p "$INSTALL_DIR" || fail "could not create install directory: $INSTALL_DIR"
OUTPUT_FILE="$INSTALL_DIR/fable-mode"
# A same-directory temporary file plus rename prevents a partial executable
# from being presented if copying is interrupted.
TEMP_OUTPUT=$(mktemp "$INSTALL_DIR/.fable-mode.tmp.XXXXXX") \
    || fail "could not create temporary output in: $INSTALL_DIR"
cp "$EXTRACT_DIR/fable-mode" "$TEMP_OUTPUT" \
    || fail 'could not copy executable to the install directory'
chmod 755 "$TEMP_OUTPUT" || fail 'could not set executable permissions'
mv -f "$TEMP_OUTPUT" "$OUTPUT_FILE" || fail 'could not install executable atomically'
TEMP_OUTPUT=''

printf 'Installed verified executable: %s\n' "$OUTPUT_FILE"
printf 'Next: "%s" install --yes\n' "$OUTPUT_FILE"
