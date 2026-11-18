'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowUpRight, ArrowRight, ArrowUp, Command, Compass, Globe2, Database,
  Layers3, Sparkles, Search, LoaderCircle, RotateCcw, Check, Copy, ExternalLink,
  PanelRightClose, PanelRightOpen, ShieldCheck, Terminal, X, Cpu, Radio, ChevronDown, History, Trash2,
  Zap, Building2, Menu, CircleDot, FileText, MapPin, ArrowDown, LockKeyhole } from 'lucide-react';
import type { ChatResult, Message, Model, Source, ToolActivity } from '@/lib/types';

const SUGGESTIONS = [
  { icon: Building2, title: 'Development portfolio', query: 'What developments are documented for DarGlobal in Dubai?', label: 'RESEARCH' },
  { icon: MapPin, title: 'Explore by region', query: 'Which DarGlobal developments are documented in Oman?', label: 'GEOGRAPHY' },
  { icon: Layers3, title: 'Cross-source analysis', query: 'What verifiable information connects DarGlobal and Wasalt?', label: 'DISCOVERY' },
  { icon: Search, title: 'Saudi property listings', query: 'Show apartments for sale in Riyadh on Wasalt.', label: 'MARKETPLACE' },
];
const sourceName = (s: string) => s === 'darglobal' ? 'DarGlobal' : 'Wasalt';
const uid = () => (typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);
function ClockIcon(){ return <span className="pulse-dot" />; }

function ArchitectureGraphic(){
  return <div className="arch-window" aria-hidden="true">
    <svg viewBox="0 0 600 390" className="arch-svg" preserveAspectRatio="xMidYMid slice">
      <defs>
        <linearGradient id="bldg" x1="0" x2="1" y1="0" y2="1"><stop stopColor="#b8a991" stopOpacity=".22"/><stop offset="1" stopColor="#5f6a5f" stopOpacity=".02"/></linearGradient>
      </defs>
      <g fill="none" stroke="#d2c3a9" strokeOpacity=".20" strokeWidth=".9">
        {Array.from({length: 16}, (_,i)=><line key={'h'+i} x1="0" x2="600" y1={i*26} y2={i*26}/>)}
        {Array.from({length: 25}, (_,i)=><line key={'v'+i} y1="0" y2="390" x1={i*26} x2={i*26}/>)}
      </g>
      <g fill="url(#bldg)" stroke="#ddceb4" strokeOpacity=".57" strokeWidth="1.5">
        <path d="M167 380 V80 L239 32 L307 80 V380Z"/>
        <path d="M306 380 V126 L392 69 L469 127 V380Z"/>
        <path d="M114 380 V172 L168 143 V380Z"/>
        <path d="M239 32 L239 380 M167 80 L239 109 L307 80 M307 126 L392 164 L469 127"/>
      </g>
      <g stroke="#ddd1be" strokeOpacity=".52" fill="none" strokeWidth="1.1">
        {Array.from({length: 10},(_,i)=><path key={'f'+i} d={`M167 ${120+i*25} L239 ${148+i*25} L307 ${120+i*25}`}/>)}
        {Array.from({length: 8},(_,i)=><path key={'g'+i} d={`M307 ${170+i*25} L392 ${208+i*25} L469 ${170+i*25}`}/>)}
        {Array.from({length: 5},(_,i)=><path key={'c'+i} d={`M185 ${95+i*60} V${118+i*60} M265 ${100+i*60} V${123+i*60} M348 ${178+i*40} V${204+i*40}`}/>)}
      </g>
      <g fill="none" stroke="#dfab74" strokeWidth=".9" strokeDasharray="5 7"><circle cx="392" cy="164" r="95"/><circle cx="392" cy="164" r="140"/></g>
      <circle cx="392" cy="164" r="6" fill="#d3a877"/>
      <path d="M392 164 L521 104" stroke="#d3a877" strokeWidth="1.3"/>
      <circle cx="521" cy="104" r="3" fill="#d3a877"/>
      <text x="522" y="91" fill="#e2c39e" fontSize="9" letterSpacing="2">SOURCE SIGNAL</text>
      <text x="22" y="360" fill="#c9b89a" fontSize="10" letterSpacing="2">FIG. 01 / DIGITAL PROPERTY INDEX</text>
    </svg>
    <div className="arch-bottom"><span>LAT 24.7136° N</span><span>LONG 46.6753° E</span><span>LIVE INTELLIGENCE</span></div>
  </div>;
}

function RichAnswer({text}:{text:string}){
  // Plain text rendering eliminates generated HTML and XSS exposure.
  return <div className="answer-copy">{text.split(/(\[E\d+\]|\*\*[^*]+\*\*)/g).map((part,i)=>part.startsWith('**')&&part.endsWith('**')?<strong key={i}>{part.slice(2,-2)}</strong>:<span key={i} className={/^\[E\d+\]$/.test(part)?'inline-ref':''}>{part}</span>)}</div>;
}

export default function Home(){
  const [models,setModels]=useState<Model[]>([{id:'openrouter/free',name:'Auto · Free router',free:true,tools:false,context_length:null}]);
  const [model,setModel]=useState('openrouter/free');
  const [modelOpen,setModelOpen]=useState(false);
  const [modelQuery,setModelQuery]=useState('');
  const [sources,setSources]=useState<Source[]>([]);
  const [sourceFilter,setSourceFilter]=useState<string[]>(['darglobal','wasalt']);
  const [messages,setMessages]=useState<Message[]>([]);
  const [input,setInput]=useState('');
  const [busy,setBusy]=useState(false);
  const [activity,setActivity]=useState<string>('');
  const [rightOpen,setRightOpen]=useState(true);
  const [mobileMenu,setMobileMenu]=useState(false);
  const [evidenceDrawer,setEvidenceDrawer]=useState(false);
  const [compactEvidence,setCompactEvidence]=useState(false);
  const [compactMenu,setCompactMenu]=useState(false);
  const menuButtonRef=useRef<HTMLButtonElement>(null);
  const evidenceButtonRef=useRef<HTMLButtonElement>(null);
  const menuCloseRef=useRef<HTMLButtonElement>(null);
  const evidenceCloseRef=useRef<HTMLButtonElement>(null);
  const [liveSearch,setLiveSearch]=useState(true);
  const [online,setOnline]=useState<boolean|null>(null);
  const [aiReady,setAiReady]=useState(false);
  const [catalogOnline,setCatalogOnline]=useState<boolean|null>(null);
  const [catalogLoading,setCatalogLoading]=useState(false);
  const threadVersion=useRef(0);
  const [conv,setConv]=useState<{id:string,token:string}|null>(null);
  const [selection,setSelection]=useState<number>(-1);
  const [history,setHistory]=useState<{id:string;token:string;title:string;updatedAt:number}[]>([]);
  const [toast,setToast]=useState('');
  const inputRef=useRef<HTMLTextAreaElement>(null);
  const bottomRef=useRef<HTMLDivElement>(null);
  const abortRef=useRef<AbortController|null>(null);

  useEffect(()=>{
    const menu=window.matchMedia('(max-width: 900px)');
    const evidence=window.matchMedia('(max-width: 1240px)');
    const sync=()=>{setCompactMenu(menu.matches);setCompactEvidence(evidence.matches);
      if(!menu.matches)setMobileMenu(false);if(!evidence.matches)setEvidenceDrawer(false);};
    sync();menu.addEventListener('change',sync);evidence.addEventListener('change',sync);
    return()=>{menu.removeEventListener('change',sync);evidence.removeEventListener('change',sync)};
  },[]);
  const closeMenu=()=>{setMobileMenu(false);requestAnimationFrame(()=>menuButtonRef.current?.focus())};
  const closeEvidence=()=>{setEvidenceDrawer(false);requestAnimationFrame(()=>evidenceButtonRef.current?.focus())};
  useEffect(()=>{
    if(mobileMenu)menuCloseRef.current?.focus();
    if(evidenceDrawer)evidenceCloseRef.current?.focus();
    const key=(event:KeyboardEvent)=>{
      if(event.key==='Escape'){
        if(evidenceDrawer){setEvidenceDrawer(false);requestAnimationFrame(()=>evidenceButtonRef.current?.focus())}
        else if(mobileMenu){setMobileMenu(false);requestAnimationFrame(()=>menuButtonRef.current?.focus())}
        else setModelOpen(false);
      }
      // Keep focus inside the open modal drawer when tabbing.
      if(event.key==='Tab'&&(mobileMenu||evidenceDrawer)){
        const node=document.getElementById(mobileMenu?'source-navigation':'evidence-drawer');
        const focusable=Array.from(node?.querySelectorAll<HTMLElement>('button:not([disabled]),a[href],input:not([disabled]),[tabindex="0"]')||[]).filter(el=>el.getClientRects().length>0);
        if(!focusable.length)return;
        const first=focusable[0],last=focusable[focusable.length-1];
        if(event.shiftKey&&(document.activeElement===first||!node?.contains(document.activeElement))){event.preventDefault();last.focus()}
        else if(!event.shiftKey&&(document.activeElement===last||!node?.contains(document.activeElement))){event.preventDefault();first.focus()}
      }
    };window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);
  },[mobileMenu,evidenceDrawer]);
  useEffect(()=>{
    try {const raw=localStorage.getItem('estate:history');if(raw)setHistory(JSON.parse(raw));}
    catch {setHistory([]);}
  },[]);
  const refreshModels=useCallback(async(refresh=false)=>{
    setCatalogLoading(true);
    try{
      const res=await fetch(`/api/v1/models${refresh?'?refresh=true':''}`,{cache:'no-store',signal:AbortSignal.timeout(18000)});
      if(!res.ok)throw new Error('Model catalogue unavailable');
      const data=await res.json();
      if(!Array.isArray(data.models))throw new Error('Invalid model catalog');
      setModels(data.models);setAiReady(Boolean(data.configured));setCatalogOnline(Boolean(data.catalog_online));
      setModel(old=>data.models.some((m:Model)=>m.id===old)?old:'openrouter/free');
    }catch{setCatalogOnline(false)}finally{setCatalogLoading(false)}
  },[]);
  useEffect(()=>{void refreshModels()},[refreshModels]);
  useEffect(()=>{
    let active=true;
    const load=async()=>{
      const [b,c]=await Promise.allSettled([
        fetch('/api/v1/sources').then(r=>r.json()),
        fetch('/api/v1/health/ready').then(r=>r.json())
      ]);
      if(!active)return;
      if(b.status==='fulfilled'&&Array.isArray(b.value.sources))setSources(b.value.sources);
      setOnline(c.status==='fulfilled'&&c.value.status==='ready');
    };load().catch(()=>setOnline(false));return()=>{active=false;};
  },[]);
  useEffect(()=>bottomRef.current?.scrollIntoView({behavior:busy?'smooth':'auto'}),[messages,activity,busy]);
  useEffect(()=>{if(toast){const id=setTimeout(()=>setToast(''),2500);return()=>clearTimeout(id)}},[toast]);

  const send=useCallback(async(custom?:string)=>{
    const question=(custom??input).trim();if(!question||busy||abortRef.current||question.length<3)return;
    threadVersion.current++;setInput('');setActivity('Researching verified records');setBusy(true);setSelection(-1);
    const pending:Message={id:uid(),role:'assistant',text:'',loading:true};
    setMessages(prev=>[...prev,{id:uid(),role:'user',text:question},pending]);
    const controller=new AbortController();abortRef.current=controller;
    const body={message:question,model,source_filter:sourceFilter,conversation_id:conv?.id||null,
      conversation_token:conv?.token||null,allow_live_search:liveSearch};
    let accumulated='';let completed=false;
    const timer=setTimeout(()=>controller.abort(),125000);
    try{
      const res=await fetch('/api/v1/chat/stream',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify(body),signal:controller.signal});
      if(!res.ok||!res.body)throw new Error(`Service error (${res.status})`);
      const reader=res.body.getReader();const dec=new TextDecoder();let buffer='';
      const process=(block:string)=>{
        if(abortRef.current!==controller||controller.signal.aborted)return;
        const lines=block.split('\n');let event='message',data='';
        for(const line of lines){if(line.startsWith('event:'))event=line.slice(6).trim();if(line.startsWith('data:'))data+=line.slice(5).trim();}
        if(!data)return;
        const p=JSON.parse(data);
        if(event==='activity')setActivity(p.detail||p.phase||'');
        if(event==='delta'){
          accumulated+=p.text||'';
          setMessages(prev=>prev.map(m=>m.id===pending.id?{...m,text:accumulated,loading:true}:m));
        }
        if(event==='done'){
          const result=p as ChatResult;completed=true;setActivity('');
          if(result.conversation_id&&result.conversation_token){
            setConv({id:result.conversation_id,token:result.conversation_token});
            const newThread={id:result.conversation_id,token:result.conversation_token,title:question.slice(0,64),updatedAt:Date.now()};
            setHistory(prev=>{
              const existing=prev.find(x=>x.id===newThread.id);
              const next=[{...newThread,title:existing?.title||newThread.title},...prev.filter(x=>x.id!==newThread.id)].slice(0,18);
              try{localStorage.setItem('estate:history',JSON.stringify(next));}catch{};
              return next;
            });
          }
          setMessages(prev=>prev.map(m=>m.id===pending.id?{...m,text:result.answer||accumulated,citations:result.sources||[],
            status:result.status,model:result.model_used||undefined,activity:result.tool_activity||[],reason:result.reason,fallback:result.fallback_used,query:result.retrieval_query,loading:false}:m));
        }
        if(event==='error')throw new Error(p.message||'Request failed');
      };
      while(true){const {done,value}=await reader.read();if(done)break;buffer+=dec.decode(value,{stream:true});
        let pos;while((pos=buffer.indexOf('\n\n'))!==-1){const b=buffer.slice(0,pos);buffer=buffer.slice(pos+2);process(b);}}
      if(buffer.trim())process(buffer);
      if(!completed && !controller.signal.aborted)throw new Error('Connection closed before the answer completed. Please retry.');
    }catch(err){
      if(abortRef.current!==controller)return;
      const msg=controller.signal.aborted?'Request cancelled or timed out':err instanceof Error?err.message:'Unknown request failure';
      setMessages(prev=>prev.map(m=>m.id===pending.id?{...m,text:`Research request failed: ${msg}`,status:'error',loading:false}:m));
    }finally{clearTimeout(timer);if(abortRef.current===controller){setBusy(false);setActivity('');abortRef.current=null;inputRef.current?.focus();
      void fetch('/api/v1/sources',{cache:'no-store'}).then(r=>r.json()).then(d=>{if(Array.isArray(d.sources))setSources(d.sources)}).catch(()=>{});}}
  },[busy,conv,input,liveSearch,model,sourceFilter]);

  const reset=()=>{threadVersion.current++;abortRef.current?.abort();abortRef.current=null;setBusy(false);setMessages([]);setConv(null);setActivity('');setInput('');setMobileMenu(false);setEvidenceDrawer(false);setModelOpen(false);};
  const openThread=async(thread:{id:string;token:string;title:string;updatedAt:number})=>{
    if(busy)return;
    const version=++threadVersion.current;
    try{
      const resp=await fetch(`/api/v1/conversations/${encodeURIComponent(thread.id)}`,{
        headers:{'X-Conversation-Token':thread.token}});
      if(!resp.ok)throw new Error('Conversation is no longer accessible');
      const doc=await resp.json();
      if(version!==threadVersion.current||abortRef.current)return;
      setMessages((doc.messages||[]).map((m:{role:'user'|'assistant';text:string})=>({id:uid(),role:m.role,text:m.text})));
      setConv({id:thread.id,token:thread.token});setMobileMenu(false);
    }catch{setToast('Could not retrieve this conversation');}
  };
  const removeThread=async(thread:{id:string;token:string;title:string;updatedAt:number})=>{
    try{await fetch(`/api/v1/conversations/${encodeURIComponent(thread.id)}`,{method:'DELETE',headers:{'X-Conversation-Token':thread.token}})}catch{}
    setHistory(prev=>{const next=prev.filter(x=>x.id!==thread.id);try{localStorage.setItem('estate:history',JSON.stringify(next))}catch{};return next});
    if(conv?.id===thread.id)reset();
  };
  const toggleSource=(s:string)=>setSourceFilter(prev=>prev.includes(s)?(prev.length>1?prev.filter(x=>x!==s):prev):[...prev,s]);
  const docCount=sources.reduce((a,s)=>a+s.documents,0);
  const activeCount=sources.filter(s=>s.permitted&&s.documents>0).length;
  const showEvidence=compactEvidence?evidenceDrawer:rightOpen;
  const citations=messages.filter(x=>x.role==='assistant').at(-1)?.citations||[];
  const latestSources=Array.from(new Map<string, import('@/lib/types').Citation>(citations.map(x=>[x.url,x] as [string,import('@/lib/types').Citation])).values()).slice(-7).reverse();
  const filteredModels=models.filter(m=>m.name.toLowerCase().includes(modelQuery.toLowerCase())||m.id.toLowerCase().includes(modelQuery.toLowerCase()));
  const copy=(text:string)=>navigator.clipboard.writeText(text).then(()=>setToast('Copied to clipboard')).catch(()=>setToast('Clipboard unavailable'));

  return <div className="shell">
    {(mobileMenu||evidenceDrawer)&&<button type="button" className="drawer-backdrop" aria-label="Close research panel" onClick={()=>mobileMenu?closeMenu():closeEvidence()}/>}
    {(!compactMenu||mobileMenu)&&<aside id="source-navigation" className={`sidebar ${mobileMenu?'show':''}`} role={compactMenu?'dialog':undefined} aria-modal={compactMenu?true:undefined} aria-label="Research sources and history">
      <div className="brand-row"><div className="brand-mark"><Compass size={22} strokeWidth={1.6}/><span className="brand-mark-point"/></div>
        <div><div className="brand-top">ESTATE<span className="brand-dot">.</span></div><div className="brand-bottom">INTELLIGENCE</div></div>
        <button ref={menuCloseRef} className="mobile-close" onClick={closeMenu} aria-label="Close menu"><X size={20}/></button>
      </div>
      <div className="sidebar-overline">YOUR WORKSPACE <span>01 / 03</span></div>
      <button className="new-session" onClick={reset}><span className="new-icon"><Sparkles size={16}/></span><span>New research session</span><ArrowUpRight size={16}/></button>
      <div className="side-section"><div className="side-label">RESEARCH SOURCES <span className="label-dash" /></div>
        {(['darglobal','wasalt'] as const).map((id,index)=>{const src=sources.find(s=>s.id===id);return <button key={id}
          className={`source-option ${sourceFilter.includes(id)?'active':''}`} onClick={()=>toggleSource(id)} aria-pressed={sourceFilter.includes(id)}>
          <div className={`source-icon ${id}`}><Building2 size={17} strokeWidth={1.7}/></div>
          <span className="source-desc"><strong>{sourceName(id)}</strong><small>{src?.documents??'—'} indexed documents</small></span>
          <span className={`source-checkbox ${sourceFilter.includes(id)?'checked':''}`}>{sourceFilter.includes(id)&&<Check size={12}/>}</span>
        </button>})}
      </div>
      <div className="side-section discovery"><div className="side-label">DISCOVERY ENGINE <span className="label-dash" /></div>
        <div className="discovery-inner"><div className="discovery-heading"><span className="radar-icon"><Radio size={16}/></span><span>Official source lookup</span>
          <button aria-label="Toggle live source lookup" role="switch" aria-checked={liveSearch}
            className={`switch ${liveSearch?'on':''}`} onClick={()=>setLiveSearch(v=>!v)}><i/></button></div>
          <p>Search permitted source pages when indexed evidence isn't sufficient.</p>
        </div>
      </div>
      {history.length>0&&<div className="side-section recent-section"><div className="side-label">RECENT RESEARCH <span className="label-dash" /></div>
        <div className="recent-list">{history.slice(0,5).map(h=><div key={h.id} className={`recent-item ${conv?.id===h.id?'recent-current':''}`}>
          <button onClick={()=>openThread(h)} title={h.title}><History size={14}/><span>{h.title}</span></button>
          <button className="recent-delete" onClick={()=>removeThread(h)} title="Delete conversation"><Trash2 size={13}/></button>
        </div>)}</div></div>}
      <div className="sidebar-spacer" />
      <div className="side-note"><ShieldCheck size={17}/><div><strong>Evidence, not estimates.</strong><span>Every factual answer is linked to the source it came from.</span></div></div>
      <div className="side-footer"><div className="footer-mono">EST / SYSTEM V1.0</div><div className="footer-line"><span className={`small-dot ${online?'ok':''}`} />{online===true?'SYSTEM OPERATIONAL':online===false?'SERVICE DISCONNECTED':'CHECKING SERVICE'}</div></div>
    </aside>}
    <main className="main-area" inert={mobileMenu?true:undefined}>
      <header className="topbar"><div className="top-left"><button ref={menuButtonRef} className="menu-mobile" onClick={()=>{setEvidenceDrawer(false);setMobileMenu(true)}} aria-label="Open menu" aria-expanded={mobileMenu}><Menu size={21}/></button>
          <span className="breadcrumb-first">WORKSPACE</span><span className="slash">/</span><span className="breadcrumb-current">RESEARCH STUDIO</span></div>
        <div className="top-actions"><div className="connection"><ClockIcon/> {online===true?'CONNECTED':'CONNECTING'}</div>
          <button className="icon-only" title="Reset conversation" onClick={reset}><RotateCcw size={17}/></button>
          <button ref={evidenceButtonRef} className="icon-only right-toggle" onClick={()=>{if(compactEvidence){setMobileMenu(false);setEvidenceDrawer(v=>!v)}else setRightOpen(v=>!v)}} title="Toggle evidence panel" aria-label="Toggle evidence panel" aria-expanded={showEvidence}>{showEvidence?<PanelRightClose size={19}/>:<PanelRightOpen size={19}/>}</button>
          <div className="avatar">EI</div>
        </div>
      </header>
      <div className={`central-layout ${showEvidence?'has-right':''}`}>
        <section className="conversation-area" inert={evidenceDrawer?true:undefined}>
          <div className="research-scroll" aria-label="Conversation" tabIndex={0}>
          {messages.length===0 ? <div className="landing">
            <div className="hero-brow"><span className="tiny-line"/> INTELLIGENCE / REAL ESTATE <span className="hero-brow-number">001—2026</span></div>
            <h1>Every property<br/>has a <em>story.</em><br/><span>Find the facts.</span></h1>
            <p className="hero-desc">Source-grounded research across global developments and Saudi Arabian real estate. Built to distinguish what&apos;s documented from what&apos;s assumed.</p>
            <div className="hero-data"><div><span>ACTIVE SOURCES</span><strong>{String(activeCount).padStart(2,'0')}<span className="data-sup">/02</span></strong></div><div><span>INDEXED RECORDS</span><strong>{docCount.toString().padStart(2,'0')}</strong></div><div><span>RETRIEVAL</span><strong className="data-mode">HYBRID <span>↗</span></strong></div></div>
            <ArchitectureGraphic/>
            <div className="suggest-section"><div className="suggest-heading"><span>START EXPLORING</span><span className="right-tip">CURATED RESEARCH PATHS <ArrowDown size={12}/></span></div>
              <div className="suggest-grid">{SUGGESTIONS.map(s=><button key={s.title} className="suggest-card" onClick={()=>send(s.query)}>
                <div className="suggest-top"><s.icon size={18} strokeWidth={1.6}/><ArrowUpRight size={16}/></div>
                <div><span className="suggest-tag">{s.label}</span><strong>{s.title}</strong></div></button>)}</div>
            </div>
          </div> : <div className="conversation-thread"><div className="conversation-intro"><span>RESEARCH CONVERSATION</span><strong>Evidence-backed analysis</strong><small>{messages.filter(m=>m.role==='user').length} queries · {sourceFilter.map(sourceName).join(' + ')}</small></div>
            {messages.map(m=><div key={m.id} className={`message ${m.role}`}>
              {m.role==='assistant'&&<div className="ai-symbol"><Sparkles size={17}/></div>}
              <div className="message-content"><div className="message-meta">{m.role==='user'?'YOUR QUESTION':'ESTATE / INTELLIGENCE'}{m.loading&&<span className="status-tag"><LoaderCircle size={12} className="spin"/> PROCESSING</span>}{m.status&&<span className="result-tag">{m.status.replace(/_/g,' ').toUpperCase()}</span>}</div>
                {m.text?<RichAnswer text={m.text}/>:<div className="thinking"><i/><i/><i/> <span>{activity||'Researching evidence...'}</span></div>}
                {m.citations&&m.citations.length>0&&<div className="inline-sources"><div className="inline-sources-label">SOURCE EVIDENCE · {m.citations.length}</div><div className="inline-sources-row">{m.citations.map(c=><a key={c.id} href={c.url} target="_blank" rel="noopener noreferrer"><span>{c.id}</span>{c.title.slice(0,55)}<ArrowUpRight size={13}/></a>)}</div></div>}
                {m.role==='assistant'&&!m.loading&&m.reason&&<small className="diagnostic-line">{m.reason.replaceAll('_',' ')}</small>}
                {m.activity&&m.activity.length>0&&<details className="research-diagnostics"><summary>Research activity</summary>{m.activity.map((a,i)=><p key={i}>{a.status}: {a.detail}</p>)}</details>}
                {m.role==='assistant'&&!m.loading&&<div className="message-actions"><button onClick={()=>copy(m.text)}><Copy size={13}/> Copy</button>{m.model&&<span><Cpu size={12}/>{m.model}</span>}{m.fallback&&<span>Fallback used</span>}</div>}
              </div></div>)}
            <div ref={bottomRef}/></div>}
          </div>
          <div className="composer-wrap"><div className="composer"><div className="composer-head"><div className="model-control">
                <button className={`model-trigger ${modelOpen?'selected':''}`} onClick={()=>setModelOpen(v=>!v)} aria-expanded={modelOpen}><span className="model-orb"><Sparkles size={14}/></span><span className="model-verb">MODEL</span><strong>{models.find(m=>m.id===model)?.name||'Auto · Free router'}</strong><ChevronDown size={14}/></button>
                {modelOpen&&<div className="model-popover"><input value={modelQuery} onChange={e=>setModelQuery(e.target.value)} placeholder="Search free models..." autoFocus/><div className="catalog-status"><span>{catalogLoading?'Refreshing…':catalogOnline?`${models.length-1} selectable free models`:'Catalogue unavailable · auto router only or cached models'}</span><button type="button" disabled={catalogLoading} onClick={()=>refreshModels(true)}>Refresh</button></div><div className="model-results">{filteredModels.slice(0,70).map(m=><button key={m.id} className={m.id===model?'current':''} onClick={()=>{setModel(m.id);setModelOpen(false);setModelQuery('')}}><span><strong>{m.name}</strong><small>{m.id}</small></span><span className="model-badges">FREE {m.tools?'· TOOLS':''}</span></button>)}{!filteredModels.length&&<span className="model-empty">No available matching models</span>}</div></div>}
                </div><span className="composer-mode"><CircleDot size={13}/> VERIFIED SOURCES ONLY</span></div>
              {!aiReady&&<div className="diagnostic-line">OpenRouter key not configured or not yet checked. Configure the backend before AI generation.</div>}
              <textarea ref={inputRef} rows={2} value={input} disabled={busy} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();send()}}} maxLength={1500} placeholder="Ask anything about properties, locations, developments..." aria-label="Ask a real estate research question"/>
              <div className="composer-foot"><span><kbd>↵</kbd> to send <b>·</b> <kbd>shift ↵</kbd> for new line</span><div className="composer-foot-right"><span>{input.length}/1500</span><button onClick={()=>busy?abortRef.current?.abort():send()} disabled={!busy&&input.trim().length<3} className="submit-btn" title={busy?"Stop generating":"Submit question"} aria-label={busy?"Stop generating":"Submit question"}>{busy?<X size={18}/>:<ArrowUp size={19}/>}</button></div></div>
            </div><div className="composer-disclaimer"><ShieldCheck size={12}/> Responses are research aids. Verify financial decisions with official sources.</div></div>
        </section>
        {showEvidence&&<aside id="evidence-drawer" className={`evidence-panel ${compactEvidence?'evidence-drawer':''}`} role={compactEvidence?'dialog':undefined} aria-modal={compactEvidence?true:undefined} aria-label="Source evidence"><div className="evidence-top"><span>RESEARCH CONTEXT</span>{compactEvidence?<button ref={evidenceCloseRef} className="icon-only drawer-close" onClick={closeEvidence} aria-label="Close evidence panel"><X size={20}/></button>:<span className="panel-count">{String(activeCount).padStart(2,'0')} / 02</span>}</div>
          <div className="evidence-title">The evidence<br/><em>behind the answer.</em></div>
          <div className="evidence-divider"/>
          <div className="panel-heading">SOURCE CONNECTIONS <span>●</span></div>
          <div className="connection-list">{(['darglobal','wasalt'] as const).map(id=>{const s=sources.find(x=>x.id===id);return <div className="connection-card" key={id}><div className="conn-symbol"><Globe2 size={17}/></div><div className="conn-data"><strong>{sourceName(id)}</strong><small>{s?.documents??0} indexed documents</small><span className={s?.permitted&&!['access_restricted','unavailable','permission_required'].includes(s.last_run_status)?'conn-status indexed':'conn-status restricted'}>{s?.last_run_status==='access_restricted'?'CLOUDFLARE CHALLENGE':s?.last_run_status==='unavailable'?'UNAVAILABLE':s?.last_run_status==='permission_required'||!s?.permitted?'RESTRICTED / PENDING':'PERMITTED'}</span>{s?.last_run_status&&<small className="source-status-detail">{s.last_run_status.replaceAll('_',' ')}{s.permission_note?` · ${s.permission_note}`:''}</small>}</div><a target="_blank" rel="noopener noreferrer" href={id==='darglobal'?'https://darglobal.co.uk/':'https://wasalt.sa/'} aria-label={`Open ${id}`}><ArrowUpRight size={16}/></a></div>})}</div>
          <div className="evidence-divider"/>
          <div className="panel-heading">EVIDENCE LOG <span>{latestSources.length.toString().padStart(2,'0')}</span></div>
          {latestSources.length? <div className="evidence-log">{latestSources.map((s,i)=><a key={i} href={s.url} target="_blank" rel="noopener noreferrer" className="evidence-item"><span className="evidence-id">{s.id}</span><span><strong>{s.title}</strong><small>{sourceName(s.source)} · source record</small><small>{s.excerpt}</small></span><ExternalLink size={13}/></a>)}</div>:<div className="empty-evidence"><div className="empty-radar"><span/><span/><span/><CircleDot size={19}/></div><strong>Awaiting first discovery</strong><p>Verified citations and source signals will appear here as you research.</p></div>}
          <div className="panel-bottom"><LockKeyhole size={15}/><span>Evidence is retrieved from indexed records and authorized official pages. Unsupported claims are withheld.</span></div>
        </aside>}
      </div>
    </main>{toast&&<div className="toast"><Check size={15}/>{toast}</div>}
  </div>;
}
