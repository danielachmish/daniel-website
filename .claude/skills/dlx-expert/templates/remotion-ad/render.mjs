import {bundle} from '@remotion/bundler';
import {renderMedia, selectComposition} from '@remotion/renderer';
import path from 'node:path';
import fs from 'node:fs';
// Use a local headless Chrome when present (cloud sandboxes), otherwise let Remotion download its own.
const candidates=[process.env.REMOTION_BROWSER,'/opt/pw-browsers/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell'].filter(Boolean);
const browserExecutable=candidates.find((p)=>fs.existsSync(p))||null;
const serveUrl=await bundle({entryPoint:path.resolve('src/index.tsx')});
const composition=await selectComposition({serveUrl,id:process.argv[3]||'AladinAd',browserExecutable});
let last=0;
await renderMedia({serveUrl,composition,codec:'h264',crf:16,outputLocation:process.argv[2],browserExecutable,concurrency:4,
  onProgress:({progress})=>{if(progress-last>0.2){last=progress;console.log('progress',Math.round(progress*100)+'%');}}});
console.log('rendered',process.argv[2]);
