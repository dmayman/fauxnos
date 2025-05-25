import React from 'react';
import Draggable from 'react-draggable';
import styled from 'styled-components';

interface BlobProps {
  color: string;
  size: number;
  initialX?: number;
  initialY?: number;
  blur?: string;
  shadow?: string;
  children?: React.ReactNode;
}

const BlobContainer = styled.div<{ 
  size: number; 
  color: string; 
  blur?: string;
  shadow?: string;
 }>`
  width: ${(props) => props.size}px;
  height: ${(props) => props.size}px;
  background: ${(props) => props.color};
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: move;
  box-shadow: ${(props) => props.shadow || '0 4px 12px rgba(0, 0, 0, 0.2)'};
  -webkit-backdrop-filter: ${(props) => props.blur ? `blur(${props.blur})` : 'none'};
  backdrop-filter: ${(props) => props.blur ? `blur(${props.blur})` : 'none'};
  -webkit-transition: all 0.3s ease;
  -moz-transition: all 0.3s ease;
  -o-transition: all 0.3s ease;
  transition: all 0.3s ease;
  position: absolute;
  user-select: none;
  
  &:hover {
    transform: scale(1.05);
    box-shadow: 0 12px 24px rgba(0, 0, 0, 0.25);
    z-index: 10;
  }
`;

const Blob: React.FC<BlobProps> = ({
  color,
  size,
  initialX = 0,
  initialY = 0,
  blur,
  shadow,
  children,
}) => {
  const nodeRef = React.useRef<HTMLDivElement>(null);
  
  return (
    <Draggable
      nodeRef={nodeRef as React.RefObject<HTMLElement>}
      defaultPosition={{ x: initialX, y: initialY }}
      bounds="parent"
    >
      <BlobContainer 
        ref={nodeRef} 
        size={size} 
        color={color}
        blur={blur}
        shadow={shadow}
      >
        {children}
      </BlobContainer>
    </Draggable>
  );
};

export default Blob;
