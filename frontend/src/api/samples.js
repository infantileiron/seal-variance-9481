import{request,post}from'./client.js';export const list=()=>request('/samples');export const save=(data,id)=>id?request('/samples/'+id,{method:'PUT',body:JSON.stringify(data)}):post('/samples',data);
