const fs=require('fs');
const parser=require('@babel/parser');
const html=fs.readFileSync('index.html','utf8');
const re=/<script\s+type="text\/babel"[^>]*>([\s\S]*?)<\/script>/g;
let m,i=0,bad=0;
while((m=re.exec(html))){
  i++;
  try{ parser.parse(m[1],{sourceType:'module',plugins:['jsx']});
    console.log('script #'+i+' ('+m[1].length+' chars): PARSE OK'); }
  catch(e){ bad++; console.log('script #'+i+': PARSE ERROR -> '+String(e.message).split('\n')[0]); }
}
console.log(bad?('FAIL: '+bad):'ALL OK');
