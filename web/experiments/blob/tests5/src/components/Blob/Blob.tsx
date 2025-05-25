import React, { useMemo } from 'react';
import { motion } from 'framer-motion';
import { useDraggable } from '@dnd-kit/core';

interface BlobProps {
  id: string;
  x: number;
  y: number;
  size: number;
  color: string;
  onDragEnd: (id: string, position: { x: number; y: number }) => void;
}

const generateBlobPath = (size: number, seed: number) => {
  const radius = size / 2;
  const centerX = size / 2;
  const centerY = size / 2;
  const points = 8;
  
  // Use a seeded random number generator for consistent paths
  const random = (min: number, max: number) => {
    const x = Math.sin(seed++) * 10000;
    return min + (x - Math.floor(x)) * (max - min);
  };
  
  let path = `M ${centerX + radius * Math.cos(0)} ${centerY + radius * Math.sin(0)}`;
  
  for (let i = 1; i <= points; i++) {
    const angle = (i * 2 * Math.PI) / points;
    const pointRadius = radius * (0.7 + random(0, 0.6));
    const x = centerX + pointRadius * Math.cos(angle);
    const y = centerY + pointRadius * Math.sin(angle);
    path += ` L ${x} ${y}`;
  }
  
  return path + ' Z';
};

const Blob: React.FC<BlobProps> = ({ id, x, y, size, color }) => {
  // Generate a stable path based on the blob's ID
  const path = useMemo(() => {
    const seed = id.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
    return generateBlobPath(size, seed);
  }, [id, size]);
  
  const { attributes, listeners, setNodeRef, transform } = useDraggable({
    id,
  });

  const style = transform ? {
    transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`,
  } : {};

  return (
    <div
      ref={setNodeRef}
      style={{
        position: 'absolute',
        left: x,
        top: y,
        cursor: 'grab',
        touchAction: 'none',
        ...style,
      }}
      {...attributes}
      {...listeners}
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        style={{
          display: 'block',
          filter: 'drop-shadow(0 2px 4px rgba(0,0,0,0.1))',
        }}
      >
        <path
          d={path}
          fill={color}
          style={{
            transition: 'fill 0.2s ease',
          }}
        />
      </svg>
    </div>
  );
};

export default React.memo(Blob);
