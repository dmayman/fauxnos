#!/bin/bash
# Setup FIFO pipes for Spotify streams
set -euo pipefail

# List of FIFO paths (add more here as needed)
FIFOS=(
  "/tmp/spotifystream"
  "/tmp/spotifystream1"
  "/tmp/spotifystream2"
)

for fifo in "${FIFOS[@]}"; do
  # Remove existing FIFO/file if it exists
  if [ -p "$fifo" ] || [ -e "$fifo" ]; then
    rm -f "$fifo"
    echo "Removed existing FIFO at $fifo"
  fi

  # Create new FIFO
  mkfifo "$fifo"
  echo "Created FIFO at $fifo"

  # Set permissions to 666 (readable/writable by all)
  chmod 666 "$fifo"
  echo "Set FIFO permissions to 666 at $fifo"
done

echo "Ready: ${FIFOS[*]}"