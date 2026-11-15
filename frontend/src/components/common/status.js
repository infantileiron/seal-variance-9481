import{STATUS}from'../../constants/enums.js';export const badge=a=>`<span class=badge data-state=${a.approved?'approved':a.status}>${a.approved?'已签核':STATUS[a.status]||a.status}</span>`;
