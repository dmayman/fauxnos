import React, { useState, useRef, useEffect, forwardRef, useImperativeHandle } from 'react';
import { useDraggable } from '@dnd-kit/core';

export interface Position {
  x: number;
  y: number;
  isDragging: boolean;
}

export interface SquareRef {
  getPosition: () => Position;
}

interface SquareProps {
  id: string;
  initialX?: number;
  initialY?: number;
  onPositionChange?: (position: Position) => void;
  children?: React.ReactNode;
}

const Square = forwardRef<SquareRef, SquareProps>(({ 
  id, 
  initialX = 0, 
  initialY = 0, 
  onPositionChange,
  children 
}, ref) => {
  const [{ x, y }, setPosition] = useState({ x: initialX, y: initialY });
  const [isDragging, setIsDragging] = useState(false);
  const nodeRef = useRef<HTMLDivElement>(null);
  
  const { 
    attributes,
    listeners,
    setNodeRef,
    transform,
    active
  } = useDraggable({ 
    id,
  });

  // Handle drag state changes
  useEffect(() => {
    if (active && active.id === id) {
      setIsDragging(true);
    } else if (!active) {
      setIsDragging(false);
      
      // Update position when drag ends
      if (transform) {
        setPosition(prev => ({
          x: prev.x + transform.x,
          y: prev.y + transform.y,
        }));
      }
    }
  }, [active, id, transform]);

  // Calculate the current position including any active transform
  const currentX = transform ? x + transform.x : x;
  const currentY = transform ? y + transform.y : y;

  // Notify parent of position changes, but only when dragging or position changes
  const prevPosition = useRef({ x: currentX, y: currentY, isDragging });
  
  useEffect(() => {
    if (
      prevPosition.current.x !== currentX ||
      prevPosition.current.y !== currentY ||
      prevPosition.current.isDragging !== isDragging
    ) {
      onPositionChange?.({ x: currentX, y: currentY, isDragging });
      prevPosition.current = { x: currentX, y: currentY, isDragging };
    }
  }, [currentX, currentY, isDragging, onPositionChange]);

  // Expose position via ref
  useImperativeHandle(ref, () => ({
    getPosition: () => ({ x: currentX, y: currentY, isDragging })
  }));

  // Combine refs
  const setRefs = (el: HTMLDivElement | null) => {
    setNodeRef(el);
    nodeRef.current = el;
  };

  // Invisible drag handle
  const handleStyle: React.CSSProperties = {
    position: 'absolute',
    width: '100%',
    height: '100%',
    cursor: isDragging ? 'grabbing' : 'grab',
    touchAction: 'none',
    zIndex: 10,
    opacity: 0,
  };

  return (
    <>
      <div
        ref={setRefs}
        style={handleStyle}
        {...listeners}
        {...attributes}
      />
      {children}
    </>
  );
});

Square.displayName = 'Square';

export default Square;
