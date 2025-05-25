import React from 'react';

const SVGDefs = () => (
  <svg width="600" height="600" viewBox="0 0 600 600">
    <defs>
      <filter id="goo" colorInterpolationFilters="sRGB">
        <feGaussianBlur in="SourceGraphic" stdDeviation="10" result="blur" />
        <feColorMatrix 
          in="blur" 
          mode="matrix" 
          values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 18 -7" 
          result="goo" 
        />
        <feBlend in="SourceGraphic" in2="goo" />
      </filter>
    </defs>
    <g filter="url(#goo)">
      <circle cx="150" cy="150" style={{stroke: 'none'}} r="100" fill="forestgreen" />
      <circle cx="250" cy="250" style={{stroke: 'none'}} r="100" fill="forestgreen" />
    </g>
  </svg>
);

export default SVGDefs;
