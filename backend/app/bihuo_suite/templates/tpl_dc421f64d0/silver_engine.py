"""Portable Silver renderer: frozen visual mathematics, clean-source input only."""
from pathlib import Path
import sys,json,hashlib
from functools import lru_cache
import numpy as np,cv2
from PIL import Image,ImageDraw,ImageFilter,ImageChops
sys.dont_write_bytecode=True
from .vendor.apple_minimal import visual,media
from .vendor.apple_minimal.pilot import text_image,font,place_center,ease
from .vendor.subtitle_engine.split_title import split_rgba,with_shadow
H=Path(__file__).resolve().parent
MODEL=json.loads((H/'data/source-model.json').read_text(encoding='utf-8'))
STAGE=json.loads((H/'data/stage-fit.json').read_text(encoding='utf-8'))
COUPLING=json.loads((H/'data/coupling.json').read_text(encoding='utf-8'))
SIZE=(1080,1920)

def blank():return Image.new('RGBA',SIZE)

def pixel_sha(im):return hashlib.sha256(im.tobytes()).hexdigest()

def dim_rgb(im,q):
 arr=np.array(im);arr[:,:,:3]=np.clip(arr[:,:,:3].astype(float)*q,0,255).round().astype(np.uint8);return Image.fromarray(arr)

def fade(im,q):
 im=im.copy();im.putalpha(im.getchannel('A').point([round(v*max(0,min(q,1))) for v in range(256)]));return im

@lru_cache(maxsize=1)
def stage():
 y=np.arange(1920)[:,None];row=np.clip(y*np.array(STAGE['slope'])+np.array(STAGE['intercept']),0,255).round().astype(np.uint8);arr=np.broadcast_to(row[:,None,:],(1920,1080,3)).copy();return Image.fromarray(arr).convert('RGBA')

def source_opacity(n):return next((r['opacity_candidate'] for r in MODEL['global_fade'] if r['frame']==n),1.)

def global_opacity(cfg,n):
 if cfg['mode']=='baseline':return source_opacity(n)
 phase=n-cfg['fade_start']+338
 return source_opacity(phase) if n>=cfg['fade_start'] else 1.

def outer(cfg,n):
 phase=n-cfg['outer_start']+322
 if not 322<=phase<=338:return np.array([[1.,0,0],[0,1.,0]],np.float32)
 row=next(r for r in COUPLING['frames'] if r['frame']==phase);M=np.array(row['same_glyph_affine']['matrix_template_roi_to_current_roi'],np.float32);origin=np.array(COUPLING['roi_xyxy'][:2]);M[:,2]+=origin-M[:,:2]@origin;return M

def warp(im,M):
 arr=np.asarray(im.convert('RGBa'));out=cv2.warpAffine(arr,M,SIZE,flags=cv2.INTER_CUBIC,borderMode=cv2.BORDER_CONSTANT,borderValue=(0,0,0,0));return Image.fromarray(out,'RGBa').convert('RGBA')

def rect(cfg,n):
 phase=n-cfg['handoff']+221
 if phase<231:return [0,0,1080,1920]
 if phase>=250:return cfg['close_rect']
 row=next(r for r in MODEL['window_geometry'] if r['frame']==phase);x,y,_,_=row['xywh'];y=min(228,y);return [x,y,1080-2*x,round(1920-y*(1+266/228))]

def presenter(tex,box,radius=28):
 x,y,w,h=box;pose=dict(time=0,matrix=[[1,0,0],[0,1,0]],rect=[x/2,y/2,(x+w)/2,(y+h)/2],radius=radius/2 if w<1080 else 0,background_opacity=0);return visual.render('V02',tex,0,dict(size=list(SIZE),fps=25,stage_color=[0,0,0],visual_keys=[pose]))['presenter']

@lru_cache(maxsize=200)
def glyph(text,path,size,fill,stroke,edge):return text_image(text,path,size,fill,stroke,edge)

def _single_whole_line(cfg,c):
 layer=blank();parts=visual.caption_parts(c);width=sum(font(cfg['fonts']['caption'],cfg['gold_size'] if e else cfg['white_size']).getlength(text) for text,e in parts);assert width<=1030,(c['text'],width);x=(1080-width)/2
 for text,e in parts:
  size=cfg['gold_size'] if e else cfg['white_size'];im,b,pad=glyph(text,cfg['fonts']['caption'],size,(255,214,0,255) if e else(255,255,255,255),1,(15,15,15,210));baseline=cfg['baseline_gold'] if e else cfg['baseline_white'];layer.alpha_composite(im,(round(x+b[0]-pad),round(baseline+b[1]-pad)));x+=font(cfg['fonts']['caption'],size).getlength(text)
 box=layer.getchannel('A').getbbox();return (with_shadow(layer,dict(shadowX=3,shadowY=4,shadowBlur=2)) if cfg.get('shadow_enabled',True) else layer),dict(text=c['text'],advance_width=width,ink_xyxy=box,body_size=cfg['white_size'],emphasis_size=cfg['gold_size'],single_line_natural_proportions=True)

def caption_layers(cfg,n):
 roles={};layout=[];cues=cfg['captions']
 if cfg['mode']=='baseline' and n==0:cues=[dict(cues[0],first=0,settle=0,gone=1,exit=1,split=None)]
 for i,c in enumerate(cues):
  if not c['first']<=n<c['gone']:continue
  im,info=whole_line(cfg,c);op=1.;scale=1.
  if n<c['settle']:
   op=ease(c['first']-1,c['settle'],n)
   if 'scale' in c['entry_mode']:scale=.45+.55*op
  if scale!=1:im=warp(im,np.array([[scale,0,540*(1-scale)],[0,scale,1630*(1-scale)]],np.float32))
  im=fade(im,op);split=c['split']
  if split is not None and n>=split:
   phase=min(n-split,5);distance=cfg['split_distance']*MODEL['split_curve']['distance_by_phase'][phase]/50;im=fade(im,MODEL['split_curve']['opacity_by_phase'][phase]);up,lo=split_rgba(im,1630,dy=distance);roles[f'cue{i}-upper']=up;roles[f'cue{i}-lower']=lo;info.update(dict(split=True,distance=distance,cut_y=1630))
  else:
   if n>=c['exit'] and 'crossfade' in c['exit_mode']:im=fade(im,.5)
   roles[f'cue{i}-body']=im;info['split']=False
  layout.append(info)
 return roles,layout

def header(cfg,n):
 layer=blank();a,b=cfg['title_exit'];q=(1-ease(a-1,b,n))*ease(cfg['title_entry'][0]-1,cfg['title_entry'][1],n)
 if cfg['mode']=='baseline' and n==0:q=1
 if q<=0 or not cfg['title']:return layer
 im,bb,pad=glyph(cfg['title'],cfg['fonts']['title'],cfg['title_size'],(255,255,255,255),8,(51,56,0,255));ink=im.getchannel('A').getbbox();im=with_shadow(im,dict(shadowX=2,shadowY=3,shadowBlur=1.5));place_center(layer,im,540,cfg['title_top']-ink[1],q);return layer

def identity(cfg,n):
 out=blank();card=cfg['identity'];name=card.get('name','');desc=card.get('description','')
 if not card.get('enabled') or not(name or desc):return out
 leave=1-ease(cfg['identity_exit'][0]-1,cfg['identity_exit'][1],n);entry=ease(1,9,n)
 if cfg['mode']=='baseline' and n==0:leave=entry=1
 d=ImageDraw.Draw(out);q=entry*leave
 if q<=0:return out
 line_end=1075+(max(60,61*len(name)) if name else 34)
 d.line((77,1075,77,line_end),fill=(255,221,0,round(255*q)),width=4)
 for i,ch in enumerate(name):
  im,bb,pad=glyph(ch,cfg['fonts']['caption'],64,(255,255,255,255),0,(0,0,0,0));first=2+i*3;op=ease(first-1,first+4,n)*leave
  if cfg['mode']=='baseline' and n==0:op=1
  im=with_shadow(im,dict(shadowX=1,shadowY=2,shadowBlur=1));out.alpha_composite(fade(im,op),(round(100+bb[0]-pad),round(1075+i*61-pad)))
 if desc:
  im,b,pad=glyph(desc,cfg['fonts']['caption'],30,(255,255,255,255),0,(0,0,0,0));im=with_shadow(im,dict(shadowX=1,shadowY=2,shadowBlur=1));out.alpha_composite(fade(im,q),(round((184 if name else 100)+b[0]-pad),round((1075+61*len(name)-29 if name else 1075)-pad)))
 return out

def merge(roles):
 out=blank()
 for im in roles.values():out.alpha_composite(im)
 return out

def render_layers(cfg,n,save_repair=False):
 source=cfg['mode']=='baseline';M=outer(cfg,n);phase=n-cfg['handoff']+221;box=rect(cfg,n);opacity=global_opacity(cfg,n);captions,layout=caption_layers(cfg,n);graphics=dict(header=header(cfg,n),identity=identity(cfg,n),**captions)
 if source:raise ValueError('Source baseline uses separately bound legacy lossless layer resources; portable input must be clean')
 else:
  raw=media._sample(dict(path=cfg['source'],start_frame=0,source_in=0,end_policy='hold'),n,25).convert('RGB');tex=raw
  if phase>=221:
   q=ease(220,231,phase);crop=np.array([0,0,1080,1920])*(1-q)+np.array(cfg['close_crop'])*q;close=raw.crop(tuple(round(x) for x in crop));x,y,w,h=box;fit=media._fit(close.convert('RGBA'),w,h,dict(fit='cover',anchor=[.5,.5]));tex=Image.new('RGB',SIZE);tex.paste(fit.convert('RGB'),(x,y))
  meta=dict(frame=n,clean_raw=True,source_crop=cfg['close_crop'] if phase>=231 else[0,0,1080,1920],person_rect=box,no_reference_source_pixels=True)
 bg=stage().copy() if phase>=231 else blank();person=presenter(tex,box)
 if not source and phase>=231:
  d=ImageDraw.Draw(person);x,y,w,h=box;d.rounded_rectangle((x,y,x+w,y+h),radius=28,outline=(115,117,124,200),width=2)
 if 221<=phase<=230:
  b=next(row for row in MODEL['whole_blur'] if row['frame']==phase);shift=np.array([[1.,0,0],[0,1.,b['dy_candidate']]],np.float32)
  if not source:person=visual._blur_alpha(warp(person,shift),b['radius_candidate'])
  graphics={k:visual._blur_alpha(warp(v,shift),b['radius_candidate']) for k,v in graphics.items()}
 if cfg['outer_start']<=n<=cfg['outer_start']+16:person=warp(person,M);graphics={k:warp(im,M) for k,im in graphics.items()}
 if opacity<1:bg=dim_rgb(bg,opacity);person=dim_rgb(person,opacity);graphics={k:dim_rgb(im,opacity) for k,im in graphics.items()}
 if n>=cfg['black_at']:bg=blank();person=blank();graphics={k:blank() for k in graphics}
 meta.update(dict(caption_layout=layout,outer_matrix=M.tolist(),stage_rotates=False,global_opacity=opacity,source_blur_profile_phase=phase if 221<=phase<=230 else None));return dict(background=bg,presenter=person,graphics=merge(graphics)),meta

def composite(roles):
 out=Image.new('RGBA',SIZE,(0,0,0,255))
 for im in roles.values():out.alpha_composite(im)
 return out.convert('RGB')


def whole_line(cfg,c):
 lines=c.get('lines') or [dict(text=c['text'],emphasis_spans=c.get('emphasis_spans',[]))]
 if len(lines)==1:return _single_whole_line(cfg,dict(c,**lines[0]))
 out=blank();info=[]
 for i,line in enumerate(lines):
  local=dict(cfg);shift=(i-.5)*106;local['baseline_white']+=shift;local['baseline_gold']+=shift
  im,meta=_single_whole_line(local,dict(c,**line));out.alpha_composite(im);info.append(meta)
 return out,dict(text=c['text'],lines=info,ink_xyxy=out.getchannel('A').getbbox(),single_line_natural_proportions=False)
