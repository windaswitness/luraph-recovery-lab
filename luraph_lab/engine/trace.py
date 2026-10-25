"""Bounded abstract branch-trace checks, not a proof of runtime equivalence."""
from collections import Counter
from . import lift as l

class Trace:
 def __init__(self,seed):self.seed=seed;self.visits=Counter();self.out=[];self.steps=0
 def choice(self,pc,loop=False):
  visit=self.visits[pc];self.visits[pc]+=1
  # Stable choices per original conditional, independently of emission order.
  v=((pc*2654435761 + self.seed*104729 + visit*2246822519)&0xffffffff)
  answer=(v^(v>>7)^(v>>15))%3!=0
  if loop and visit%4==3:answer=False
  self.out.append((pc,'branch',answer))
  return answer
 def tick(self):
  self.steps+=1
  if self.steps>10000:raise RuntimeError('budget')
 def record(self,op):self.out.append((op.pc,op.kind))

def original(f,seed):
 t=Trace(seed);pc=f.entry
 try:
  while pc!=-1:
   t.tick();body,term=f.nodes[pc]
   for op in body:t.record(op)
   a=term.args
   if term.kind=='next':pc=a[0]
   elif term.kind=='branch':pc=a[1] if a[1]==a[2] or t.choice(pc) else a[2]
   elif term.kind=='forprep':pc=a[1]
   elif term.kind=='forstep':pc=a[1] if t.choice(pc,True) else a[2]
   else:t.record(term);break
 except RuntimeError:t.out.append(('budget',))
 return t.out

def structured(f,body,seed):
 t=Trace(seed)
 def run(seq):
  for op in seq:
   t.tick();k=op.kind;a=op.args
   if k=='if':
    decision=t.choice(op.pc)
    orig=f.nodes[op.pc][1].args[0]
    assert a[0]==orig or a[0]==l.neg(orig),(f.index,op.pc,a[0],orig)
    if a[0]!=orig:decision=not decision
    signal=run(a[1] if decision else a[2])
    if signal:return signal
   elif k=='for':
    step=f.loops[op.pc][0]
    while t.choice(step,True):
     signal=run(a[2])
     if signal=='return':return signal
     if signal=='break':break
   elif k=='while':
    while True:
     t.tick();signal=run(a[0])
     if signal=='return':return signal
     if signal=='break':break
   elif k in ('continue','break'):return k
   elif k.startswith('return'):t.record(op);return 'return'
   else:t.record(op)
  return None
 try:run(body)
 except RuntimeError:t.out.append(('budget',))
 return t.out


def check(function, body, seeds=30):
    for seed in range(seeds):
        before = original(function, seed)
        after = structured(function, body, seed)
        if before != after:
            at = next((i for i, pair in enumerate(zip(before, after)) if pair[0] != pair[1]), min(len(before), len(after)))
            return {"seed": seed, "at": at, "original": before[max(0, at-3):at+5], "structured": after[max(0, at-3):at+5]}
    return None
