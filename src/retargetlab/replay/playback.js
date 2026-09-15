// Each animation callback can present at most one saved frame. A long stall
// slows playback rather than discarding source frames to chase wall time.
export class FrameClock {
  reset(now) { this.last=now;this.elapsed=0; }
  next(now, frames, index, speed) {
    if(this.last===undefined)this.reset(now);
    const dt=Math.max(0,now-this.last);this.last=now;
    if(index>=frames.length-1)return index;
    const interval=Math.max(0,(frames[index+1].timestamp_s-frames[index].timestamp_s)*1000/speed);
    this.elapsed+=Math.min(dt,interval||16.667);
    if(this.elapsed+1e-6<interval)return index;
    this.elapsed=Math.max(0,this.elapsed-interval);
    return index+1;
  }
}
