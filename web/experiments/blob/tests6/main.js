document.addEventListener('DOMContentLoaded', () => {
  // Blob configuration
  const blobConfigs = [
    { id: 'blob1', cx: 100, cy: 100, r: 40 },
    { id: 'blob2', cx: 250, cy: 150, r: 60 },
    { id: 'blob3', cx: 400, cy: 200, r: 50 },
    { id: 'blob4', cx: 200, cy: 300, r: 70 },
    { id: 'blob5', cx: 350, cy: 350, r: 45 }
  ];

  const svg = document.getElementById('blob-container');
  const blobsGroup = document.querySelector('.blobs');
  
  // Create blobs
  blobConfigs.forEach(config => {
    const blob = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    blob.setAttribute('class', 'blob');
    blob.setAttribute('id', config.id);
    blob.setAttribute('cx', config.cx);
    blob.setAttribute('cy', config.cy);
    blob.setAttribute('r', config.r);
    blob.setAttribute('data-draggable', '');
    blob.setAttribute('data-dnd-kit-draggable', '');
    blobsGroup.appendChild(blob);
  });

  // Initialize dnd-kit
  const draggableItems = Array.from(document.querySelectorAll('[data-dnd-kit-draggable]'));
  let activeId = null;
  let initialPosition = { x: 0, y: 0 };
  let currentPosition = { x: 0, y: 0 };

  // Convert screen coordinates to SVG coordinates
  function getSVGPoint(x, y) {
    const pt = svg.createSVGPoint();
    pt.x = x;
    pt.y = y;
    return pt.matrixTransform(svg.getScreenCTM().inverse());
  }

  // Handle mouse down
  function onMouseDown(event) {
    const target = event.target.closest('[data-dnd-kit-draggable]');
    if (!target) return;

    activeId = target.id;
    target.classList.add('dragging');
    
    // Store initial position
    const svgPoint = getSVGPoint(event.clientX, event.clientY);
    initialPosition = {
      x: parseFloat(target.getAttribute('cx')),
      y: parseFloat(target.getAttribute('cy'))
    };
    currentPosition = { x: svgPoint.x, y: svgPoint.y };

    // Add event listeners
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
    
    event.preventDefault();
  }

  // Handle mouse move
  function onMouseMove(event) {
    if (!activeId) return;
    
    const blob = document.getElementById(activeId);
    if (!blob) return;
    
    // Get current mouse position in SVG coordinates
    const svgPoint = getSVGPoint(event.clientX, event.clientY);
    
    // Calculate delta from initial position
    const dx = svgPoint.x - currentPosition.x;
    const dy = svgPoint.y - currentPosition.y;
    
    // Update blob position
    const newX = initialPosition.x + dx;
    const newY = initialPosition.y + dy;
    
    blob.setAttribute('cx', newX);
    blob.setAttribute('cy', newY);
  }

  // Handle mouse up
  function onMouseUp() {
    if (!activeId) return;
    
    const blob = document.getElementById(activeId);
    if (blob) {
      blob.classList.remove('dragging');
    }
    
    // Clean up
    document.removeEventListener('mousemove', onMouseMove);
    document.removeEventListener('mouseup', onMouseUp);
    activeId = null;
  }

  // Add event listeners to all draggable items
  draggableItems.forEach(item => {
    item.addEventListener('mousedown', onMouseDown);
    item.style.cursor = 'move';
  });

  // Clean up function
  return () => {
    draggableItems.forEach(item => {
      item.removeEventListener('mousedown', onMouseDown);
    });
    document.removeEventListener('mousemove', onMouseMove);
    document.removeEventListener('mouseup', onMouseUp);
  };
});
