import {bundle} from '@remotion/bundler';
import {renderStill, selectComposition} from '@remotion/renderer';
import path from 'node:path';
import fs from 'node:fs';
// Use a local headless Chrome when present (cloud sandboxes), otherwise let Remotion download its own.
const candidates=[process.env.REMOTION_BROWSER,'/opt/pw-browsers/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell'].filter(Boolean);
const browserExecutable=candidates.find((p)=>fs.existsSync(p))||null;
const frames=process.argv.slice(3).map(Number); const out=process.argv[2];
const serveUrl=await bundle({entryPoint:path.resolve('src/index.tsx')});
const composition=await selectComposition({serveUrl,id:process.env.COMP||'AladinAd',browserExecutable});
for(const f of frames){await renderStill({serveUrl,composition,frame:f,output:`${out}/f${String(f).padStart(3,'0')}.png`,browserExecutable,scale:0.5});}
console.log('done',frames.length);
