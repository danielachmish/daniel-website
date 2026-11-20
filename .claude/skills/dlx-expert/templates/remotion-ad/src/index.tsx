import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {Ad, b, TOTAL_BEATS, FPS} from './Ad';

const Root: React.FC = () => (
  <Composition id="AladinAd" component={Ad} durationInFrames={b(TOTAL_BEATS)} fps={FPS} width={1080} height={1920} />
);
registerRoot(Root);
