"""Bounded evaluator for observed instruction-column rewrite islands."""
def resolve(p,start):
 r={0:None};pc=start+1;writes={};steps=[]
 def get(t,k):
  if isinstance(t,tuple) and t[0]=='col':return writes.get((t[1],int(k)),p[t[1]].get(int(k)))
  if t==('proto',):return ('col',k) if isinstance(p[k],dict) else p[k]
  raise ValueError('unknown get')
 def put(t,k,v):
  if not isinstance(t,tuple) or t[0]!='col':raise ValueError('external write')
  if t[1] not in [2,8,9,11]:raise ValueError('noncode write')
  writes[t[1],int(k)]=v
 for _ in range(150):
  if not start<pc<=start+150:raise ValueError('escape')
  vals={col:writes.get((col,pc),p[col].get(pc)) for col in (1,2,3,6,8,9,11)}
  k,a,m,k2,b,op,c=[vals[col] for col in (1,2,3,6,8,9,11)]
  steps.append(pc)
  if op==10:r[c]=('col',9)
  elif op==76:r[b]=('col',2)
  elif op==34:r[c]=('col',11)
  elif op==112:r[c]=('col',8)
  elif op==119:r[b]=('proto',)
  elif op==61:r[a]=k
  elif op==84:r[c]=r[a]
  elif op==99:r[b]=r[c]+m
  elif op==21:r[c]=m+r[b]
  elif op==111:r[a]=r[b]+r[c]
  elif op==71:r[b]=r[c]-m
  elif op==106:r[a]=r[c]-r[b]
  elif op==53:r[c]=m-r[b]
  elif op==30:r[a]=k*r[b]
  elif op==19:r[c]=r[b]*m
  elif op==103:r[c]=r[b]*r[a]
  elif op==3:r[a]=r[b]/r[c]
  elif op==105:r[b]=r[a]/k
  elif op==108:r[a]=r[c]%k2
  elif op==93:r[c]=r[b]%r[a]
  elif op==81:put(r[c],k2,m)
  elif op==57:put(r[a],k2,r[c])
  elif op==14:put(r[b],r[a],k)
  elif op==97:put(r[c],r[b],r[a])
  elif op==2:r[a]=get(r[b],k)
  elif op==1:r[b]=get(r[a],r[c])
  elif op==39:pc=int(b)+1;continue
  elif op==73:pass
  elif op==50:
   if not writes:raise ValueError('no writes')
   return writes,pc,steps
  else:raise ValueError('opcode '+str(op))
  pc+=1
 raise ValueError('budget')
