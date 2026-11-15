export function polling(fn){let stopped=false;const timer=setInterval(()=>{if(!stopped)fn().catch(console.error);},2000);return()=>{stopped=true;clearInterval(timer);};}
