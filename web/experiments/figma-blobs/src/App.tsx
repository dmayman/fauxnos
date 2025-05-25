import React from 'react';
import styled from 'styled-components';
import Blob from './components/Blob/Blob';

const BackgroundPattern = styled.div`
  position: absolute;
  width: 100%;
  height: 100%;
  background-image: 
    radial-gradient(circle at 1px 1px, rgba(255, 255, 255, 0.1) 1px, transparent 0);
  background-size: 40px 40px;
  opacity: 0.3;
  z-index: 0;
`;

const AppContainer = styled.div`
  width: 100vw;
  height: 100vh;
  background: #1E1E1E;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  position: relative;
`;

const ContentArea = styled.div`
  width: 100%;
  max-width: 430px;
  height: 100%;
  max-height: 932px;
  background: #1E1E1E;
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
`;

const BlobText = styled.span`
  color: white;
  font-family: 'Helvetica Neue', sans-serif;
  font-size: 24px;
  font-weight: 500;
  pointer-events: none;
  text-transform: uppercase;
  letter-spacing: 0.5px;
`;

const App: React.FC = () => {
  // Blob data with positions and colors from the Figma design
  const blobs = [
    { 
      id: 1, 
      size: 140, 
      color: 'rgba(198, 214, 184, 0.8)', 
      x: -30, 
      y: 250, 
      text: 'D',
      blur: '15px',
      shadow: '0 12px 40px rgba(0, 0, 0, 0.25)'
    },
    { 
      id: 2, 
      size: 180, 
      color: 'rgba(232, 196, 196, 0.8)', 
      x: 180, 
      y: 150, 
      text: 'G',
      blur: '15px',
      shadow: '0 12px 40px rgba(0, 0, 0, 0.25)'
    },
    { 
      id: 3, 
      size: 130, 
      color: 'rgba(209, 179, 196, 0.8)', 
      x: 300, 
      y: 320, 
      text: 'B',
      blur: '15px',
      shadow: '0 12px 40px rgba(0, 0, 0, 0.25)'
    },
    { 
      id: 4, 
      size: 160, 
      color: 'rgba(184, 216, 216, 0.8)', 
      x: 60, 
      y: 420, 
      text: 'F',
      blur: '15px',
      shadow: '0 12px 40px rgba(0, 0, 0, 0.25)'
    },
    { 
      id: 5, 
      size: 140, 
      color: 'rgba(240, 230, 179, 0.8)', 
      x: 230, 
      y: 480, 
      text: 'H',
      blur: '15px',
      shadow: '0 12px 40px rgba(0, 0, 0, 0.25)'
    },
  ];

  return (
    <AppContainer>
      <BackgroundPattern />
      <ContentArea>
        {blobs.map((blob) => (
          <Blob
            key={blob.id}
            size={blob.size}
            color={blob.color}
            initialX={blob.x}
            initialY={blob.y}
            blur={blob.blur}
            shadow={blob.shadow}
          >
            <BlobText>{blob.text}</BlobText>
          </Blob>
        ))}
      </ContentArea>
    </AppContainer>
  );
};

export default App;
