#!/bin/bash

# Source directory: librespot_dm
LIBRESPOT_DIR="./librespot_dm"

# Destination directory: patch_kit
PATCH_DIR="./patch_kit"

# List of files to copy
FILES=(
    "connect/src/state.rs"
    "playback/src/config.rs"
    "playback/src/player.rs"
    "playback/src/mixer/mod.rs"
    "playback/src/mixer/softmixer.rs"
    "src/main.rs"
    "src/player_event_handler.rs"
)

# Create patch kit folder
echo "Creating patch kit folder at $PATCH_DIR"
mkdir -p "$PATCH_DIR"

# Copy files preserving directory structure
for FILE in "${FILES[@]}"; do
    DEST_DIR="$PATCH_DIR/$(dirname "$FILE")"
    mkdir -p "$DEST_DIR"
    cp "$LIBRESPOT_DIR/$FILE" "$DEST_DIR/"
done

echo "✅ Patch kit created successfully in $PATCH_DIR"
