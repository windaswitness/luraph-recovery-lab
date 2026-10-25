"""Arity-aware Luau emission with conservative folding and lexical cells."""
from collections import Counter, defaultdict
from types import SimpleNamespace
import math
import re
from narsil.lua_lex import quote
from .lift import Op, O, R, U, K, G, ix, call

def render(context, functions, parents, structured):
    """Return a non-invoked root function suitable for manual inspection."""
    l=SimpleNamespace(functions=functions, functions_parents=parents)
    raw=structured
    def lower(seq):
     out=[];multi=None;top=None
     def args(base,count):
      nonlocal multi
      if count is not None:return [R(n) for n in range(base+1,base+count+1)]
      if multi:
       start,expr=multi
       if start<=base:raise ValueError(('bad multibase',start,base))
       multi=None
       return [R(n) for n in range(base+1,start)]+[expr]
      if top is None:raise ValueError(('unknown top',base))
      return [R(n) for n in range(base+1,top+1)]
     for op in seq:
      k=op.kind;a=op.args
      if k=='method':
       dest,obj,key=a
       out.append(O('set',R(dest+1),obj))
       out.append(O('set',R(dest),('methodvalue',obj,key)))
      elif k=='call':
       base,argc,nret=a;expr=call(R(base),args(base,argc))
       if nret is None:
        assert multi is None
        multi=(base,expr)
       elif nret==0:out.append(O('expr',expr));top=base-1
       elif nret==1:out.append(O('set',R(base),('single',expr)));top=base
       else:out.append(O('assign',tuple(R(n) for n in range(base,base+nret)),(expr,)));top=base+nret
      elif k=='returncall':out.append(O('returns',(call(R(a[0]),args(a[0],a[1])),)))
      elif k=='return':
       base,count=a
       if count is None:values=args(base-1,None)
       else:values=[R(n) for n in range(base,base+count)]
       out.append(O('returns',tuple(values)))
      elif k=='vararg':multi=(a[0],('varargs',))
      elif k=='setlist':
       base,start,count=a
       if count is None:raise ValueError('dynamic SETLIST is not supported by this profile')
       values=args(base,count)
       for n,expr in enumerate(values,start+1):out.append(O('set',ix(R(base),K(n)),expr))
      elif k=='for':
       kind,base,body=a
       if kind=='numeric':bindings=(R(base+3),);values=(R(base),R(base+1),R(base+2))
       else:bindings=(R(base+1),R(base+2));values=(R(base),R(base+1),R(base+2))
       out.append(O('loop',kind,bindings,values,lower(body)))
      elif k=='if':out.append(O('if',a[0],lower(a[1]),lower(a[2])))
      elif k=='while':out.append(O('while',lower(a[0])))
      elif k=='clear':
       for n in range(a[0],a[1]+1):out.append(O('set',R(n),K(None)))
      elif k=='set' and a[1][0] in ('varargs','call'):out.append(O('set',a[0],('single',a[1])))
      else:out.append(op)
      if k in ('if','for','while','continue','break','return','returncall'):
       if multi is not None:raise ValueError(('multi at boundary',k,multi))
       top=None
     if multi is not None:raise ValueError(('left multivalue',multi))
     return out

    def expr_nodes(expr):
     if not isinstance(expr,tuple) or not expr:return
     if isinstance(expr[0],str):
      yield expr
      for v in expr[1:]:yield from expr_nodes(v)
     else:
      for v in expr:yield from expr_nodes(v)
    def reads(expr):
     result=Counter(v for v in expr_nodes(expr) if v[0] in ('reg','up','global'))
     for v in expr_nodes(expr):
      if v[0]=='closure':
       for desc in l.functions[v[1]].p[5].values():result[R(desc[3]) if desc[1] in (0,1) else U(desc[3])]+=1
     return result
    def expr_replace(expr,old,new):
     if expr==old:return new
     if not isinstance(expr,tuple):return expr
     return tuple(expr_replace(v,old,new) for v in expr)
    def stmt_exprs(op):
     k=op.kind;a=op.args
     if k=='set':return ([a[0]] if a[0][0]=='index' else [])+[a[1]]
     if k=='assign':return list(a[1])
     if k=='expr':return [a[0]]
     if k=='returns':return list(a[0])
     if k=='if':return [a[0]]
     if k=='loop':return list(a[2])
     return []
    def children(op):
     if op.kind=='if':return [op.args[1],op.args[2]]
     if op.kind=='while':return [op.args[0]]
     if op.kind=='loop':return [op.args[3]]
     return []
    def stmt_reads(op,deep=False):
     result=Counter()
     for expr in stmt_exprs(op):result.update(reads(expr))
     if deep:
      for body in children(op):
       for stmt in body:result.update(stmt_reads(stmt,True))
     return result
    def writes(op,deep=False):
     result=set()
     if op.kind=='set' and op.args[0][0] in ('reg','up','global'):result.add(op.args[0])
     elif op.kind=='assign':result.update(op.args[0])
     elif op.kind=='loop':result.update(op.args[1])
     if deep:
      for body in children(op):
       for stmt in body:result.update(writes(stmt,True))
     return result
    def stmt_replace(op,old,new):
     k=op.kind;a=list(op.args)
     if k=='set':
      if a[0][0]=='index':a[0]=expr_replace(a[0],old,new)
      a[1]=expr_replace(a[1],old,new)
     elif k=='assign':a[1]=expr_replace(a[1],old,new)
     elif k in ('expr','if','returns'):a[0]=expr_replace(a[0],old,new)
     elif k=='loop':a[2]=expr_replace(a[2],old,new)
     return Op(k,tuple(a),op.pc)
    def pure(expr):
     # Arithmetic, comparison, length, global lookup and indexing can invoke
     # metamethods or throw. Do not erase them just because a result is unused.
     return all(v[0] not in ('call','index','methodvalue','table','closure','varargs','binary','global')
                and not (v[0]=='unary' and v[1]!='not') for v in expr_nodes(expr))
    def effect(op):
     if op.kind in ('expr','returns','if','loop','while','break','continue','assign','close'):return True
     if op.kind=='set':return op.args[0][0]!='reg' or not pure(op.args[1])
     return False

    captured=defaultdict(set)
    for child,(parent,pc,dest) in l.functions_parents.items():
     for descr in l.functions[child].p[5].values():
      if descr[1] in (0,1):captured[parent].add(descr[3])

    def simplify(expr):
     if not isinstance(expr,tuple):return expr
     expr=tuple(simplify(v) for v in expr)
     if len(expr)==3 and expr[:2]==('unary','not'):
      inner=expr[2]
      if isinstance(inner,tuple) and inner[:2]==('unary','not'):return inner[2]
      if isinstance(inner,tuple) and inner[0]=='binary' and inner[1] in ('==','~='):
       # Ordered comparisons cannot be inverted this way for NaN values or
       # for arbitrary user-defined comparison metamethods.
       return ('binary',{'==':'~=','~=':'=='}[inner[1]],*inner[2:])
     return expr

    def optimize(seq,index,liveout=frozenset()):
     seq=list(seq)
     live_after={};future=set(liveout)
     for at in reversed(range(len(seq))):
      live_after[at]=set(future)
      future=(future-writes(seq[at]))|set(stmt_reads(seq[at],True))
     for at,op in enumerate(seq):
      a=list(op.args)
      if op.kind=='if':
       a[0]=simplify(a[0]);a[1]=optimize(a[1],index,live_after[at]);a[2]=optimize(a[2],index,live_after[at])
       if not a[1] and a[2]:a=[simplify(('unary','not',a[0])),a[2],[]]
      elif op.kind=='while':a[0]=optimize(a[0],index,live_after[at]|set(stmt_reads(op,True)))
      elif op.kind=='loop':a[3]=optimize(a[3],index,live_after[at]|set(stmt_reads(op,True)))
      seq[at]=Op(op.kind,tuple(a),op.pc)
     for iteration in range(30):
      changed=False
      for i,op in enumerate(seq):
       if op.kind!='set' or op.args[0][0]!='reg':continue
       target,expr=op.args
       if target[1] in captured[index]:continue
       uses=[];total=0;last=len(seq)
       for j in range(i+1,len(seq)):
        count=stmt_reads(seq[j],True)[target]
        if count:uses.append((j,count));total+=count
        # A write in only one branch does not kill the incoming value on the
        # other path (the common `value = argument or default` pattern).
        if seq[j].kind in ('set','assign') and target in writes(seq[j]):last=j;break
       if total==0:
        if target in liveout or target[1] in captured[index]:continue
        if pure(expr):seq[i]=O('noop');changed=True
        elif expr[0]=='call':seq[i]=O('expr',expr);changed=True
        elif expr[0]=='single' and expr[1][0]=='call':seq[i]=O('expr',expr[1]);changed=True
        # Table literals may be discarded only if they cannot be captured.
        elif expr[0]=='table':seq[i]=O('noop');changed=True
        continue
       if total!=1:continue
       if last==len(seq) and (target in liveout or target[1] in captured[index]):continue
       j,count=uses[0]
       if stmt_reads(seq[j],False)[target]!=1:continue
       if not any(target==v for e in stmt_exprs(seq[j]) for v in expr_nodes(e)):continue
       dependencies=set(reads(expr))
       if any(dependencies & writes(v,True) for v in seq[i+1:j]):continue
       if any(v.kind in ('if','while','loop','break','continue','returns') for v in seq[i+1:j]):continue
       # Calls can mutate globals and lexical captures too. Only literal values
       # may move across an observable operation without a state-effect proof.
       if expr[0]!='lit' and any(effect(v) for v in seq[i+1:j]):continue
       seq[j]=stmt_replace(seq[j],target,expr);seq[i]=O('noop');changed=True
      seq=[s for s in seq if s.kind!='noop']
      if not changed:break
     return seq

    def walk_stmts(seq):
     for op in seq:
      yield op
      for body in children(op):yield from walk_stmts(body)

    bodies={i:optimize(lower(seq),i) for i,seq in raw.items()}

    reserved=set('and break do else elseif end false for function if in local nil not or repeat return then true until while continue type export'.split())
    # Stable generated identifiers carry no game-specific hints. Function IDs
    # are used only to avoid accidental shadowing of lexical captures.
    regnames={}
    for i,body in bodies.items():
     regs=set(range(1,l.functions[i].params+1))|captured[i]
     for op in walk_stmts(body):
      regs.update(v[1] for v in stmt_reads(op) if v[0]=='reg')
      regs.update(v[1] for v in writes(op) if v[0]=='reg')
     regnames[i]={reg:f'v{i}_{reg}' for reg in sorted(regs)}

    # A descriptor-0 capture is a mutable cell. Each closure snapshots the cell
    # identity, not its value. CLOSE replaces the parent's cell, leaving closures
    # attached to the closed cell. Descriptor-1 captures snapshot the value.
    mutable=defaultdict(set)
    snapshot_names={};snapshots_by_child=defaultdict(list)
    for child,(parent,pc,dest) in l.functions_parents.items():
     for slot,desc in sorted(l.functions[child].p[5].items()):
      kind,reg=desc[1],desc[3]
      if kind in (0,1):
       name=f'captured{child}_{slot-1}'
       snapshot_names[child,slot-1]=(name,kind)
       snapshots_by_child[child].append((name,parent,reg,kind))
       if kind==0:mutable[parent].add(reg)

    def regref(i,reg):
     name=regnames[i][reg]
     return name+'.value' if reg in mutable[i] else name

    def literal(v):
     if v is None:return 'nil'
     if isinstance(v,bool):return str(v).lower()
     if isinstance(v,bytes):return quote(v)
     if isinstance(v,float) and not math.isfinite(v):return '(0/0)' if math.isnan(v) else '(math.huge)' if v>0 else '(-math.huge)'
     if not isinstance(v,(int,float)):raise ValueError('non-scalar literal is unsupported')
     return str(v)

    def upref(i,index,stack=()):
     if (i,index) in snapshot_names:
      name,kind=snapshot_names[i,index]
      return name+'.value' if kind==0 else name
     parent=l.functions_parents[i][0];desc=l.functions[i].p[5][index+1]
     if desc[1] in (0,1):return regref(parent,desc[3])
     return upref(parent,desc[3])

    def render_expr(e,i,indent=0):
     k=e[0]
     if k=='reg':return regref(i,e[1])
     if k=='up':return upref(i,e[1])
     if k=='lit':return literal(e[1])
     if k=='global':
      return e[1] if re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',e[1]) and e[1] not in reserved else 'getfenv()['+quote(e[1].encode())+']'
     if k=='varargs':return '...'
     if k=='single':return '('+render_expr(e[1],i,indent)+')'
     if k=='table':return '{}'
     if k=='index':
      obj=render_expr(e[1],i,indent);key=e[2]
      if e[1][0] in ('binary','unary','table','closure'):obj='('+obj+')'
      if key[0]=='lit' and isinstance(key[1],bytes):
       name=key[1].decode('utf8','replace')
       if re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',name) and name not in reserved:return obj+'.'+name
      return obj+'['+render_expr(key,i,indent)+']'
     if k=='binary':return '('+render_expr(e[2],i,indent)+' '+e[1]+' '+render_expr(e[3],i,indent)+')'
     if k=='unary':return '('+e[1]+(' ' if e[1]=='not' else '')+render_expr(e[2],i,indent)+')'
     if k=='methodvalue':return render_expr(ix(e[1],e[2]),i,indent)
     if k=='call':
      fn,args=e[1:]
      if fn[0]=='methodvalue' and args and args[0]==fn[1] and fn[2][0]=='lit':
       name=fn[2][1].decode()
       if re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',name):return render_expr(fn[1],i,indent)+':'+name+'('+', '.join(render_expr(x,i,indent) for x in args[1:])+')'
      callee=render_expr(fn,i,indent)
      if fn[0] in ('closure','table','binary','unary'):callee='('+callee+')'
      return callee+'('+', '.join(render_expr(x,i,indent) for x in args)+')'
     if k=='closure':return render_function(e[1],indent)
     raise ValueError(('unknown expr',e))

    def render_body(body,i,indent):
     out=[];pad='    '*indent
     def expr(x):return render_expr(x,i,indent)
     for op in body:
      k=op.kind;a=op.args
      if k=='set':out.append(pad+expr(a[0])+' = '+expr(a[1]))
      elif k=='assign':out.append(pad+', '.join(expr(x) for x in a[0])+' = '+', '.join(expr(x) for x in a[1]))
      elif k=='expr':out.append(pad+expr(a[0]))
      elif k=='returns':out.append(pad+'return'+(' '+', '.join(expr(x) for x in a[0]) if a[0] else ''))
      elif k in ('break','continue'):out.append(pad+k)
      elif k=='close':
       for reg in sorted(mutable[i]):
        if reg>=a[0]:
         name=regnames[i][reg]
         out.append(pad+name+' = {value = '+name+'.value}')
      elif k=='if':
       out.append(pad+'if '+expr(a[0])+' then')
       out.extend(render_body(a[1],i,indent+1))
       if a[2]:out.append(pad+'else');out.extend(render_body(a[2],i,indent+1))
       out.append(pad+'end')
      elif k=='loop':
       kind,bindings,values,loopbody=a
       vals=list(values)
       if kind=='numeric' and vals[-1]==K(1):vals.pop()
       names=[f'loopValue{i}_{x[1]}' if x[1] in mutable[i] else expr(x) for x in bindings]
       out.append(pad+'for '+', '.join(names)+(' = ' if kind=='numeric' else ' in ')+', '.join(expr(x) for x in vals)+' do')
       for binding,name in zip(bindings,names):
        if binding[1] in mutable[i]:out.append(pad+'    '+expr(binding)+' = '+name)
       out.extend(render_body(loopbody,i,indent+1));out.append(pad+'end')
      elif k=='while':
       out.append(pad+'while true do');out.extend(render_body(a[0],i,indent+1));out.append(pad+'end')
      else:raise ValueError(('unknown stmt',k))
     return out

    rendering=set()
    def render_function(i,indent=0,wrap_snapshots=True):
     if wrap_snapshots and snapshots_by_child[i]:
      specs=snapshots_by_child[i];pad='    '*indent
      return '(function('+', '.join(v[0] for v in specs)+')\n'+pad+'    return '+render_function(i,indent+1,False)+'\n'+pad+'end)('+', '.join(regnames[p][reg] if kind==0 else regref(p,reg) for _,p,reg,kind in specs)+')'
     if i in rendering:raise ValueError(('recursive closure?',i))
     rendering.add(i)
     f=l.functions[i];params=[('argument'+str(n)) if n in mutable[i] else regnames[i][n] for n in range(1,f.params+1)]
     if f.vararg:params.append('...')
     names=[name for n,name in regnames[i].items() if n>f.params and n not in mutable[i]]
     lines=['function('+', '.join(params)+')']
     if names:lines.append('    '*(indent+1)+'local '+', '.join(names))
     for reg in sorted(mutable[i]):
      initial='argument'+str(reg) if reg<=f.params else 'nil'
      lines.append('    '*(indent+1)+'local '+regnames[i][reg]+' = {value = '+initial+'}')
     lines.extend(render_body(bodies[i],i,indent+1))
     lines.append('    '*indent+'end')
     rendering.remove(i)
     # A parenthesized receiver at the start of a line must be separated from
     # the previous statement, or Luau parses it as an additional call argument.
     return re.sub(r'(?m)^([ \t]*)\(',r'\1;(','\n'.join(lines))


    return 'return '+render_function(context.root_index)+'\n'
