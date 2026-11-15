import{request,post}from'./client.js';export const list=()=>request('/calibration');export const preview=()=>request('/calibration/preview');export const createRule=data=>post('/calibration',data);
