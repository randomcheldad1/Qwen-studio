// Private MCP bridge to already-signed-in desktop chats, with local Qwen vision.
import {McpServer} from '@modelcontextprotocol/sdk/server/mcp.js';
import {StdioServerTransport} from '@modelcontextprotocol/sdk/server/stdio.js';
import {z} from 'zod';
import {spawn} from 'node:child_process';
const server=new McpServer({name:'qwen-desktop-leaders',version:'3.0.0'});
const provider=z.enum(['chatgpt','claude']);const children=new Set();
function invoke(name,args){return new Promise(resolve=>{
 const p=spawn('/usr/bin/python3',[new URL('../desktop_leaders.py',import.meta.url).pathname],{stdio:['pipe','pipe','ignore'],detached:true});children.add(p);let output='';let done=false;
 const kill=()=>{try{process.kill(-p.pid,'SIGTERM');}catch{}};
 const finish=value=>{if(done)return;done=true;clearTimeout(timer);children.delete(p);resolve({content:[{type:'text',text:JSON.stringify(value)}],...(value.error?{isError:true}:{})});};
 const timer=setTimeout(()=>{kill();finish({error:'Desktop consultation timed out.'});},480000);
 p.stdout.on('data',c=>{output+=c;if(output.length>100000){kill();finish({error:'Desktop output exceeded its limit.'});}});
 p.on('error',()=>finish({error:'Desktop bridge could not start.'}));p.on('close',()=>{try{finish(JSON.parse(output));}catch{finish({error:'Desktop bridge stopped without a confirmed result.'});}});
 p.stdin.on('error',()=>{});p.stdin.end(JSON.stringify({name,arguments:args}));
});}
for(const [name,description,extra] of [
 ['leader_status','Check whether the existing desktop app is open.',{}],
 ['leader_login','Focus the existing desktop app. User handles any sign-in there.',{}],
 ['ask_leader','Start a fresh desktop chat, send the question, and return only its completed task-matched reply. Uses local Qwen vision for controls when accessibility is unavailable.',{question:z.string().min(1).max(12000)}]
])server.registerTool(name,{description,inputSchema:{provider,...extra}},args=>invoke(name,args));
function stop(){for(const p of children){try{process.kill(-p.pid,'SIGTERM');}catch{}}process.exit(0);}
process.on('SIGTERM',stop);process.on('SIGINT',stop);process.stdin.on('end',stop);
await server.connect(new StdioServerTransport());
