#!/bin/bash
# Setup FIFO pipe for go-librespot

FIFO_PATH="/tmp/spotifystream"

# Remove existing FIFO if it exists
if [ -p "$FIFO_PATH" ]; then
    rm -f "$FIFO_PATH"
    echo "Removed existing FIFO at $FIFO_PATH"
fi

# Create new FIFO
mkfifo "$FIFO_PATH"
echo "Created FIFO at $FIFO_PATH"

# Set permissions to 666 (readable/writable by all)
chmod 666 "$FIFO_PATH"
echo "Set FIFO permissions to 666"