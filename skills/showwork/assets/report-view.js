// Shared Showwork report renderer. Builds the report DOM inside `root`; used by the browser page and the desktop app.
// hooks: { submitChoice(choiceId) -> Promise<void>, assetUrl(relativePath) -> string, connected() -> boolean, idPrefix?: string,
//          unavailableText?: string (shown on a decision while connected() is false) }
    function text(tag, content, className) { const e = document.createElement(tag); e.textContent = content; if(className) e.className=className; return e; }
    // Files worth reviewing: accordions with a read-only, editor-style code view (no outside scripts).
    const FAMILY={js:'js',jsx:'js',ts:'js',tsx:'js',mjs:'js',cjs:'js',javascript:'js',typescript:'js',json:'json',py:'py',python:'py',rb:'py',ruby:'py',sh:'sh',zsh:'sh',bash:'sh',shell:'sh',toml:'sh',ini:'sh',yml:'yaml',yaml:'yaml',swift:'c',kt:'c',kts:'c',kotlin:'c',java:'c',go:'c',rs:'c',rust:'c',c:'c',h:'c',m:'c',mm:'c',cpp:'c',cs:'c',dart:'c',gradle:'c',php:'php',sql:'sql',css:'css',scss:'css',html:'html',htm:'html',xml:'html',vue:'html',svg:'html',plist:'html'};
    const RX={slash:String.raw`\/\/[^\n]*`,block:String.raw`\/\*[\s\S]*?(?:\*\/|$)`,hash:String.raw`#[^\n]*`,dash:String.raw`--[^\n]*`,markup:String.raw`<!--[\s\S]*?(?:-->|$)`,
      triple:String.raw`"""[\s\S]*?(?:"""|$)|'''[\s\S]*?(?:'''|$)`,dq:'"',sq:"'",bt:'\x60',
      num:String.raw`\b(?:0x[\da-fA-F]+|\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?)\b`,word:String.raw`[@$]?[A-Za-z_][\w$]*`,tag:String.raw`<\/?[A-Za-z][\w:.-]*|\/?>`};
    const RECIPES={js:'com:slash com:block str:bt str:dq str:sq num word',c:'com:slash com:block str:triple str:dq str:sq num word',py:'str:triple com:hash str:dq str:sq num word',sh:'com:hash str:dq str:sq num word',yaml:'com:hash str:dq str:sq num word',
      json:'str:dq num word',php:'com:slash com:block com:hash str:dq str:sq num word',sql:'com:dash com:block str:sq str:dq num word',css:'com:block str:dq str:sq num word',html:'com:markup str:dq str:sq tag:tag'};
    // Quoted strings are matched by hand from their opening quote (see quoted()), so an unclosed quote costs linear time.
    const QUOTE={dq:{body:/"(?:\\.|[^"\\\n])*/y,close:'"'},sq:{body:/'(?:\\.|[^'\\\n])*/y,close:"'"},bt:{body:/\x60(?:\\[\s\S]|[^\x60\\])*/y,close:'\x60'}};
    const COMPILED={};
    const MAX_FRAME=12000; // handoff visuals taller than this scroll inside their frame
    const PROBE=[100,200]; // viewport heights for measuring visuals; below the 260px frame minimum, so padding can always reach them
    for(const [name,recipe] of Object.entries(RECIPES)){const parts=recipe.split(' ').map(part=>{const [cls,key]=part.includes(':')?part.split(':'):[part,part];return [cls,key];});COMPILED[name]={classes:parts.map(([cls])=>cls),keys:parts.map(([,key])=>key),re:new RegExp(parts.map(([,key])=>'('+RX[key]+')').join('|'),'g')};}
    const words=list=>new Set(list.split(' '));
    const KEYWORDS={js:words('as async await break case catch class const continue debugger default delete do else enum export extends finally for from function get if implements import in instanceof interface let new of private protected public readonly return satisfies set static super switch throw try type typeof var void while with yield declare namespace abstract keyof'),
      c:words('abstract actor as associatedtype async await break case catch class const continue default defer deinit do else enum extends extension fallthrough final finally fn for func fun go guard if impl implements import in init inout interface internal is lazy let loop match mod mut namespace new object open operator override package private protocol protected pub public repeat return some static struct super switch throw throws trait try typealias type use val var void when where while weak unowned yield chan select range'),
      php:words('abstract as break case catch class const continue declare default do echo else elseif enum extends final finally fn for foreach function global if implements include interface match namespace new private protected public readonly require require_once return static switch throw trait try use while yield'),
      py:words('and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield match case'),
      sh:words('if then else elif fi for while until do done case esac in function return local export readonly set unset source exit echo cd exec'),
      sql:words('select from where insert into values update set delete create table alter add drop index on join left right inner outer full cross group by order limit offset as and or not null is in primary key foreign references unique default constraint column if exists begin commit rollback returning distinct having union all case when then else end view trigger cascade varchar text integer bigint boolean timestamp')};
    const LITERALS=words('true false null undefined None nil True False NaN this self Self');
    function familyOf(file){const ext=(file.language||file.path.split('/').pop().split('.').pop()||'').toLowerCase();return FAMILY[ext]||'text';}
    function wordClass(word,code,end,family){
      if(/^[@$]/.test(word)) return 'lit';
      if(LITERALS.has(word)) return 'lit';
      if(KEYWORDS[family]?.has(family==='sql'?word.toLowerCase():word)) return 'kw';
      const rest=code.slice(end,end+40);
      if((family==='yaml'||family==='css')&&/^[ \t]*:/.test(rest)) return 'key';
      if(/^ ?\(/.test(rest)) return 'fn';
      if(/^[A-Z]/.test(word)&&family!=='sql') return 'ty';
      return '';
    }
    // A string runs from its quote to the matching unescaped quote on the same line (backticks may span lines).
    // When it is unclosed, every later quote of that kind up to where the scan stopped is unclosed too, so those are skipped.
    function quoted(code,at,kind,unclosed){
      if(at<unclosed[kind]) return 0;
      const q=QUOTE[kind];q.body.lastIndex=at;const end=q.body.exec(code)[0].length+at;
      if(code[end]===q.close) return end+1;
      unclosed[kind]=end;return 0;
    }
    function tokens(code,family){
      const spec=COMPILED[family]; if(!spec) return [['',code]];
      const out=[],re=spec.re,unclosed={dq:0,sq:0,bt:0}; let last=0,match; re.lastIndex=0;
      while((match=re.exec(code))){
        if(!match[0].length){re.lastIndex++;continue;}
        const group=match.slice(1).findIndex(value=>value!==undefined),key=spec.keys[group];
        if(QUOTE[key]){const end=quoted(code,match.index,key,unclosed);if(!end)continue;match[0]=code.slice(match.index,end);re.lastIndex=end;}
        if(match.index>last) out.push(['',code.slice(last,match.index)]);
        let cls=spec.classes[group];
        if(cls==='word') cls=wordClass(match[0],code,re.lastIndex,family);
        else if(cls==='str'&&(family==='json'||family==='yaml')&&/^[ \t]*:/.test(code.slice(re.lastIndex,re.lastIndex+20))) cls='key';
        out.push([cls,match[0]]); last=re.lastIndex;
      }
      if(last<code.length) out.push(['',code.slice(last)]);
      return out;
    }
    function codeRows(file){
      const family=familyOf(file),raw=file.code.replace(/\r\n?/g,'\n').replace(/\n$/,''),rows=[];
      if(!file.diff){
        let parts=[];rows.push({kind:'',parts});
        for(const [cls,value] of tokens(raw,family)) value.split('\n').forEach((piece,i)=>{if(i){parts=[];rows.push({kind:'',parts});}if(piece)parts.push([cls,piece]);});
        const first=file.start_line||1,width=String(first+rows.length-1).length;
        rows.forEach((row,i)=>row.no=String(first+i).padStart(width));
        return rows;
      }
      let before=file.start_line||1,after=before,inHunk=false;
      const lines=raw.split('\n');
      lines.forEach((line,i)=>{
        const hunk=/^@@ -(\d+)(?:,\d+)? \+(\d+)/.exec(line);
        if(hunk){before=+hunk[1];after=+hunk[2];inHunk=true;rows.push({kind:'hunk',parts:[['',line]]});return;}
        // A file header starts a new file: `diff --git` always, the other header lines outside a hunk, and a
        // `---`/`+++` pair directly before `@@` even inside one (diffs joined without `diff --git`).
        const fileStart=line.startsWith('--- ')&&lines[i+1]?.startsWith('+++ ')&&lines[i+2]?.startsWith('@@ ')||line.startsWith('+++ ')&&lines[i-1]?.startsWith('--- ')&&lines[i+1]?.startsWith('@@ ');
        if(line.startsWith('diff --git ')||fileStart) inHunk=false;
        if(!inHunk&&/^(diff --git|index |--- |\+\+\+ |new file|deleted file|old mode|new mode|similarity|rename |Binary files)/.test(line)||line.startsWith('\\')){rows.push({kind:'meta',parts:[['',line]]});return;}
        const mark=line[0]==='+'||line[0]==='-'?line[0]:' ',body=line[0]===mark?line.slice(1):line;
        rows.push({kind:mark==='+'?'add':mark==='-'?'del':'',mark,parts:tokens(body,family),old:mark==='+'?'':before++,new:mark==='-'?'':after++});
      });
      let width=1;// a loop, not Math.max(...rows): a long diff has too many rows for function arguments
      for(const row of rows) if(row.mark!==undefined) width=Math.max(width,String(row.old).length,String(row.new).length);
      rows.forEach(row=>row.no=row.mark===undefined?' '.repeat(width*2+1):String(row.old).padStart(width)+' '+String(row.new).padStart(width));
      return rows;
    }
    function editor(file){
      const box=document.createElement('div');box.className='editor';
      const bar=document.createElement('div');bar.className='editor-bar';
      const dots=text('span','','dots');dots.setAttribute('aria-hidden','true');dots.append(document.createElement('i'),document.createElement('i'),document.createElement('i'));
      const label=(file.diff?'Diff · ':'')+(file.language||file.path.split('/').pop().split('.').pop());
      const copy=text('button','Copy','copy');copy.type='button';copy.setAttribute('aria-label','Copy code from '+file.path);
      copy.onclick=async()=>{try{await navigator.clipboard.writeText(file.code);copy.textContent='Copied';}catch{copy.textContent='Copy failed';}setTimeout(()=>copy.textContent='Copy',1600);};
      bar.append(dots,text('span',file.path,'name'),text('span',label,'lang'),copy);
      const view=document.createElement('div');view.className='code';view.tabIndex=0;view.setAttribute('role','region');view.setAttribute('aria-label','Code: '+file.path);
      const fragment=document.createDocumentFragment();
      for(const row of codeRows(file)){
        const line=document.createElement('div');line.className=('line '+row.kind).trim();line.append(text('span',row.no,'no'));
        const source=document.createElement('span');source.className='src';
        if(row.mark!==undefined) source.append(text('span',row.mark,'mark'));
        for(const [cls,value] of row.parts) source.append(cls?text('span',value,'tk-'+cls):document.createTextNode(value));
        line.append(source);fragment.append(line);
      }
      view.append(fragment);box.append(bar,view);return box;
    }
export function renderReport(root, page, hooks) {
  const p = hooks.idPrefix || '';
  const $ = id => root.querySelector('[id="' + p + id + '"]');
  let selected = null, saved = null, sending = false, observers = [], destroyed = false, unavailable = false, lightbox = null;
  const unavailableText = hooks.unavailableText || 'Disconnected. Your choice cannot be saved right now.';
  root.innerHTML = `
      <div id="${p}mode" class="eyebrow"></div><h1 id="${p}title"></h1><p class="r-summary" id="${p}summary"></p>
      <section class="r-decision" id="${p}decision" hidden aria-labelledby="${p}question">
        <h2 class="r-question" id="${p}question"></h2><div id="${p}options" class="options" role="radiogroup" aria-labelledby="${p}question"></div>
        <div class="decision-actions"><button id="${p}submit" disabled>Choose this option</button><span class="r-selection-status" id="${p}selection-status" role="status">Choose an option, then press the button.</span></div>
      </section>
      <nav class="r-contents" id="${p}contents" aria-label="Report contents" hidden></nav><div id="${p}sections" class="section-grid"></div>
      <section class="r-files" id="${p}files" hidden aria-labelledby="${p}files-title"><div class="files-head"><h2 id="${p}files-title">Files worth reviewing</h2><button id="${p}toggle-files" class="linkish" type="button">Expand all</button></div><div id="${p}file-list" class="file-list"></div></section>
      <section class="r-verification" id="${p}verification" hidden><h2>Checks and open questions</h2><div id="${p}checks" class="checks"></div></section>
      <footer id="${p}footer"></footer>
`;
    // Full-window image viewer: fits the window first; clicking the image (or "Actual size") shows it pixel for pixel.
    function closeLightbox(){ if(!lightbox) return; const {overlay,opener}=lightbox; lightbox=null; overlay.remove(); document.removeEventListener('keydown',lightboxKeys,true); if(opener&&opener.isConnected) opener.focus(); }
    function lightboxKeys(e){ if(!lightbox) return; if(e.key==='Escape'){ e.preventDefault(); e.stopPropagation(); closeLightbox(); }
      else if(e.key==='Tab'){ const items=[...lightbox.overlay.querySelectorAll('button')],at=items.indexOf(document.activeElement); e.preventDefault(); items[(at+(e.shiftKey?-1:1)+items.length)%items.length].focus(); } }
    function openLightbox(src,title,opener){
      closeLightbox();
      const overlay=document.createElement('div');overlay.className='r-lightbox';overlay.setAttribute('role','dialog');overlay.setAttribute('aria-modal','true');overlay.setAttribute('aria-label',title);
      const bar=document.createElement('div');bar.className='r-lightbox-bar';
      const size=text('button','Actual size','r-lightbox-size');size.type='button';size.setAttribute('aria-pressed','false');
      const close=text('button','×','r-lightbox-close');close.type='button';close.setAttribute('aria-label','Close');
      bar.append(text('span',title,'r-lightbox-title'),size,close);
      const stage=document.createElement('div');stage.className='r-lightbox-stage';
      const img=document.createElement('img');img.src=src;img.alt=title;stage.append(img);
      const toggle=()=>{const actual=overlay.classList.toggle('actual');size.setAttribute('aria-pressed',String(actual));size.textContent=actual?'Fit to window':'Actual size';};
      img.onclick=e=>{e.stopPropagation();toggle();};size.onclick=toggle;close.onclick=closeLightbox;
      stage.onclick=e=>{if(e.target===stage)closeLightbox();};
      overlay.append(bar,stage);document.body.append(overlay);
      lightbox={overlay,opener};document.addEventListener('keydown',lightboxKeys,true);close.focus();
    }
    function zoomButton(src,title,cls,label){
      const button=document.createElement('button');button.type='button';button.className=cls;button.setAttribute('aria-label',label+': '+title);button.title=label;
      button.onclick=e=>{e.stopPropagation();openLightbox(src,title,button);};
      button.onkeydown=e=>{if(e.key===' '||e.key==='Enter')e.stopPropagation();};
      return button;
    }
    function visual(item, zoomable=false) {
      if(item.image) {
        const src=hooks.assetUrl(item.image);
        const img=document.createElement('img'); img.className='visual-image'; img.src=src; img.alt=item.title;
        if(zoomable){ const button=zoomButton(src,item.title,'r-zoom','Enlarge image');button.append(img,text('span','Click to enlarge','r-zoom-hint'));return button; }
        // An option image: the card chooses the option, so enlarging gets its own small button.
        const wrapper=document.createElement('div');wrapper.className='r-zoom-wrap';const corner=zoomButton(src,item.title,'r-zoom-corner','Enlarge image');corner.textContent='⤢';
        wrapper.append(img,corner);return wrapper;
      }
      const frame=document.createElement('iframe'); frame.title=item.title; frame.setAttribute('sandbox','allow-same-origin');
      frame.srcdoc='<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>body{margin:0;padding:24px;font:15px/1.5 system-ui;color:#172f34;box-sizing:border-box;overflow-wrap:anywhere}*{box-sizing:border-box}svg{max-width:100%;height:auto}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px;border-bottom:1px solid #d9e3e0;vertical-align:top}pre{white-space:pre-wrap}summary{cursor:pointer}</style>'+item.html;
      frame.onload=()=>{ try { const doc=frame.contentDocument,body=doc.body,top=doc.documentElement,cap=page.mode==='handoff'?MAX_FRAME:760;let applied=0;
        if(!body||!top) return; // navigated to a document without a body (an SVG or other XML file): keep the current size
        // The content height with the frame's inner viewport at `inner` px. Bottom padding shrinks the viewport while the
        // outer size stays, so the page around the frame does not move, and everything is restored before the next paint.
        const extent=inner=>{
          const style=frame.style,saved=[style.height,style.minHeight,style.paddingBottom,top.style.overflow],outer=frame.offsetHeight,room=frame.clientHeight;
          try {
            style.height=outer+'px';style.minHeight='0';style.paddingBottom=(room-inner)+'px';top.style.overflow='hidden';
            return Math.max(top.scrollHeight,body.getBoundingClientRect().bottom+top.scrollTop);
          } finally { [style.height,style.minHeight,style.paddingBottom,top.style.overflow]=saved; }
        };
        // Measure at two fixed viewport heights, never at the frame's own height, so the result depends on the content
        // alone and resizing cannot feed back into it. Real content measures the same both times. Content sized from the
        // viewport (vh, height:100%) grows by k px per px of viewport: it gets the height h where it fits, c+k*h <= h.
        // Content that follows the viewport fully (k near 1, such as min-height:100vh) never fits, so it gets the smaller
        // measurement. Either way the frame stays within [260, cap].
        // Transitions are off while measuring: a running transition reports its animated value, not the value at the
        // probe height, which made viewport-sized content look fixed and grow the frame without end. Layout is read once
        // more after the restore so the restore itself does not start a transition. Animations are left alone: no time passes
        // while measuring, so they already hold still, and pausing them here stops them from ever advancing in WebKit.
        const resize=()=>{
          if(frame.contentDocument!==doc||frame.clientHeight<=PROBE[1]) return; // navigated away, hidden or not laid out yet
          const still=doc.createElement('style');still.textContent='*,*::before,*::after{transition:none!important}';
          let need;
          try {
            (doc.head||top).append(still);
            const [a,b]=PROBE,fa=extent(a),k=Math.max(0,(extent(b)-fa)/(b-a));need=k<0.9?(fa-k*a)/(1-k):fa;
            void top.scrollHeight;
          } finally { still.remove(); }
          const height=Math.min(cap,Math.max(260,Math.ceil(need)+2));
          if(height===applied) return;
          applied=height;frame.style.height=height+'px';
        };
        resize();const observer=new ResizeObserver(resize);observer.observe(body);observers.push(observer); } catch{} }; return frame;
    }
    function syncToggle(){const items=[...root.querySelectorAll('.file')];$('toggle-files').textContent=items.length&&items.every(item=>item.open)?'Collapse all':'Expand all';}
    function renderFiles(){
      const files=page.mode==='handoff'?(page.files||[]):[];
      $('files').hidden=!files.length;$('file-list').replaceChildren();$('toggle-files').textContent='Expand all';
      files.forEach((file,index)=>{
        const item=document.createElement('details');item.className='file';item.id=p+'file-'+index;
        const summary=document.createElement('summary');const count=file.code.replace(/\n$/,'').split('\n').length;
        const chevron=text('span','▶','chev');chevron.setAttribute('aria-hidden','true');
        const where=file.diff?'Changes':file.start_line?'Lines '+file.start_line+'–'+(file.start_line+count-1):count+' lines';
        summary.append(chevron,text('span',file.path,'file-path'),text('span',where,'file-meta'),text('span',file.why,'file-why'));
        item.append(summary);
        item.addEventListener('toggle',()=>{if(item.open&&!item.querySelector('.editor'))item.append(editor(file));syncToggle();});
        $('file-list').append(item);
      });
      if(files.length){const link=text('a','Files worth reviewing');link.href='#'+p+'files';$('contents').append(link);}
    }
    $('toggle-files').onclick=()=>{const items=[...root.querySelectorAll('.file')];const open=!items.every(item=>item.open);items.forEach(item=>item.open=open);};
    // A closed decision (app) or a lost connection (browser) keeps the options visible but not choosable.
    function syncAvailable() {
      const off=!hooks.connected(); if(off===unavailable) return; unavailable=off;
      root.querySelectorAll('.option').forEach(e=>e.setAttribute('aria-disabled',String(off)));
      syncChoice();
    }
    // The button and status follow the selection. A saved choice stays saved (button off) until another option is picked,
    // also across a lost and restored connection, so the same choice is never sent twice. One choice is sent at a time:
    // picking another option while one is saving is allowed, and once that save lands the status names what was saved.
    function syncChoice() {
      const isSaved=selected!=null&&selected===saved,title=id=>page.options.find(item=>item.id===id)?.title??id;
      $('submit').disabled=unavailable||sending||selected==null||isSaved;
      $('selection-status').textContent=unavailable?unavailableText:sending?'Saving…':isSaved?'Choice saved. You can continue in chat.':
        saved!=null&&selected!=null?'Saved: '+title(saved)+'. Press the button to change it to '+title(selected)+'.':
        selected==null?'Choose an option, then press the button.':'Review your choice, then press the button.';
    }
    function choose(id) {
      if(!hooks.connected()) return;
      selected=id; root.querySelectorAll('.option').forEach(e=>e.setAttribute('aria-checked',String(e.dataset.choice===id)));
      syncChoice();
    }
    function render() {
      selected=null; unavailable=false;
      document.title=page.title+' · Showwork'; $('mode').textContent=page.mode==='decision'?'Choose together':'Review the result';
      $('title').textContent=page.title; $('summary').textContent=page.summary; $('decision').hidden=page.mode!=='decision';
      $('options').replaceChildren(); $('sections').replaceChildren(); $('checks').replaceChildren(); $('submit').disabled=true;
      $('contents').replaceChildren();$('contents').hidden=page.mode!=='handoff';$('sections').classList.toggle('handoff',page.mode==='handoff');
      $('selection-status').textContent='Choose an option, then press the button.';
      if(page.mode==='decision') {
        $('question').textContent=page.question;
        page.options.forEach((item,i)=>{
          const card=document.createElement('div'); card.className='card option'; card.tabIndex=0; card.setAttribute('role','radio'); card.setAttribute('aria-checked','false'); card.dataset.choice=item.id; card.setAttribute('aria-label',item.title);
          card.append(visual(item)); const copy=document.createElement('div');copy.className='card-copy';copy.append(text('div','Option '+(i+1),'tag'));
          const heading=text('h3','','option-label');heading.append(text('span','','radio'),text('span',item.title));copy.append(heading,text('p',item.body));card.append(copy);
          card.onclick=()=>choose(item.id);card.onkeydown=e=>{if(e.key===' '||e.key==='Enter'){e.preventDefault();choose(item.id);}else if(['ArrowRight','ArrowDown','ArrowLeft','ArrowUp'].includes(e.key)){e.preventDefault();const offset=['ArrowRight','ArrowDown'].includes(e.key)?1:-1;const target=(i+offset+page.options.length)%page.options.length;choose(page.options[target].id);$('options').children[target].focus();}};
          $('options').append(card);
        });
      }
      const kinds={proposal:'Proposal before implementation',observed:'Observed result',explanation:'Explanation'};
      (page.sections||[]).forEach((item,index)=>{ const card=document.createElement('section');card.className='card';card.id=p+'section-'+index;const copy=document.createElement('div');copy.className='card-copy';copy.append(text('div',kinds[item.kind],'tag'),text('h2',item.title),text('p',item.body));card.append(copy,visual(item,page.mode==='handoff'));$('sections').append(card);const link=text('a',item.title);link.href='#'+card.id;$('contents').append(link); });
      renderFiles();
      const labels={verified:'Verified',failed:'Failed',unverified:'Not checked'};
      $('verification').hidden=!(page.checks||[]).length;
      (page.checks||[]).forEach(item=>{const row=document.createElement('div');row.className='check';row.append(text('span',labels[item.status],'badge '+item.status));const detail=document.createElement('div');detail.append(text('strong',item.text),text('p',item.evidence,'evidence'));row.append(detail);$('checks').append(row);});
      $('footer').textContent=page.mode==='decision'?'Your choice applies only to this question. Share more feedback in chat.':'Observed results are separate from explanatory visuals. Check labels reflect the evidence provided by the author.';
      if(page.mode==='decision') syncAvailable();
    }
    $('submit').onclick=async()=>{
      // Once the view is replaced (destroyed, or its elements rebuilt), a late answer must not touch the next page.
      const choice=selected,button=$('submit');
      if(choice==null||choice===saved||sending||!hooks.connected()) return;
      sending=true; syncChoice();
      let failure=null;
      try { await hooks.submitChoice(choice); } catch(error){ failure=error instanceof Error?error.message:String(error); }
      if(destroyed||$('submit')!==button) return;
      sending=false; if(failure===null) saved=choice;
      syncChoice(); if(failure!==null&&!unavailable) $('selection-status').textContent=failure;
    };
  render();
  return {
    destroy() { destroyed = true; closeLightbox(); observers.forEach(observer => observer.disconnect()); observers = []; },
    // Call when connected() may have changed.
    refresh() { if (!destroyed && page.mode === 'decision') syncAvailable(); }
  };
}
