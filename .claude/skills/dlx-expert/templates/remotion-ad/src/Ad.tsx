import React from 'react';
import {
  AbsoluteFill, Img, Audio, Sequence, staticFile, useCurrentFrame, useVideoConfig,
  interpolate, spring, Easing, continueRender, delayRender,
} from 'remotion';

// Heebo (variable, OFL) served locally: the render browser cannot fetch Google Fonts through the proxy.
const fontFamily = 'HeeboLocal';
if (typeof document !== 'undefined') {
  const handle = delayRender('font');
  const faces = [
    new FontFace(fontFamily, `url(${staticFile('fonts/heebo-hebrew.woff2')})`, {weight: '100 900', unicodeRange: 'U+0307-0308, U+0590-05FF, U+200C-2010, U+20AA, U+25CC, U+FB1D-FB4F'}),
    new FontFace(fontFamily, `url(${staticFile('fonts/heebo-latin.woff2')})`, {weight: '100 900'}),
  ];
  Promise.all(faces.map((f) => f.load().then((l) => document.fonts.add(l)))).then(() => continueRender(handle)).catch(() => continueRender(handle));
}

// ---------- timing: every event sits on the music grid (115 BPM) ----------
export const FPS = 30;
const BEAT = (60 / 115) * FPS;
export const b = (n: number) => Math.round(n * BEAT);
export const TOTAL_BEATS = 33.5;

const C = {bg: '#0d110e', lime: '#84cc2d', white: '#f4f6f2'};
const EASE_IN_OUT = Easing.bezier(0.65, 0, 0.35, 1);
const EASE_OUT = Easing.bezier(0.16, 1, 0.3, 1);
const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const PRODUCTS = ['p3_cut.png', 'p4_cut.png', 'p5_cut.png', 'p6_cut.png', 'p7_cut.png', 'p2_cut.png'];

const Grain: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill style={{pointerEvents: 'none', mixBlendMode: 'overlay', opacity: 0.16}}>
      <svg width="100%" height="100%"><filter id="n"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed={f % 30} /></filter>
        <rect width="100%" height="100%" filter="url(#n)" /></svg>
    </AbsoluteFill>
  );
};
const Vignette: React.FC = () => (
  <AbsoluteFill style={{pointerEvents: 'none', background: 'radial-gradient(ellipse at 50% 42%, rgba(0,0,0,0) 45%, rgba(0,0,0,0.6) 100%)'}} />
);

// Headline in the safe top band. Words slam in on the beat; it leaves with a hard cut (no dissolve overlap).
const Headline: React.FC<{words: {t: string; accent?: boolean}[]; at: number; until?: number; size?: number; y?: number}> = ({words, at, until, size = 140, y = 300}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  if (f < at || (until !== undefined && f >= until)) return null;
  return (
    <div style={{position: 'absolute', top: y, left: 70, right: 70, direction: 'rtl', textAlign: 'center', fontFamily, fontWeight: 900,
      fontSize: size, lineHeight: 1.02, letterSpacing: -2, color: C.white}}>
      {words.map((w, i) => {
        const s = spring({frame: f - at - i * 2, fps, config: {damping: 14, stiffness: 260, mass: 0.6}});
        return <span key={i} style={{display: 'inline-block', marginLeft: size * 0.22, color: w.accent ? C.lime : C.white,
          transform: `translateY(${(1 - s) * 50}px) scale(${1.25 - 0.25 * s})`, opacity: Math.min(1, s * 2),
          textShadow: '0 6px 30px rgba(0,0,0,0.5)'}}>{w.t}</span>;
      })}
    </div>
  );
};

const Slatwall: React.FC = () => (
  <AbsoluteFill style={{background: 'repeating-linear-gradient(180deg, #1c231d 0px, #1c231d 54px, #090c09 54px, #090c09 62px)'}}>
    <AbsoluteFill style={{background: 'radial-gradient(ellipse at 50% 35%, rgba(132,204,45,0.12), rgba(0,0,0,0) 60%)'}} />
  </AbsoluteFill>
);

const Hook: React.FC<{x: number; y: number}> = ({x, y}) => (
  <div style={{position: 'absolute', left: x - 6, top: y - 14, width: 12, height: 60, borderRadius: 6, background: 'linear-gradient(90deg,#7d8780,#c3ccc5,#6f7872)',
    boxShadow: '0 8px 10px rgba(0,0,0,0.6)'}} />
);

const Pack: React.FC<{src: string; x: number; y: number; h: number; enter?: number; exit?: number; seed: number; from?: 'top' | 'bottom'}> =
  ({src, x, y, h, enter = -100, exit, seed, from = 'top'}) => {
    const f = useCurrentFrame();
    const {fps} = useVideoConfig();
    const s = spring({frame: f - enter, fps, config: {damping: 10, stiffness: 170, mass: 0.6}});
    const swing = Math.sin((f - enter) / 3.5 + seed) * 6 * Math.exp(-Math.max(0, f - enter) / 12) * (f >= enter ? 1 : 0);
    let ty = (1 - s) * (from === 'top' ? -700 : 900);
    let op = f >= enter ? 1 : 0;
    let blur = (1 - s) * 10;
    if (exit !== undefined && f >= exit) {
      const e = interpolate(f, [exit, exit + 7], [0, 1], {...clamp, easing: Easing.in(Easing.cubic)});
      ty -= e * 900; blur += e * 14; op *= 1 - e * 0.6;
    }
    return (
      <div style={{position: 'absolute', left: x - h * 0.27, top: y, height: h, opacity: op, filter: `blur(${blur}px)`,
        transform: `translateY(${ty}px) rotate(${swing}deg)`, transformOrigin: '50% 3%'}}>
        <Img src={staticFile('products/' + src)} style={{height: h, filter: 'drop-shadow(0 28px 22px rgba(0,0,0,0.6))'}} />
      </div>
    );
  };

// 1. hook: macro on the last pack, it gets taken, pull back to an empty wall
const S1: React.FC = () => {
  const f = useCurrentFrame();
  const z = interpolate(f, [b(1.4), b(3)], [2.3, 1.0], {...clamp, easing: EASE_IN_OUT});
  const hooks: [number, number][] = [[200, 640], [540, 600], [880, 650], [260, 1060], [600, 1020], [900, 1080]];
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{transform: `scale(${z})`, transformOrigin: '50% 47%'}}>
        <Slatwall />
        {hooks.map(([x, y], i) => <Hook key={i} x={x} y={y} />)}
        <Pack src="p3_cut.png" x={540} y={600} h={360} seed={1} exit={b(1)} />
      </AbsoluteFill>
      <Headline words={[{t: 'המדף'}, {t: 'ריק.', accent: true}]} at={3} until={b(2.5)} size={160} />
      <Headline words={[{t: 'שוב.'}]} at={b(2.5)} until={b(4.5)} size={160} />
    </AbsoluteFill>
  );
};

const Phone: React.FC<{children: React.ReactNode; w: number}> = ({children, w}) => (
  <div style={{width: w, height: w * 2.08, borderRadius: w * 0.15, background: '#0b0b0c', padding: w * 0.032,
    boxShadow: '0 60px 120px rgba(0,0,0,0.6), 0 0 0 3px #2b2f2c, inset 0 0 0 2px #444'}}>
    <div style={{position: 'relative', width: '100%', height: '100%', borderRadius: w * 0.12, overflow: 'hidden', background: '#fff'}}>
      {children}
      <div style={{position: 'absolute', top: 0, left: 0, right: 0, height: 92, background: '#fff', fontFamily, fontWeight: 700, fontSize: 30,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 54px', color: '#111'}}>
        <span>9:41</span><span style={{letterSpacing: 2}}>●●●</span>
      </div>
      <div style={{position: 'absolute', top: 20, left: '50%', width: w * 0.3, height: 52, marginLeft: -w * 0.15, background: '#000', borderRadius: 999}} />
      <AbsoluteFill style={{background: 'linear-gradient(125deg, rgba(255,255,255,0.10) 0%, rgba(255,255,255,0) 35%)', pointerEvents: 'none'}} />
    </div>
  </div>
);

// 2+3. order in the real site, then push in on the order sheet
const S2: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const W = 640, PH = W * 2.08;
  const enter = spring({frame: f, fps, config: {damping: 18, stiffness: 120}});
  const drift = interpolate(f, [0, b(3.5)], [1, 1.04], clamp);
  const scroll = interpolate(f, [b(0.8), b(3)], [0, 330], {...clamp, easing: EASE_IN_OUT}); // BASELINE rows only
  const push = interpolate(f, [b(3.5), b(4.3)], [0, 1], {...clamp, easing: EASE_IN_OUT});
  const scale = drift * (1 + 0.28 * push);
  const ty = -620 * push;
  const sheet = spring({frame: f - b(3.3), fps, config: {damping: 20, stiffness: 150}});
  const qtyP = interpolate(f, [b(4.5), b(6.5)], [0, 1], {...clamp, easing: Easing.in(Easing.quad)});
  const qty = Math.max(1, Math.round(1 + 19 * qtyP));
  const tapAt = b(7.5);
  const done = spring({frame: f - b(8), fps, config: {damping: 14, stiffness: 170}});
  const exit = interpolate(f, [b(9.6), b(10)], [0, 1], {...clamp, easing: Easing.in(Easing.cubic)});
  const holding = f >= b(4.5) && f < b(6.5);
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{background: C.bg}} />
      <AbsoluteFill style={{background: 'radial-gradient(ellipse at 50% 55%, rgba(132,204,45,0.18), rgba(0,0,0,0) 60%)'}} />
      <div style={{position: 'absolute', left: (1080 - W) / 2, top: 600 + (1 - enter) * 1500,
        transform: `translateY(${ty - exit * 1800}px) scale(${scale})`, transformOrigin: `50% ${PH * 0.78}px`, filter: `blur(${exit * 8}px)`}}>
        <Phone w={W}>
          <Img src={staticFile('site.png')} style={{width: '100%', marginTop: 92, transform: `translateY(${-scroll}px)`}} />
          <div style={{position: 'absolute', left: 0, right: 0, bottom: 0, height: 620, background: '#fff', borderRadius: '44px 44px 0 0',
            boxShadow: '0 -20px 60px rgba(0,0,0,0.25)', transform: `translateY(${(1 - sheet) * 700}px)`, direction: 'rtl', fontFamily, padding: '28px 40px'}}>
            <div style={{width: 90, height: 8, borderRadius: 8, background: '#ddd', margin: '0 auto 20px'}} />
            <div style={{display: 'flex', gap: 24, alignItems: 'center'}}>
              <Img src={staticFile('products/p3_cut.png')} style={{height: 210}} />
              <div><div style={{fontSize: 46, fontWeight: 900, color: '#111'}}>מטען ביתי 20W</div>
                <div style={{fontSize: 32, fontWeight: 700, color: '#555', marginTop: 4}}>BASELINE</div></div>
            </div>
            <div style={{display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 34, marginTop: 26}}>
              {['+', String(qty), '−'].map((t, i) => (
                <div key={i} style={{width: i === 1 ? 170 : 100, height: 100, borderRadius: 999, display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: i === 1 ? 70 : 58, fontWeight: 900, color: i === 1 ? '#111' : '#fff', background: i === 1 ? '#f1f1f1' : '#111',
                  transform: i === 0 && holding ? 'scale(0.9)' : 'none', boxShadow: i === 0 && holding ? '0 0 0 12px rgba(132,204,45,0.4)' : 'none'}}>{t}</div>
              ))}
            </div>
            <div style={{position: 'relative', marginTop: 34, height: 116, borderRadius: 999, background: C.lime, color: '#0d110e', display: 'flex',
              alignItems: 'center', justifyContent: 'center', fontSize: 50, fontWeight: 900, transform: f >= tapAt && f < tapAt + 5 ? 'scale(0.95)' : 'none'}}>
              שליחת הזמנה
              {f >= tapAt && f < tapAt + 14 && (
                <div style={{position: 'absolute', left: 24, top: 18, width: 80, height: 80, borderRadius: 999, border: '6px solid rgba(255,255,255,0.95)',
                  transform: `scale(${interpolate(f, [tapAt, tapAt + 14], [0.4, 1.4])})`, opacity: interpolate(f, [tapAt, tapAt + 14], [1, 0])}} />
              )}
            </div>
          </div>
          <div style={{position: 'absolute', left: 0, right: 0, bottom: 0, height: 620, background: C.lime, borderRadius: '44px 44px 0 0',
            clipPath: `circle(${interpolate(f, [b(8), b(8) + 9], [0, 140], {...clamp, easing: EASE_OUT})}% at 12% 86%)`,
            display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', direction: 'rtl', fontFamily}}>
            <div style={{width: 170, height: 170, borderRadius: 999, background: '#0d110e', display: 'flex', alignItems: 'center', justifyContent: 'center', transform: `scale(${done})`}}>
              <svg width="96" height="96" viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke={C.lime} strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round"
                strokeDasharray="30" strokeDashoffset={30 - 30 * Math.min(1, done * 1.2)} /></svg></div>
            <div style={{fontSize: 60, fontWeight: 900, color: '#0d110e', marginTop: 30}}>ההזמנה התקבלה</div>
            <div style={{fontSize: 40, fontWeight: 700, color: '#0d110e', marginTop: 10}}>20 × מטען ביתי 20W</div>
          </div>
        </Phone>
      </div>
      <AbsoluteFill style={{pointerEvents: 'none', opacity: push * (1 - exit),
        background: `linear-gradient(180deg, ${C.bg} 0px, ${C.bg} 560px, rgba(13,17,14,0) 640px)`}} />
      <Headline words={[{t: 'מזמינים'}, {t: 'מאלדין.', accent: true}]} at={6} until={b(4.4)} size={130} />
      <Headline words={[{t: '20'}, {t: 'יחידות.', accent: true}]} at={b(6.5)} until={b(8)} size={130} />
      <Headline words={[{t: 'נשלח.'}]} at={b(8)} until={b(9.7)} size={150} />
    </AbsoluteFill>
  );
};

// 4. on the way: tracker reaches "arrived"
const S3: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const steps = ['הוזמן', 'נארז', 'בדרך', 'הגיע'];
  const inS = spring({frame: f, fps, config: {damping: 18, stiffness: 140}});
  const push = interpolate(f, [0, b(6.5)], [1, 1.06], clamp);
  const fill = interpolate(f, [b(1), b(4)], [0, 1], {...clamp, easing: EASE_IN_OUT});
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{background: C.bg}} />
      <AbsoluteFill style={{background: 'radial-gradient(ellipse at 50% 55%, rgba(132,204,45,0.16), rgba(0,0,0,0) 62%)'}} />
      <div style={{position: 'absolute', left: 60, right: 60, top: 640, height: 440, borderRadius: 48, background: 'rgba(255,255,255,0.07)',
        border: '2px solid rgba(255,255,255,0.12)', direction: 'rtl', fontFamily, transform: `translateY(${(1 - inS) * 900}px) scale(${push})`,
        display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
        <div style={{position: 'relative', width: 820, display: 'flex', justifyContent: 'space-between'}}>
          <div style={{position: 'absolute', left: 60, right: 60, top: 54, height: 10, background: 'rgba(255,255,255,0.15)', borderRadius: 10}} />
          <div style={{position: 'absolute', right: 60, top: 54, height: 10, background: C.lime, borderRadius: 10, width: 700 * fill}} />
          {steps.map((s, i) => {
            const t = b(1 + i);
            const on = f >= t;
            const pop = spring({frame: f - t, fps, config: {damping: 9, stiffness: 220}});
            return (
              <div key={s} style={{display: 'flex', flexDirection: 'column', alignItems: 'center', zIndex: 2, width: 140}}>
                <div style={{width: 118, height: 118, borderRadius: 999, background: on ? C.lime : '#2a312b', transform: `scale(${on ? 0.75 + 0.25 * pop : 0.75})`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: on ? '0 0 40px rgba(132,204,45,0.5)' : 'none'}}>
                  {on && <svg width="62" height="62" viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="#0d110e" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" /></svg>}
                </div>
                <div style={{marginTop: 30, fontSize: 60, fontWeight: 900, color: on ? C.white : '#6c766d'}}>{s}</div>
              </div>
            );
          })}
        </div>
      </div>
      <Headline words={[{t: 'בדרך'}, {t: 'אליך.'}]} at={b(0.4)} until={b(4.2)} size={140} />
      <Headline words={[{t: 'הגיע'}, {t: 'לחנות.', accent: true}]} at={b(4.2)} size={140} />
    </AbsoluteFill>
  );
};

// 5. payoff: the wall fills, landing on the beat
const S4: React.FC = () => {
  const f = useCurrentFrame();
  const pull = interpolate(f, [0, b(8)], [1.18, 1.0], {...clamp, easing: EASE_OUT});
  const flash = interpolate(f, [0, 5], [0.5, 0], clamp);
  const L: [number, number, number, number][] = [ // x, y, h, product - irregular, inside side margins
    [210, 620, 300, 0], [450, 590, 330, 2], [700, 630, 290, 4], [900, 600, 300, 1],
    [170, 990, 320, 5], [410, 960, 300, 3], [640, 1000, 340, 0], [880, 970, 300, 2],
    [260, 1360, 300, 4], [520, 1340, 320, 1], [780, 1370, 300, 5],
  ];
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{transform: `scale(${pull})`, transformOrigin: '50% 50%'}}>
        <Slatwall />
        {L.map(([x, y, h, p], i) => (
          <React.Fragment key={i}>
            <Hook x={x} y={y + 6} />
            <Pack src={PRODUCTS[p]} x={x} y={y} h={h} seed={i * 1.3} enter={Math.round(i * BEAT * 0.25)} from={i % 2 ? 'top' : 'bottom'} />
          </React.Fragment>
        ))}
      </AbsoluteFill>
      <AbsoluteFill style={{background: C.lime, opacity: flash, mixBlendMode: 'screen'}} />
      <AbsoluteFill style={{background: 'linear-gradient(180deg, rgba(13,17,14,0.95) 0%, rgba(13,17,14,0) 30%)'}} />
      <Headline words={[{t: 'המדף'}, {t: 'מלא.', accent: true}]} at={b(3)} size={170} />
    </AbsoluteFill>
  );
};

// 6. end card
const S5: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const logo = spring({frame: f, fps, config: {damping: 14, stiffness: 150}});
  const cta = spring({frame: f - 8, fps, config: {damping: 11, stiffness: 170}});
  return (
    <AbsoluteFill style={{background: C.bg}}>
      <AbsoluteFill style={{transform: `scale(${interpolate(f, [0, b(4.5)], [1.05, 1.12])})`, filter: 'blur(16px) brightness(0.4)'}}>
        <Slatwall />
        {[[300, 700], [560, 650], [800, 720], [420, 1100], [680, 1080]].map(([x, y], i) => <Pack key={i} src={PRODUCTS[i]} x={x} y={y} h={320} seed={i} />)}
      </AbsoluteFill>
      <AbsoluteFill style={{background: 'radial-gradient(ellipse at 50% 48%, rgba(132,204,45,0.22), rgba(0,0,0,0) 55%)'}} />
      <Img src={staticFile('logo_dark.png')} style={{position: 'absolute', left: 150, top: 560, width: 780, transform: `scale(${0.8 + 0.2 * logo})`, opacity: logo}} />
      <div style={{position: 'absolute', left: 60, right: 60, top: 740, textAlign: 'center', direction: 'rtl', fontFamily, fontWeight: 900, fontSize: 112,
        lineHeight: 1.08, color: C.white, opacity: interpolate(f, [3, 9], [0, 1], clamp)}}>
        מזמינים מהאתר.<br /><span style={{color: C.lime}}>מקבלים עד החנות.</span>
      </div>
      <div style={{position: 'absolute', left: 170, right: 170, top: 1010, height: 140, borderRadius: 999, background: C.lime, display: 'flex', alignItems: 'center',
        justifyContent: 'center', fontFamily, fontWeight: 900, fontSize: 64, color: '#0d110e', direction: 'rtl', transform: `scale(${cta * (1 + 0.02 * Math.sin(f / 4))})`,
        boxShadow: `0 0 ${40 + 20 * Math.sin(f / 5)}px rgba(132,204,45,0.55)`}}>הזמינו עכשיו</div>
      <div style={{position: 'absolute', left: 0, right: 0, top: 1175, textAlign: 'center', fontFamily, fontWeight: 700, fontSize: 60, color: C.white,
        opacity: interpolate(f, [12, 18], [0, 1], clamp)}}>aladincorp.com</div>
    </AbsoluteFill>
  );
};

const Sfx: React.FC<{at: number; src: string; v?: number}> = ({at, src, v = 0.6}) => (
  <Sequence from={at} durationInFrames={90}><Audio src={staticFile('sfx/' + src)} volume={v} /></Sequence>
);

const T = {s2: 4.5, s3: 14.5, s4: 21, s5: 29}; // scene starts, in beats

export const Ad: React.FC = () => (
  <AbsoluteFill style={{background: C.bg}}>
    <Sequence from={0} durationInFrames={b(T.s2)}><S1 /></Sequence>
    <Sequence from={b(T.s2)} durationInFrames={b(T.s3 - T.s2)}><S2 /></Sequence>
    <Sequence from={b(T.s3)} durationInFrames={b(T.s4 - T.s3)}><S3 /></Sequence>
    <Sequence from={b(T.s4)} durationInFrames={b(T.s5 - T.s4)}><S4 /></Sequence>
    <Sequence from={b(T.s5)} durationInFrames={b(TOTAL_BEATS - T.s5)}><S5 /></Sequence>
    <Vignette />
    <Grain />
    <Audio src={staticFile('music.wav')} volume={(f) =>
      interpolate(f, [b(T.s4 - 0.6), b(T.s4 - 0.5), b(T.s4) - 1, b(T.s4)], [1, 0.12, 0.12, 1], clamp) *
      interpolate(f, [b(TOTAL_BEATS) - 10, b(TOTAL_BEATS)], [1, 0], clamp)} />
    <Sfx at={2} src="pop_hard.mp3" v={0.55} />
    <Sfx at={b(1)} src="whoosh_fast.mp3" v={0.55} />
    <Sfx at={b(2.5)} src="pop_hard.mp3" v={0.45} />
    <Sfx at={b(T.s2) - 4} src="swoosh_trans.mp3" v={0.6} />
    <Sfx at={b(T.s2 + 3.3)} src="sweep_small.mp3" v={0.45} />
    {Array.from({length: 10}, (_, i) => <Sfx key={'q' + i} at={b(T.s2 + 4.5) + Math.round(i * (b(2) / 10))} src="ui_click.mp3" v={0.25 + i * 0.04} />)}
    <Sfx at={b(T.s2 + 6.5)} src="tech_select.mp3" v={0.6} />
    <Sfx at={b(T.s2 + 7.5)} src="select_click.mp3" v={0.7} />
    <Sfx at={b(T.s2 + 8)} src="notify.mp3" v={0.65} />
    <Sfx at={b(T.s3) - 4} src="whoosh_fast.mp3" v={0.55} />
    {[1, 2, 3, 4].map((x) => <Sfx key={'t' + x} at={b(T.s3 + x)} src="tech_select.mp3" v={0.55} />)}
    <Sfx at={b(T.s3 + 4.2)} src="pop_hard.mp3" v={0.5} />
    <Sfx at={b(T.s4) - 2} src="impact.mp3" v={0.6} />
    {Array.from({length: 11}, (_, i) => <Sfx key={'p' + i} at={b(T.s4) + Math.round(i * BEAT * 0.25) + 6} src="ui_click.mp3" v={0.3} />)}
    <Sfx at={b(T.s5) - 3} src="whoosh_fast.mp3" v={0.5} />
    <Sfx at={b(T.s5) + 8} src="select_click.mp3" v={0.5} />
  </AbsoluteFill>
);
