"""New-input whole-frame return revision. Original r1 code and outputs preserved.
Uses the same pinned V02 sampler, V03 fit and project-local measured roles.
"""
from pathlib import Path
import sys
from functools import lru_cache
import numpy as np
from PIL import Image,ImageFilter
from . import teal_engine as base
old_pose=base.person_box;old_person=base.person
def large_weight(cfg,t):
 box=old_pose(cfg,t);width=box[2]-box[0];small=291 if t<cfg['information']['start']-.28 else 491
 return max(0,min(1,(width-small)/(850-small)))
def person_box(cfg,t):
 box=np.array(old_pose(cfg,t),float);weight=large_weight(cfg,t)
 return (box+np.array([-115,24,115,120])*weight).tolist()
_glows={}
def person(frame,t,cfg):
 x,y,x2,y2=box=person_box(cfg,t);w=x2-x;h=y2-y;weight=large_weight(cfg,t)
 texture=base.M._fit(frame.convert('RGBA'),round(w),round(h),dict(fit='cover',anchor=[.5,.35])).resize((1080,1920),Image.Resampling.LANCZOS)
 key=dict(time=0,matrix=[[w/1080,0,x/2],[0,h/1920,y/2]],rect=[x/2,y/2,x2/2,y2/2],radius=15*(1-weight),background_opacity=0)
 layer=base.V.render('V02',texture,0,dict(size=[1080,1920],fps=25,stage_color=[5,14,12],visual_keys=[key]))['presenter']
 if weight>=1:glow=base.blank()
 else:
  sig=tuple(round(v,5) for v in box)
  if sig not in _glows:
   if len(_glows)>=8:_glows.pop(next(iter(_glows)))
   _glows[sig]=old_person(frame,t,cfg)[1]
  glow=base.fade(_glows[sig],1-weight)
 return layer,glow
base.person_box=person_box;base.person=person
def render_layers(frame,t,cfg):
 layers=base.render_layers(frame,t,cfg);weight=large_weight(cfg,t)
 if weight:
  # Original-background source provides the actual fill. No reference pixels or repair are loaded.
  bg=base.M._fit(frame.convert('RGBA'),1080,1920,dict(fit='cover',anchor=[.5,.35])).filter(ImageFilter.GaussianBlur(45));layers['background'].alpha_composite(base.fade(bg,weight))
 return layers
blank=base.blank;composite=base.composite;match=base.match
