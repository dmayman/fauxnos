import React, { useState, useCallback, useRef } from 'react';
import { DndContext, MouseSensor, TouchSensor, useSensor, useSensors } from '@dnd-kit/core';
import { restrictToWindowEdges } from '@dnd-kit/modifiers';
import Square, { Position } from './components/Square/Square';
import Goo from 'gooey-react';
import './App.css';

interface DraggableCircle {
  id: string;
  position: { x: number; y: number; isDragging: boolean };
  radius: number;
  color: string;
}

const initialCircles: DraggableCircle[] = [
  { id: 'circle1', position: { x: 100, y: 100, isDragging: false }, radius: 50, color: 'sandybrown' },
  { id: 'circle2', position: { x: 250, y: 150, isDragging: false }, radius: 60, color: 'palevioletred' },
];

function App() {
  const [circles, setCircles] = useState<DraggableCircle[]>(initialCircles);
  const svgRef = useRef<SVGSVGElement>(null);

  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 150, tolerance: 5 } })
  );

  const handlePositionChange = useCallback((id: string, newPosition: Position) => {
    setCircles(prevCircles => {
      const circle = prevCircles.find(c => c.id === id);
      if (!circle) return prevCircles;
      
      // Only update if position actually changed
      if (
        circle.position.x === newPosition.x &&
        circle.position.y === newPosition.y &&
        circle.position.isDragging === newPosition.isDragging
      ) {
        return prevCircles;
      }
      
      return prevCircles.map(c => 
        c.id === id 
          ? { ...c, position: { ...newPosition } } 
          : c
      );
    });
  }, []);

  return (
    <div className="app">
      <DndContext
        sensors={sensors}
        modifiers={[restrictToWindowEdges]}
      >
        <Goo intensity='strong' style={{ height: '100vh', width: '100vw', position: 'relative' }}>
          {/* SVG for rendering the circles */}
          <svg 
            ref={svgRef} 
            width="100%" 
            height="100%" 
            style={{ position: 'absolute', top: 0, left: 0, pointerEvents: 'none' }}
          >
            <g>
              {circles.map(circle => (
                <circle
                  key={circle.id}
                  cx={circle.position.x}
                  cy={circle.position.y}
                  r={circle.radius}
                  fill={circle.color}
                  stroke={circle.position.isDragging ? '#4CAF50' : 'none'}
                  strokeWidth="2"
                  style={{
                    transition: circle.position.isDragging ? 'none' : 'all 0.2s ease-in-out'
                  }}
                />
              ))}
            </g>
          </svg>
          
          {/* Invisible drag handles that float above the SVG */}
          <div style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%' }}>
            {circles.map(circle => (
              <div 
                key={`handle-${circle.id}`}
                style={{
                  position: 'absolute',
                  left: circle.position.x - circle.radius,
                  top: circle.position.y - circle.radius,
                  width: circle.radius * 2,
                  height: circle.radius * 2,
                  borderRadius: '50%',
                  cursor: 'move',
                  zIndex: 10,
                }}
              >
                <Square
                  id={circle.id}
                  initialX={circle.position.x}
                  initialY={circle.position.y}
                  onPositionChange={(pos) => handlePositionChange(circle.id, pos)}
                />
              </div>
            ))}
          </div>
        </Goo>
      </DndContext>
    </div>
  );
}

export default App;
