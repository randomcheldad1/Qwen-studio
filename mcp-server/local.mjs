// Private local stdio MCP for OpenCode; does not change the public OAuth bridge.
import {McpServer} from '@modelcontextprotocol/sdk/server/mcp.js';
import {StdioServerTransport} from '@modelcontextprotocol/sdk/server/stdio.js';
import {z} from 'zod';
import {registerProjectTools} from './project-tools.mjs';
const server=new McpServer({name:'qwen-studio-local',version:'1.0.0'});
registerProjectTools(server);
const result=value=>({content:[{type:'text',text:JSON.stringify(value)}]});
server.registerTool('list_qwen_models',{description:'List installed local Qwen models.',inputSchema:{}},async()=>{
 try{
  const r=await fetch('http://127.0.0.1:11434/api/tags',{signal:AbortSignal.timeout(5000)});if(!r.ok)throw Error();
  const data=await r.json();return result({models:data.models.map(m=>m.name).filter(n=>n.toLowerCase().startsWith('qwen'))});
 }catch{return {...result({error:'Local Ollama is unavailable.'}),isError:true};}
});
await server.connect(new StdioServerTransport());
process.stdin.on('end',()=>process.exit(0));
