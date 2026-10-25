"""Lift the captured columns into semantic operations and structured control flow.

Intermediate only. No source from this file is installed into Studio.
"""

from dataclasses import dataclass
from collections import defaultdict, Counter, deque
import json,re,math


def R(n):
 if isinstance(n,bool) or not isinstance(n,(int,float)) or not 0<=n<4096 or int(n)!=n:
  raise ValueError(('invalid or oversized register index',n))
 return ('reg',int(n))
def U(n):
 if isinstance(n,bool) or not isinstance(n,(int,float)) or not 0<=n<4096 or int(n)!=n:
  raise ValueError(('invalid or oversized upvalue index',n))
 return ('up',int(n))
def K(n):return ('lit',n)
def G(n):return ('global',n.decode() if isinstance(n,bytes) else n)
def ix(a,b):return ('index',a,b)
def bin(a,op,b):return ('binary',op,a,b)
def neg(a):return ('unary','not',a)
def call(fn,args):return ('call',fn,tuple(args))

@dataclass
class Op:
 kind:str
 args:tuple
 pc:int=0
def O(kind,*args):return Op(kind,args)

class Function:
 def __init__(self,index,p,context,parents):
  d=context;functions_parents=parents
  self.index=index;self.p=p;self.params=0;self.vararg=False
  self.nodes={};self.succ={};self.loops={};self.skips=set();self.parents=[]
  self.live=context.reachable(p)
  if len(self.live)>5000:raise ValueError(('CFG exceeds 5000 reachable instructions',index))
  for pc in self.live:
   op=p[9][pc]
   if op in (20,39,69,73,82):self.skips.add(pc)
   if op==69:self.params=p[11][pc]
   if op==82:self.params=p[2][pc];self.vararg=True
  if type(self.params) is not int or not 0<=self.params<4096:raise ValueError(('invalid parameter count',index))
  def canon(pc):
   visited=set()
   while pc in self.skips:
    if pc in visited:raise RuntimeError(('jump cycle',index,pc))
    visited.add(pc)
    pc=p[8][pc]+1 if p[9][pc]==39 else pc+1
   return pc if pc in self.live else -1
  self.canon=canon;self.entry=canon(1)
  for pc in sorted(self.live-self.skips):
   vals={col:p[col].get(pc) for col in (1,2,3,6,8,9,11)}
   k,a,m,k2,b,op,c=[vals[col] for col in (1,2,3,6,8,9,11)]
   body=[];term=None
   setr=lambda dst,expr:body.append(O('set',R(dst),expr))
   setx=lambda dst,expr:body.append(O('set',dst,expr))
   invoke=lambda dst,argc,nret:body.append(O('call',dst,argc,nret))
   branch=lambda cond,dst:O('branch',cond,canon(dst+1),canon(pc+1))
   if op==0:
    child=d.ids[id(k2)];setr(a,('closure',child));functions_parents[child]=(index,pc,a)
   elif op==1:setr(b,ix(R(a),R(c)))
   elif op==2:setr(a,ix(R(b),K(k)))
   elif op==3:setr(a,bin(R(b),'/',R(c)))
   elif op==4:setx(ix(U(c),K(k2)),K(m))
   elif op==5:setx(ix(U(c),K(m)),R(b))
   elif op==6:setr(a,bin(R(b),'..',R(c)))
   elif op==7:term=branch(bin(K(m),'<=',R(b)),c)
   elif op==9:body.append(O('setlist',a,b,None))
   elif op==11:invoke(c,2,0)
   elif op==12:term=branch(bin(K(k),'>',R(b)),a)
   elif op==13:term=O('returncall',a,0)
   elif op==14:setx(ix(R(b),R(a)),K(k))
   elif op==15:setr(c,('varargs',))
   elif op==17:invoke(c,0,0)
   elif op==19:setr(c,bin(R(b),'*',K(m)))
   elif op==21:setr(c,bin(K(m),'+',R(b)))
   elif op==22:term=O('forprep',c,canon(b+1),'numeric')
   elif op==23:setx(ix(U(a),K(k)),K(k2))
   elif op==24:term=O('return',a,c-1)
   elif op==25:term=branch(bin(K(k2),'>=',R(a)),c)
   elif op==26:setr(b,ix(U(a),R(c)))
   elif op==27:term=branch(bin(K(m),'<',R(c)),b)
   elif op==28:setx(ix(U(c),R(a)),R(b))
   elif op==29:term=branch(bin(R(c),'~=',R(b)),a)
   elif op==30:setr(a,bin(K(k),'*',R(b)))
   elif op==31:setx(ix(U(b),R(c)),R(a))
   elif op==32:term=branch(bin(R(c),'>',K(k2)),a)
   elif op==33:setr(a,ix(U(c),K(k2)))
   elif op==35:setr(c,U(a))
   elif op==37:setr(c,('unary','-',R(b)))
   elif op==38:term=O('return',c,None)
   elif op==40:setr(c,bin(K(m),'^',R(b)))
   elif op==41:setr(a,('table',))
   elif op==42:body.append(O('clear',c,b))
   elif op==43:body.append(O('close',b))
   elif op==44:invoke(c,1,0)
   elif op==45:setr(b,bin(K(m),'..',R(c)))
   elif op==46:invoke(a,None,1)
   elif op==47:body.append(O('vararg',c))
   elif op==48:term=O('forstep',c,canon(a+1),canon(pc+1),'generic')
   elif op==50:setr(b,K(None))
   elif op==51:invoke(c,a-1,1)
   elif op==52:term=branch(bin(R(b),'~=',K(k)),a)
   elif op==53:setr(c,bin(K(m),'-',R(b)))
   elif op==54:term=O('returncall',a,c-1)
   elif op==55:term=O('forstep',c,canon(a+1),canon(pc+1),'numeric')
   elif op==56:invoke(a,None if c==0 else c-1,None if b==0 else b-1)
   elif op==57:setx(ix(R(a),K(k2)),R(c))
   elif op==58:term=O('returncall',c,None)
   elif op==59:setr(a,U(b))
   elif op==60:setr(a,neg(R(c)))
   elif op==61:setr(a,K(k))
   elif op==62:term=branch(bin(R(a),'>=',R(b)),c)
   elif op==63:
    body.append(O('method',a,R(c),K(k2)))
   elif op==64:invoke(c,0,1)
   elif op==65:setr(c,bin(R(b),'>=',R(a)))
   elif op==66:term=branch(bin(R(c),'<=',K(k2)),a)
   elif op==67:setr(a,bin(R(c),'==',K(k2)))
   elif op==68:term=branch(bin(R(c),'>',R(b)),a)
   elif op==70:setx(ix(U(a),K(k)),R(b))
   elif op==71:setr(b,bin(R(c),'-',K(m)))
   elif op==72:invoke(c,2,1)
   elif op==74:setr(b,bin(R(a),'^',K(k)))
   elif op==75:setr(b,bin(R(a),'..',K(k)))
   elif op==77:invoke(b,None,0)
   elif op==78:term=O('return',c,1)
   elif op==79:setr(c,call(G('unpack'),[R(a),R(b)]))
   elif op==80:setr(c,bin(R(b),'>',K(m)))
   elif op==81:setx(ix(R(c),K(k2)),K(m))
   elif op==83:invoke(a,c-1,0)
   elif op==84:setr(c,R(a))
   elif op==85:setr(b,bin(R(a),'^',R(c)))
   elif op==86:term=O('returncall',b,1)
   elif op==87:body.append(O('setlist',b,c,a))
   elif op==88:setr(c,ix(U(a),R(b)))
   elif op==89:term=branch(bin(R(b),'==',K(m)),c)
   elif op==90:setr(c,bin(K(k2),'/',R(a)))
   elif op==91:term=branch(neg(R(c)),b)
   elif op==92:setx(U(c),K(k2))
   elif op==93:setr(c,bin(R(b),'%',R(a)))
   elif op==94:setx(U(b),R(c))
   elif op==95:setr(a,call(G('unpack'),[R(b),K(k)]))
   elif op==97:setx(ix(R(c),R(b)),R(a))
   elif op==98:setr(c,G(k2))
   elif op==99:setr(b,bin(R(c),'+',K(m)))
   elif op==100:setx(G(k2),K(k))
   elif op==101:term=O('forprep',c,canon(a+1),'generic')
   elif op==102:term=branch(R(a),c)
   elif op==103:setr(c,bin(R(b),'*',R(a)))
   elif op==104:setr(a,bin(R(b),'==',R(c)))
   elif op==105:setr(b,bin(R(a),'/',K(k)))
   elif op==106:setr(a,bin(R(c),'-',R(b)))
   elif op==108:setr(a,bin(R(c),'%',K(k2)))
   elif op==109:term=O('return',1,0)
   elif op==110:setr(a,bin(R(c),'<',R(b)))
   elif op==111:setr(a,bin(R(b),'+',R(c)))
   elif op==113:setr(c,('table',))
   elif op==114:setr(c,('unary','#',R(a)))
   elif op==115:setr(a,ix(U(c),K(k2)))
   elif op==116:term=branch(bin(R(a),'>=',K(k)),b)
   elif op==117:invoke(a,1,1)
   elif op==118:term=branch(bin(R(b),'==',R(a)),c)
   elif op==120:setx(G(m),R(b))
   else:raise ValueError(('unsupported op',index,pc,op))
   term=term or O('next',canon(pc+1))
   for v in body+[term]:v.pc=pc
   self.nodes[pc]=(body,term)
   if term.kind=='next':succ=[term.args[0]]
   elif term.kind=='branch':succ=list(term.args[1:])
   elif term.kind=='forprep':succ=[term.args[1]]
   elif term.kind=='forstep':succ=list(term.args[1:3])
   else:succ=[-1]
   self.succ[pc]=succ
  for pc,(body,term) in self.nodes.items():
   if term.kind=='forprep':
    start,step,kind=term.args
    stepterm=self.nodes[step][1]
    assert stepterm.kind=='forstep',(index,pc,step,stepterm)
    assert kind==stepterm.args[-1]
    self.loops[pc]=(step,stepterm.args[1],stepterm.args[2],start,kind)



def descendants(expr):
 if not isinstance(expr,tuple):return
 yield expr
 for v in expr[1:]:
  if isinstance(v,tuple):
   if v and isinstance(v[0],str):yield from descendants(v)
   else:
    for a in v:yield from descendants(a)

def dominators(succ,entry):
 nodes=set(succ);pred=defaultdict(set)
 for n,targets in succ.items():
  for v in targets:
   if v in nodes:pred[v].add(n)
 dom={n:({entry} if n==entry else set(nodes)) for n in nodes}
 changed=True
 while changed:
  changed=False
  for n in nodes-{entry}:
   incoming=pred[n]
   result={n}|(set.intersection(*(dom[x] for x in incoming)) if incoming else set())
   if result!=dom[n]:dom[n]=result;changed=True
 return dom,pred

def postdominators(succ):
 nodes=set(succ)|{-1};order=sorted(nodes);bits={n:1<<i for i,n in enumerate(order)}
 allbits=(1<<len(order))-1
 masks={n:(bits[-1] if n==-1 else allbits) for n in nodes}
 changed=True
 while changed:
  changed=False
  for n in nodes-{-1}:
   targets=succ.get(n,[-1]);result=allbits
   for x in targets:result &= masks[x]
   result |= bits[n]
   if result!=masks[n]:masks[n]=result;changed=True
 pdom={n:{x for x in order if masks[n]&bits[x]} for n in nodes}
 ipdom={}
 for n in nodes-{-1}:
  cands=pdom[n]-{n}
  ipdom[n]=max(cands,key=lambda x:len(pdom[x])) if cands else -1
 return pdom,ipdom

class Structurer:
 def __init__(self,f,prefer_postdom=False):
  self.prefer_postdom=prefer_postdom
  self.f=f;self.nodes=f.nodes;self.succ=dict(f.succ)
  # Treat a complete for loop as one statement when finding surrounding joins.
  for prep,(step,body,exit,*_) in f.loops.items():self.succ[prep]=[exit]
  self.dom,self.pred=dominators(f.succ,f.entry)
  self.natural={}
  for n,targets in f.succ.items():
   for h in targets:
    if h in self.dom[n] and h not in [v[0] for v in f.loops.values()]:
     members={h,n};work=[n]
     while work:
      at=work.pop()
      for pr in self.pred[at]:
       if pr not in members:members.add(pr);work.append(pr)
     self.natural.setdefault(h,set()).update(members)
  self.pdom,self.ipdom=postdominators(f.succ)
  self.join_cache={}
  self.emitted=Counter();self.count=0

 def commonjoin(self,targets,boundaries):
  key=tuple(sorted(boundaries))
  if key not in self.join_cache:
   edges=dict(self.succ)
   for boundary in boundaries:
    if boundary!=-1:edges[boundary]=[-1]
   self.join_cache[key]=postdominators(edges)[0]
  pdom=self.join_cache[key]
  common=set.intersection(*(pdom.get(x,{-1}) for x in targets))
  if common:
   join=max(common,key=lambda x:len(pdom[x]))
   if self.prefer_postdom and join!=-1:return join
   # A nearer continuation may be shared by both branches while early
   # returns bypass it; consider reachability below before using postdom.
  # Early returns prevent an ordinary continuation from postdominating its
  # guard. Find the nearest shared continuation before falling back to exit.
  maps=[]
  for target in targets:
   dist={target:0};queue=deque([target])
   while queue:
    node=queue.popleft()
    if node in boundaries or node==-1:continue
    for nxt in self.succ.get(node,[-1]):
     if nxt!=-1 and nxt not in dist:dist[nxt]=dist[node]+1;queue.append(nxt)
   maps.append(dist)
  candidates=set.intersection(*(set(m) for m in maps))-{-1}
  if candidates:return min(candidates,key=lambda x:(max(m[x] for m in maps),sum(m[x] for m in maps)))
  return -1

 def emit(self,start,stop=-1,contexts=(),active=frozenset()):
  out=[];at=start;chain=set()
  while at!=stop and at!=-1:
   self.count+=1
   if self.count>100000:raise RuntimeError(('too much expansion',self.f.index,at))
   for cont,brk in reversed(contexts):
    if at==cont:return out+[O('continue')]
    if at==brk:return out+[O('break')]
   if at in chain:raise RuntimeError(('unstructured cycle',self.f.index,at,stop))
   chain.add(at)
   if at in self.natural and at not in active:
    members=self.natural[at]
    exits={v for n in members for v in self.f.succ[n] if v not in members}
    exit=self.commonjoin(exits,set()) if len(exits)>1 else next(iter(exits),-1)
    # Keep local loop exits inside the body; only the common exit becomes break.
    body=self.emit_loop(at,exit,contexts,active)
    out.append(Op('while',(body,),at));at=exit;continue
   self.emitted[at]+=1
   body,term=self.nodes[at];out.extend(body)
   if term.kind=='next':at=term.args[0]
   elif term.kind=='branch':
    cond,yes,no=term.args
    if yes==no:at=yes;continue
    # An enclosing continue/break is itself a structured terminal edge.
    boundary={v for pair in contexts for v in pair}|{stop,-1}
    join=self.commonjoin([yes,no],boundary)
    if yes==stop:
     out.append(Op('if',(neg(cond),self.emit(no,stop,contexts,active),[]),at));return out
    elif no==stop:
     out.append(Op('if',(cond,self.emit(yes,stop,contexts,active),[]),at));return out
    elif yes in boundary and no not in boundary:
     a=self.emit(yes,stop,contexts,active);out.append(Op('if',(cond,a,[]),at));at=no
    elif no in boundary and yes not in boundary:
     b=self.emit(no,stop,contexts,active);out.append(Op('if',(neg(cond),b,[]),at));at=yes
    else:
     a=self.emit(yes,join,contexts,active);b=self.emit(no,join,contexts,active)
     out.append(Op('if',(cond,a,b),at));at=join
   elif term.kind=='forprep':
    step,body,exit,base,kind=self.f.loops[at]
    loopbody=self.emit(body,step,contexts+((step,exit),),active)
    out.append(Op('for',(kind,base,loopbody),at));at=exit
   elif term.kind=='forstep':
    raise RuntimeError(('unclaimed forstep',self.f.index,at,stop))
   else:out.append(term);return out
  return out

 def emit_loop(self,header,exit,contexts,active):
  # The header is permitted once on entry; returning to it becomes continue.
  body,term=self.nodes[header]
  ctx=contexts+((header,exit),)
  out=list(body)
  if term.kind=='next':out+=self.emit(term.args[0],exit,ctx,active|{header})
  elif term.kind=='branch':
   cond,yes,no=term.args
   if yes==exit:out.append(Op('if',(cond,[O('break')],[]),header));out+=self.emit(no,exit,ctx,active|{header})
   elif no==exit:out.append(Op('if',(neg(cond),[O('break')],[]),header));out+=self.emit(yes,exit,ctx,active|{header})
   else:
    join=self.commonjoin([yes,no],{v for pair in ctx for v in pair}|{-1})
    out.append(Op('if',(cond,self.emit(yes,join,ctx,active|{header}),self.emit(no,join,ctx,active|{header})),header))
    out+=self.emit(join,exit,ctx,active|{header})
  else:raise RuntimeError(('bad loopheader',self.f.index,header,term.kind))
  # Falling out of the emitted loop region means taking its exit edge.
  # Backedges already emit continue explicitly.
  if not out or out[-1].kind not in ('continue','break','return','returncall'):
   out.append(O('break'))
  return out

def encode(x):
 if isinstance(x,dict):return {key:encode(value) for key,value in x.items()}
 if isinstance(x,Op):return {'kind':x.kind,'args':[encode(v) for v in x.args],'pc':x.pc}
 if isinstance(x,tuple) or isinstance(x,list):return [encode(v) for v in x]
 if isinstance(x,bytes):return {'bytes':x.hex()}
 if isinstance(x,float) and not math.isfinite(x):return {'number':'nan' if math.isnan(x) else '+inf' if x>0 else '-inf'}
 return x
