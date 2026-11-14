"""Qingci two-occurrence candidate: measured native roles, real reusable V02/V03/font primitives."""
import sys,json,math
sys.dont_write_bytecode=True
from pathlib import Path
from functools import lru_cache
import numpy as np
from PIL import Image,ImageDraw,ImageFilter
H=Path(__file__).resolve().parent
from .vendor.apple_minimal import visual,media
from .vendor.apple_minimal.pilot import text_image,font,ease
from .vendor.subtitle_engine.split_title import with_shadow
SIZE=(1080,1920);G=json.loads((H/'data/source-geometry.json').read_text(encoding='utf-8'));EXITS=json.loads((H/'data/source-exits-complete-v2.json').read_text(encoding='utf-8'))
def blank():return Image.new('RGBA',SIZE)
def alpha(im,q):im=im.copy();im.putalpha(im.getchannel('A').point([round(i*max(0,min(1,q))) for i in range(256)]));return im
def out(a,b,n):t=max(0,min(1,(n-a)/(b-a)));return 1-(1-t)**3
@lru_cache(maxsize=1)
def background():
 y=np.linspace(0,1,1920)[:,None,None];top=np.array([220,234,228]);bottom=np.array([165,199,185]);a=np.uint8(np.round(top[None,None,:]*(1-y)+bottom[None,None,:]*y));return Image.fromarray(np.repeat(a,1080,axis=1)).convert('RGBA')
def bg(n,c):
 im=background().copy()
 if str(n) in G['stage']:
  b=G['stage'][str(n)];mask=Image.new('L',SIZE);ImageDraw.Draw(mask).rectangle((b['x'],b['top'],b['right']-1,b['bottom']-1),fill=255);im.putalpha(mask);base=Image.new('RGBA',SIZE,'black');base.alpha_composite(im);return base
 return im
def _first_material(c,n):
 roles={};metrics=[]
 for m in c['materials']:
  if not m['start']<=n<m['end'] and not(c['mode']=='baseline' and n==0 and m['kind']=='street'):continue
  kind=m['kind'];first,last=m['start'],m['end'];op=1
  if c['mode']=='baseline':
   if kind=='street':
    rec=G['street_entry'].get(str(n));rect=rec['xywh'] if rec else [54,114,972,1000];op=rec.get('opacity_fit',1) if rec else 1
   else:
    rec=G['night_entry'].get(str(n));t=max(0,min(1,(n-112)/13));rect=rec['xywh'] if rec else [0,631*(1-t)**3,1080,1920];op=rec['opacity_fit'] if rec else ease(111,121,n)
   if str(n) in EXITS:rect=EXITS[str(n)]['xywh'];op=EXITS[str(n)]['opacity_fit']
  else:
   if kind=='street':
    phase=9+16*max(0,min(1,(n-first)/24));lo=int(phase);hi=min(25,lo+1);mix=phase-lo;a=G['street_entry'][str(max(9,lo))];b=G['street_entry'][str(max(9,hi))];rect=(np.array(a['xywh'])*(1-mix)+np.array(b['xywh'])*mix).tolist();op=a['opacity_fit']*(1-mix)+b['opacity_fit']*mix
   else:
    t=max(0,min(1,(n-first)/24));phase=112+13*t;lo=int(phase);hi=min(125,lo+1);mix=phase-lo
    def entry(k):return G['night_entry'].get(str(k),dict(xywh=[0,631*(1-(k-112)/13)**3,1080,1920],opacity_fit=ease(111,121,k)))
    a=entry(lo);b=entry(hi);rect=(np.array(a['xywh'])*(1-mix)+np.array(b['xywh'])*mix).tolist();op=a['opacity_fit']*(1-mix)+b['opacity_fit']*mix
   # Exit is driven by each actual semantic asset end, with measured shrink+fade table.
   duration=m.get('exit_frames',16)
   if n>=last-duration:
    start=85 if kind=='street' else 184;phase=start+16*max(0,min(1,(n-(last-duration))/duration));lo=min(start+16,int(phase));hi=min(start+16,lo+1);mix=phase-lo;a=EXITS[str(lo)];b=EXITS[str(hi)];rect=(np.array(a['xywh'])*(1-mix)+np.array(b['xywh'])*mix).tolist();op=a['opacity_fit']*(1-mix)+b['opacity_fit']*mix
  x,y,w,h=rect;entry=dict(id=m['id'],path=m['path'],type=m.get('media_type','image'),start_frame=0,source_in=0,end_policy='hold',fit='cover' if c['mode']=='baseline' else 'contain',rect=[x/2,y/2,(x+w)/2,(y+h)/2],radius=11 if kind=='street' else 18,entry_frames=0,entry_blur=0,audio='muted');layers=media.render('V03',None,n,dict(size=list(SIZE),fps=25,media_entries=[entry]));im=next(iter(layers.values()))
  roles[m['id']]=alpha(im,op);metrics.append(dict(id=m['id'],rect=[float(v) for v in rect],opacity=float(op)))
 return roles,metrics
def _first_person_rect(c,n):
 if c['mode']=='baseline':return G['poses'][str(n)]
 large=np.array([64,230,952,1422.]);rect=large.copy()
 for m in c['materials']:
  if m['kind']=='street':target=np.array([288,1158,504,380.]);q=out(m['start'],m['start']+24,n)*(1-out(m['end'],m['end']+10,n))
  else:target=np.array([706,274,310,410.]);q=out(m['start'],m['start']+24,n)*(1-out(m['end'],m['end']+15,n))
  if q>0:rect=rect*(1-q)+target*q
 return rect.tolist()
def _base_presenter(c,n):
 raw=_source_sample(c,n);assert raw is not None;rect=person_rect(c,n);x,y,w,h=rect
 if c['mode']=='baseline':
  # Recover only source-window interior; preserve pixel-scale face and park backdrop.
  inset=5;crop=[round(x+inset),round(y+inset),round(x+w-inset),round(y+h-inset)];texture=raw.crop(crop);target=[x+inset,y+inset,w-2*inset,h-2*inset]
 else:
  # Natural aspect cover from clean portrait; no old source repairs or pixels.
  ratio=w/h;rw,rh=raw.size
  if rw/rh>ratio:ww=rh*ratio;crop=[(rw-ww)/2,0,(rw+ww)/2,rh]
  else:hh=rw/ratio;cy=rh*(.33 if w>400 and h<600 else .47);top=max(0,min(rh-hh,cy-hh/2));crop=[0,top,rw,top+hh]
  texture=raw.crop(tuple(round(v) for v in crop));target=rect
 xx,yy,ww,hh=target;r=34 if w>400 and h<500 else 20;pose=dict(time=0,matrix=[[ww/1080,0,xx/2],[0,hh/1920,yy/2]],rect=[xx/2,yy/2,(xx+ww)/2,(yy+hh)/2],radius=max(1,r-5)/2,background_opacity=0);im=visual.render('V02',texture,0,dict(size=list(SIZE),fps=25,stage_color=[0,0,0],visual_keys=[pose]))['presenter']
 shape=Image.new('L',SIZE);ImageDraw.Draw(shape).rounded_rectangle((round(x),round(y),round(x+w),round(y+h)),radius=r,fill=255);glow=Image.new('RGBA',SIZE,'white');glow.putalpha(shape.filter(ImageFilter.GaussianBlur(19)).point([round(v*.9) for v in range(256)]));border=blank();ImageDraw.Draw(border).rounded_rectangle((round(x),round(y),round(x+w),round(y+h)),radius=r,outline=(119,134,131,245),width=3);glow.alpha_composite(border)
 return im,glow,dict(rect=rect,source_crop=crop,source_recovery=c['mode']=='baseline',edge_inset_source_pixels=5 if c['mode']=='baseline' else 0,not_human_segmentation=True)
@lru_cache(maxsize=512)
def tile(text,path,size,fill,stroke,edge):return text_image(text,path,size,fill,stroke,edge)
def put(layer,text,path,size,fill,stroke,edge,x,baseline,shadow=False):
 im,bb,pad=tile(text,path,size,fill,stroke,edge)
 if shadow:im=with_shadow(im,dict(shadowX=2,shadowY=2,shadowBlur=1))
 layer.alpha_composite(im,(round(x+bb[0]-pad),round(baseline+bb[1]-pad)))
def titles(c,n):
 a,b=c['title_events']['entry'];e,f=c['title_events']['exit'];warm=c['mode']=='baseline' and n==0;q=1 if warm else ease(a-1,b,n)*(1-ease(e,f,n));board=blank();main=blank();support=blank();path=c['fonts']['title']
 if n>=f:return dict(title_plate=board,title=main,support=support)
 if c['title'].strip():
  size=100;tw=font(path,size).getlength(c['title']);assert tw<1000;w=tw+60;x=(1080-w)/2;ImageDraw.Draw(board).rectangle((round(x),100,round(x+w),236),fill=(255,194,3,255),outline=(15,15,10,255),width=6)
  outer=blank();put(outer,c['title'],path,size,(255,255,250,255),8,(7,7,7,255),(1080-tw)/2,213);inner=blank();put(inner,c['title'],path,size,(12,12,12,255),4,(255,255,250,255),(1080-tw)/2,213);outer.alpha_composite(inner);main=alpha(outer,q)
 if c['support'].strip():
  size=78
  while font(path,size).getlength(c['support'])>940:size-=1
  tw=font(path,size).getlength(c['support']);outer=blank();put(outer,c['support'],path,size,(237,152,32,255),6,(38,30,24,255),(1080-tw)/2,329);inner=blank();put(inner,c['support'],path,size,(46,36,23,255),3,(248,164,47,255),(1080-tw)/2,329);outer.alpha_composite(inner);support=alpha(outer,q)
  # Independent yellow line exists in frame1 before support letters.
  d=ImageDraw.Draw(board)
  if c['mode']=='baseline' and n==1:d.rectangle((208,276,870,302),fill=(255,194,3,255))
  else:d.rectangle((max(15,round((1080-tw)/2-28)),281,max(20,round((1080-tw)/2-12)),299),fill=(255,194,3,255));d.rectangle((min(1060,round((1080+tw)/2+12)),281,min(1075,round((1080+tw)/2+28)),299),fill=(255,194,3,255))
 board=alpha(board,1-ease(e,f,n));return dict(title_plate=board,title=main,support=support)
def identity(c,n):
 v=c['name_card'];name=v.get('name','').strip();desc=v.get('description','').strip();im=blank()
 if not v.get('enabled') or not(name or desc):return im
 assert len(name)<=4,'Vertical supplied name supports at most4 glyphs in tested geometry'
 a,b=c['identity_events']['entry'];e,f=c['identity_events']['exit'];exitq=1-ease(e,f,n);warm=c['mode']=='baseline' and n==0;path=c['fonts']['body']
 for i,ch in enumerate(name):
  layer=blank();put(layer,ch,path,64,(255,255,250,255),1,(160,160,145,230),98,1127+i*64,True);q=1 if warm else ease(a+3*i-1,b+3*i,n);im.alpha_composite(alpha(layer,q))
 if desc:
  lay=blank();put(lay,desc,path,40,(255,255,250,255),0,(0,0,0,0),205 if name else 98,1182 if name else 1135,True);im.alpha_composite(alpha(lay,1 if warm else ease(a,b,n)))
 d=ImageDraw.Draw(im);d.rectangle((76,1068,80,1068+max(64,len(name)*64)),fill=(255,219,40,round(255*(1 if warm else ease(a-1,b,n)))));return alpha(im,exitq)
def caption(c,n):
 layer=blank();layouts=[]
 row=next((r for r in c['captions'] if r['range'][0]<=n<r['range'][1]),None)
 if not row:return layer,layouts
 style=c.get('caption_style',{});gap=style.get('line_gap',90);anchor=style.get('baseline',1655);chars=list(row['text']);emph=[any(a<=i<b for a,b in row['emphasis_spans']) for i in range(len(chars))];sizes=[style.get('emphasis_size',90) if e else style.get('body_size',76) for e in emph];path=c['fonts']['body'];adv=[font(path,s).getlength(ch) for ch,s in zip(chars,sizes)];edges=[0]+row.get('line_breaks',[])+[len(chars)];widths=[sum(adv[a:b]) for a,b in zip(edges,edges[1:])];assert max(widths)<=1035,(row['text'],widths);line=0;x=(1080-widths[0])/2;baseline=anchor-gap*(len(widths)-1)
 for i,(ch,size,step,first,e) in enumerate(zip(chars,sizes,adv,row['glyph_firsts'],emph)):
  if i in edges[1:-1]:line+=1;x=(1080-widths[line])/2;baseline+=gap
  q=ease(first-.25,min(first+style.get('glyph_entry_frames',5),math.ceil(row['range'][1])-1) if c['mode']!='baseline' else first+style.get('glyph_entry_frames',5),n)
  if q>0:
   glyph=blank();put(glyph,ch,path,size,tuple(style.get('emphasis_fill',[255,218,54,255])) if e else tuple(style.get('body_fill',[255,248,229,255])),style.get('stroke',4),(44,34,25,255),x,baseline,style.get('shadow',True))
   # Fixed complete-line cursor; only this glyph's opacity/vertical growth changes.
   if q<1:
    start=style.get('grow_from',.87);scale=start+(1-start)*q;box=glyph.getchannel('A').getbbox()
    if box:
     part=glyph.crop(box);part=part.resize((part.width,max(1,round(part.height*scale))),Image.Resampling.BICUBIC);glyph=blank();glyph.alpha_composite(part,(box[0],round(baseline-(baseline-box[1])*scale)))
   layer.alpha_composite(alpha(glyph,q))
  layouts.append(dict(index=i,char=ch,first=first,x=x,advance=step,size=size,emphasis=e));x+=step
 return layer,dict(id=row['id'],line_widths=widths,baseline=baseline,glyphs=layouts,no_cursor=True,fixed_line_anchor=True)
def _base_render_layers(c,n):
 materials,mm=material(c,n);person,frame,pm=presenter(c,n);cap,cm=caption(c,n);roles=dict(background=bg(n,c),materials=blank(),frame=frame,presenter=person,**titles(c,n),identity=identity(c,n),caption=cap)
 for im in materials.values():roles['materials'].alpha_composite(im)
 # White external glow lies behind the moving original-background window.
 return roles,dict(frame=n,PTS=n/25,materials=mm,presenter=pm,caption=cm,identity_provided=c['name_card'],source_repair='static-night-only boundedmask' if c['mode']=='baseline' else None)
def composite(roles):
 im=blank()
 for layer in roles.values():im.alpha_composite(layer)
 return im.convert('RGB')

def _source_sample(c,n):
 raw=media._sample(dict(path=c['source'],start_frame=0,source_in=0,end_policy='hold'),n,25).convert('RGB')
 if c['mode']!='baseline' or n<204:return raw
 # Source-only bounded glyph repair; hidden shirt/background texture is unknown.
 import cv2
 arr=np.array(raw);support=np.array(caption(c,n)[0].getchannel('A'))
 support=cv2.dilate((support>1).astype(np.uint8),np.ones((17,17),np.uint8))
 color=arr.astype(int);neutral=(color.max(2)-color.min(2)<75)&(color.min(2)>60);yellow=(color[:,:,0]>120)&(color[:,:,1]>90)&(color[:,:,2]<150)
 mask=(support.astype(bool)&(neutral|yellow)).astype(np.uint8)*255;mask=cv2.dilate(mask,np.ones((7,7),np.uint8))
 cleaned=cv2.inpaint(arr,mask,4,cv2.INPAINT_TELEA) if mask.any() else arr
 repair=c.get('repair_dir')
 if repair and n in [216,224,285,313,369,405,500]:
  root=Path(repair);root.mkdir(parents=True,exist_ok=True);Image.fromarray(mask).save(root/f'f{n:04}-mask.png');Image.fromarray(np.abs(arr.astype(int)-cleaned.astype(int)).astype(np.uint8)).save(root/f'f{n:04}-diff.png')
 return Image.fromarray(cleaned)

def material(c,n):
 ordinary=dict(c,materials=[x for x in c['materials'] if x['kind'] in ['street','night']]);roles,metrics=_first_material(ordinary,n)
 for m in c['materials']:
  if m['kind'] in ['street','night'] or not m['start']<=n<m['end']:continue
  a,b=m['start'],m['end'];kind=m['kind'];q=ease(a-1,a+14,n);exitq=1-ease(b-10,b,n)
  if kind=='book':
   rect=[92,270,896,672]
   sibling=next((v for v in c['materials'] if v['kind']=='window' and a<v['start']<b),None)
   if sibling:
    t=ease(sibling['start']-3,sibling['start']+16,n);rect=[92+6*t,270-146*t,896-12*t,672-8*t]
  elif kind=='window':rect=[98,834,884,256]
  else:rect=[54,114,972,1000]
  x,y,w,h=rect;entry=dict(id=m['id'],path=m['path'],type=m.get('media_type','image'),start_frame=m.get('source_start_frame',0),source_in=0,end_policy='hold',fit='cover' if c['mode']=='baseline' else 'contain',rect=[x/2,y/2,(x+w)/2,(y+h)/2],radius=15,entry_frames=0,entry_blur=0,audio='muted')
  layer=next(iter(media.render('V03',None,n,dict(size=list(SIZE),fps=25,media_entries=[entry])).values()))
  if kind in ['book','window']:
   reveal=Image.new('L',SIZE);draw=ImageDraw.Draw(reveal)
   if kind=='book':draw.rectangle((round(x),round(y),round(x+w*q),round(y+h*q)),fill=255)
   else:draw.polygon([(round(x+w*(1-q)),round(y)),(round(x+w),round(y)),(round(x+w),round(y+h*q)),(round(x+w*(1-q)),round(y+h*q*.82))],fill=255)
   from PIL import ImageChops
   layer.putalpha(ImageChops.multiply(layer.getchannel('A'),reveal));layer=alpha(layer,exitq)
  else:layer=alpha(visual._blur_alpha(layer,12*(1-q)),q*exitq)
  roles[m['id']]=layer;metrics.append(dict(id=m['id'],rect=rect,opacity=q*exitq,mechanism=kind))
 return roles,metrics

def person_rect(c,n):
 if c['mode']=='baseline':return G['poses'][str(n)]
 large=np.array([64,230,952,1422.]);rect=large.copy()
 for m in c['materials']:
  target=np.array([706,274,310,410.]) if m['kind']=='night' else np.array([288,1158,504,380.])
  q=out(m['start'],m['start']+24,n)*(1-out(m['end'],m['end']+15,n))
  if q>0:rect=rect*(1-q)+target*q
 return rect.tolist()

def presenter(c,n):return _base_presenter(c,n)

def render_layers(c,n):
 roles,meta=_base_render_layers(c,n)
 if n>=c.get('fade_start',10**9):
  q=max(0,min(1,(c['black_at']-n)/max(1,c['black_at']-c['fade_start'])))
  # Reference presenter already carries its native RGB fade; do not double it.
  for key,im in roles.items():
   if c['mode']=='baseline' and key=='presenter':continue
   arr=np.array(im);arr[:,:,:3]=np.round(arr[:,:,:3].astype(float)*q).astype(np.uint8);roles[key]=Image.fromarray(arr)
 if n>=c.get('black_at',10**9):roles={key:blank() for key in roles}
 return roles,meta
