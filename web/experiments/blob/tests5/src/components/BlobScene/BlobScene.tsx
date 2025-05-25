import React, { useState, useCallback } from 'react';
import { DndContext } from '@dnd-kit/core';
import { restrictToWindowEdges } from '@dnd-kit/modifiers';
import Blob from '../Blob/Blob';

interface BlobData {
  id: string;
  x: number;
  y: number;
  size: number;
  color: string;
}

const COLORS = [
  '#FF6B6B',
  '#4ECDC4',
  '#45B7D1',
  '#96CEB4',
  '#FFEEAD',
  '#D4A373',
  '#FEFAE0',
  '#606C38',
];

const BlobScene: React.FC = () => {
  const [blobs] = useState<BlobData[]>(() => {
    // Initialize with 5 blobs at random positions
    return Array.from({ length: 5 }).map((_, index) => ({
      id: `blob-${index}`,
      x: Math.random() * (window.innerWidth - 200) + 100,
      y: Math.random() * (window.innerHeight - 200) + 100,
      size: Math.random() * 80 + 60, // Random size between 60 and 140
      color: COLORS[Math.floor(Math.random() * COLORS.length)],
    }));
  });

  const handleDragEnd = useCallback((id: string, position: { x: number; y: number }) => {
    // Update blob position when dragged
    // Note: In a real app, you might want to update the state here
    // For this simplified version, we're just using initial positions
  }, []);

  return (
    <DndContext modifiers={[restrictToWindowEdges]}>
      <div style={{ 
        position: 'relative', 
        width: '100vw', 
        height: '100vh', 
        overflow: 'hidden', 
        background: '#f0f0f0' 
      }}>
        {blobs.map(blob => (
          <Blob
            key={blob.id}
            id={blob.id}
            x={blob.x}
            y={blob.y}
            size={blob.size}
            color={blob.color}
            onDragEnd={handleDragEnd}
          />
        ))}
      </div>
    </DndContext>
  );
};

export default BlobScene;
