// One request from Qt, through a real MCP initialize/tools/call exchange.
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
let input='';for await(const chunk of process.stdin){input+=chunk;if(input.length>20000)process.exit(2);}
const transport=new StdioClientTransport({command:process.execPath,args:[new URL('./leaders.mjs',import.meta.url).pathname],env:Object.fromEntries(Object.entries(process.env).filter(([,v])=>v!==undefined)),stderr:'ignore'});
const client=new Client({name:'qwen-studio',version:'1.0.0'});
const stop=async()=>{await client.close().catch(()=>{});process.exit(0);};
process.on('SIGTERM',stop);process.on('SIGINT',stop);
try{
  const request=JSON.parse(input);
  if(!['ask_leader','leader_status','leader_login'].includes(request.name))throw Error();
  await client.connect(transport);
  const discovered=await client.listTools();
  if(!discovered.tools.some(t=>t.name===request.name))throw Error();
  const response=await client.callTool(request,undefined,{timeout:490000});
  process.stdout.write(JSON.stringify(response));
}catch{process.stdout.write(JSON.stringify({isError:true,content:[{type:'text',text:'{"error":"Leader MCP connection failed."}'}]}));}
finally{await client.close();}
