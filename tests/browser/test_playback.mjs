import assert from 'node:assert/strict';
import {FrameClock} from '../../src/retargetlab/replay/playback.js';
const frames=Array.from({length:120},(_,i)=>({timestamp_s:i/30}));
const clock=new FrameClock();clock.reset(0);
let i=0,seen=[0];
for(let t=1000/60;t<2000;t+=1000/60){const next=clock.next(t,frames,i,1);if(next!==i)seen.push(next);i=next;}
assert.ok(i>=58&&i<=60, `1x advances about 60 frames in 2s, got ${i}`);
const afterStall=clock.next(5000,frames,i,1);assert.equal(afterStall,i+1);
for(let t=5017;t<15000;t+=17){const next=clock.next(t,frames,i,1);assert.ok(next===i||next===i+1);i=next;}
assert.equal(i,119);assert.equal(clock.next(999999,frames,i,2),119);
const irregular=[0,.02,.1,.105,.5].map(timestamp_s=>({timestamp_s}));
clock.reset(0);i=0;for(const t of [10,20,100,105,500])i=clock.next(t,irregular,i,1);assert.equal(i,4);
clock.reset(0);i=0;for(let t=1000/60;t<=1000;t+=1000/60)i=clock.next(t,frames,i,2);assert.ok(i>=58&&i<=60);
clock.reset(0);i=0;for(let t=1000/60;t<=1000;t+=1000/60)i=clock.next(t,frames,i,.25);assert.ok(i>=7&&i<=8);
console.log('PASS: 1x/2x/0.25x, irregular timestamps, long stalls, contiguous indices, end clamp');
