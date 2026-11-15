export const values=f=>Object.fromEntries(new FormData(f));export function busy(f,on){for(const b of f.querySelectorAll('button'))b.disabled=on;}
