import React, { useRef, useEffect, useState } from 'react';
import { useDraggable } from '@dnd-kit/core';

interface BlobProps {
  id: string;
  r: number;
}

export const Blob: React.FC<BlobProps> = ({ id, r }) => {
  // Create a wrapper div for the dnd-kit to attach to
  // const wrapperRef = useRef<HTMLDivElement>(null);
  // const circleRef = useRef<SVGCircleElement>(null);

  const [{ x, y }, setPosition] = useState({ x: 0, y: 0 });
  
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id
  });

  const currentX = transform ? x + transform.x : x;
  const currentY = transform ? y + transform.y : y;

  const onDragEnd = () => {
    if (transform) {
      setPosition({
        x: x + transform.x,  // Update x position with drag offset
        y: y + transform.y,  // Update y position with drag offset
      });
    }
  };

  const style: React.CSSProperties = {
      transform: `translate3d(${currentX}px, ${currentY}px, 0)`,  // Apply current position
      width: '200px',
      height: '200px',
      backgroundColor: 'white',
      cursor: 'move',  // Changes cursor to indicate draggable
      position: 'absolute',  // Required for transform to work correctly
      left: 0,  // Base position (will be overridden by transform)
      top: 0,   // Base position (will be overridden by transform)
    };

  return (
      <circle 
        // ref={setNodeRef}
        className={`blob ${isDragging ? 'dragging' : ''}`}
        style={style}
        onMouseUp={onDragEnd}     // Handle mouse drag end (custom)
        onTouchEnd={onDragEnd}    // Handle touch drag end (custom)
        id={id}
        cx={0}
        cy={0}
        r={r}
      />
  );
};

export default Blob;
