// Shared descriptor-confined Python engine. Remote overwrites fail closed:
// an expected hash is not a substitute for local approval.
import {spawn} from 'node:child_process';
import {z} from 'zod';
const engine=new URL('../workspace_tools.py',import.meta.url).pathname;
function call(name,args){
  return new Promise(resolve=>{
    const p=spawn('/usr/bin/python3',[engine],{stdio:['pipe','pipe','ignore']});
    let data='';let done=false;
    const finish=value=>{if(done)return;done=true;clearTimeout(timer);resolve({content:[{type:'text',text:JSON.stringify(value)}],...(value.error?{isError:true}:{})});};
    const timer=setTimeout(()=>{p.kill();finish({error:'File tool timed out.'});},15000);
    p.stdout.on('data',chunk=>{data+=chunk;if(data.length>300000){p.kill();finish({error:'Result limit exceeded.'});}});
    p.on('error',()=>finish({error:'File service unavailable.'}));
    p.on('close',()=>{try{finish(JSON.parse(data));}catch{finish({error:'File service failed.'});}});
    const {workspace,...arguments_}=args;
    p.stdin.on('error',()=>{});
    p.stdin.end(JSON.stringify({workspace,name,arguments:arguments_}));
  });
}
export function registerProjectTools(server){
  const workspace=z.enum(['qwen-studio','example']).default('qwen-studio');
  const register=(name,description,inputSchema,readOnly=true)=>server.registerTool(name,{description,inputSchema:{workspace,...inputSchema},annotations:{readOnlyHint:readOnly,destructiveHint:!readOnly}},args=>call(name,args));
  register('list_project_files','List safe files in a selected workspace.',{directory:z.string().default('.')});
  register('read_project_file','Read a 6000-character safe UTF-8 chunk and full-file SHA-256. Use next_offset to continue.',{file:z.string(),offset:z.number().int().min(0).optional()});
  register('search_project_files','Search safe workspace files.',{directory:z.string().default('.'),term:z.string()});
  register('make_project_directory','Create one directory.',{directory:z.string()},false);
  register('create_project_file','Create a new file; never overwrite.',{file:z.string(),content:z.string().max(200000)},false);
  server.registerTool('write_project_file',{description:'Create a file. Existing file replacements require approval in Qwen Studio Chat and are refused remotely.',inputSchema:{workspace,file:z.string(),content:z.string().max(200000),expected_sha256:z.string().optional()},annotations:{readOnlyHint:false,destructiveHint:true}},({expected_sha256,...args})=>call(expected_sha256?'edit_project_file':'create_project_file',expected_sha256?{...args,expected_sha256}:args));
}
