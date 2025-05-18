#!/bin/bash

# Set this to the root of your librespot fork
LIBRESPOT_DIR="../librespot_dm"

# Check if LIBRESPOT_DIR exists
if [ ! -d "$LIBRESPOT_DIR" ]; then
    echo "Error: Librespot directory not found at $LIBRESPOT_DIR"
    exit 1
fi

# Copy each patch file to its destination
echo "Patching librespot..."

cp connect/src/state.rs "$LIBRESPOT_DIR/connect/src/state.rs"
cp playback/src/config.rs "$LIBRESPOT_DIR/playback/src/config.rs"
cp playback/src/player.rs "$LIBRESPOT_DIR/playback/src/player.rs"
cp playback/src/mixer/mod.rs "$LIBRESPOT_DIR/playback/src/mixer/mod.rs"
cp playback/src/mixer/softmixer.rs "$LIBRESPOT_DIR/playback/src/mixer/softmixer.rs"
cp src/main.rs "$LIBRESPOT_DIR/src/main.rs"
cp src/player_event_handler.rs "$LIBRESPOT_DIR/src/player_event_handler.rs"

echo "✅ Patch applied successfully."
