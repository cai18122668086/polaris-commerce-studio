import sys,json
sys.dont_write_bytecode=True
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFilter,ImageFont
from .vendor.apple_minimal import visual as V,media as M
from .vendor.apple_minimal.pilot import text_image,font,ease
from .vendor.subtitle_engine.split_title import split_rgba
from .vendor import approved_window_math as AV
O=Path(__file__).resolve().parent/'data'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def empty():return Image.new('RGBA',(1080,1920))
def sample(p,n):return M._sample(dict(path=str(p),start_frame=0,end_policy='hold'),n,25).convert('RGB')

from functools import lru_cache
import cv2,math
ROLES=['background','poster_blur','poster_sharp','window_glow','presenter_window','window_edge','title_shadow','title_body','zh_shadow','zh_current','zh_old_upper','zh_old_lower','en_shadow','en_current','en_old']
def norm(im):
 a=np.array(im);a[a[:,:,3]==0,:3]=0;return Image.fromarray(a)
def fade(im,q):return AV.fade(im,q)
def interp(keys,n):return np.asarray(AV.lerp(keys,n),float)
@lru_cache(maxsize=32)
def ink(text,path,size):
 t=text_image(text,path,size,(255,255,255,255))[0];return t.crop(t.getchannel('A').getbbox())
def textpair(text,path,size,top,stroke=2,color=(6,9,15,255),cx=540):
 layer=empty();back=empty()
 if not text:return layer,back
 t=ink(text,path,size);layer.alpha_composite(t,(round(cx-t.width/2),round(top)));a=layer.getchannel('A');aa=cv2.dilate(np.asarray(a),cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(2*stroke+1,2*stroke+1)));back=Image.new('RGBA',(1080,1920),color);back.putalpha(Image.fromarray(aa));return layer,back
@lru_cache(maxsize=1)
def sourceposes():return{r['frame']:r for r in read(O/'native-pose-candidate-v1.json')['poses']}
def sourcepose(n):
 if n<71:return np.array([64,230,1016,1920],float),32,[1,1,0,0]
 p=sourceposes()[min(117,n)];box=np.array(p['box'],float);rad=p['radius'];uv=p['UV_from_source70']
 if n>=90:box=np.array([368,1344,706,1682],float);rad=169
 return box,rad,uv
def matching(cfg):return bool(cfg.get('materials_enabled',True)and cfg['MAIN_asset_id']in cfg.get('selected_asset_ids',[]))
def _old_schedule(cfg,n):
 if cfg['mode']=='source':return dict(active=n>=71,phase=n,return_q=0,semantic_match=n>=71)
 enabled=matching(cfg);active=enabled and 79<=n<190;phase=min(100,71+n-79)if active else 70;ret=float(ease(175,189,n))if active else 0
 return dict(active=active,phase=phase,return_q=ret,semantic_match=enabled and 79<=n<175,asset_id=cfg['MAIN_asset_id']if active else None,visual_retention=active and n>=175)
def _old_subject(cfg,n,s):
 box,rad,uv=sourcepose(s['phase']if s['active']else 70);glow=edge=empty()
 if cfg['mode']=='source':
  raw=Image.open(O/f'source-window-temporal-repair-v2/fixed-{n:04}.png').convert('RGB');window=AV.v02(raw,[1,1,0,0],box,rad)
 else:
  raw=sample(CLEAN,n);base=np.array([952/1080,1690/1920,64,230],float);target=np.array([.45,.45,540-.45*540,1376-.45*470],float)
  # Independent UV for the new person's head occupancy, not box-width scaling.
  q=0 if not s['active']else max(0,min(1,(s['phase']-71)/29));q=1-(1-q)**2;mat=base*(1-q)+target*q;r=s['return_q'];mat=mat*(1-r)+base*r;box=box*(1-r)+np.array([64,230,1016,1920])*r;rad=rad*(1-r)+32*r;window=AV.v02(raw,mat,box,rad)
 if s['active']and s['phase']>=90:
  q=1-s['return_q'];mask=Image.new('L',(1080,1920));ImageDraw.Draw(mask).rounded_rectangle(tuple(box),radius=rad,fill=255);glow=Image.new('RGBA',(1080,1920),'white');glow.putalpha(mask.filter(ImageFilter.GaussianBlur(24)));glow=fade(glow,q);ImageDraw.Draw(edge).rounded_rectangle(tuple(box),radius=rad,outline='white',width=4);edge=fade(edge,q)
 return window,glow,edge,dict(box=box.tolist(),radius=rad,real_scene_window=True,headalpha=False,UV_policy='Source: actual finished-window role masked only. New: independently calibrated clean actor UV interpolation, fixed FA and image matching.',source_temporal_repair=cfg['mode']=='source')
@lru_cache(maxsize=1)
def posterfits():return{r['frame']:r['poster_affine_from85']for r in read(O/'native-geometry-fits-v1.json')['rows']}
def _old_posters(cfg,n,s):
 blur=sharp=empty()
 if not s['active']:return blur,sharp
 if cfg['mode']=='source':
  raw=Image.open(O/'assets/sleep-v4-poster.png').convert('RGBA');mat=np.asarray(posterfits()[n]['matrix']);scl=float(mat[0,0]);xx=float(mat[0,2]);yy=scl*555+float(mat[1,2]);entry=dict(id='sleep',path=str(O/'assets/sleep-v4-poster.png'),type='image',start_frame=0,entry_frames=0,entry_blur=0,rect=[xx/2,yy/2,(xx+1080*scl)/2,(yy+811*scl)/2],radius=0,fit='stretch');sharp=M.render('V03',None,n,dict(size=[1080,1920],fps=25,media_entries=[entry]))['media-sleep'];blur=M._fit(raw,1080,1920,dict(fit='cover')).filter(ImageFilter.GaussianBlur(48))
 else:
  path=cfg['materials'][0]['path'];q=float(ease(79,85,n))*(1-float(ease(175,181,n)));raw=M._sample(dict(path=path,type='image'),0,25);blur=fade(M._fit(raw,1080,1920,dict(fit='cover')).filter(ImageFilter.GaussianBlur(48)),q)
  # Preserve all embedded product text; the source sharp poster may overlap captions, clean adaptation does not.
  zoom=1+.035*float(ease(103,119,n));h=780*zoom;w=972;box=[54,350-(h-780)/2,1026,350+780+(h-780)/2];entry=dict(id='MAIN',path=str(path),type='image',start_frame=0,entry_frames=0,entry_blur=0,rect=[v/2 for v in box],radius=0,fit='contain');sharp=fade(M.render('V03',None,n,dict(size=[1080,1920],fps=25,media_entries=[entry]))['media-MAIN'],q)
 return blur,sharp
def capentry(c,n):
 a,b=c['frames'];near=c.get('near',a+1)
 if not a<=n<b:return 0
 return min(1,max(.12,(n-a+1)/(near-a+1)))
def _old_captions(cfg,n,s):
 out={k:empty()for k in['zh_shadow','zh_current','zh_old_upper','zh_old_lower','en_shadow','en_current','en_old']};meta=[];source=cfg['mode']=='source'
 for lang in['zh','en']:
  if lang=='en'and not source:continue
  rows=cfg['captions_zh']if lang=='zh'else cfg['captions_en']
  for i,c in enumerate(rows):
   warm=source and n==0 and i==0;old=c.get('split',[999,999])[0]<=n<c.get('split',[999,999])[1];q=1 if warm else capentry(c,n)
   if not q and not old:continue
   top=((1502 if n<71 or warm or 238<=n<302 else 1496 if n>=302 else 1174) if lang=='zh' else (1582 if n<71 or warm or n>=238 else 1254))
   if not source:top=1174 if s['active']else 1502
   layer,back=textpair(c['text'],cfg['fonts']['caption']if lang=='zh'else cfg['fonts']['english'],72 if lang=='zh'else 52,top,stroke=2)
   if old:
    a,b=c['split'];q=float(interp([(a,[.70]),(a+1,[.34]),(a+2,[.15]),(b-1,[.13])],n)[0]);both=Image.alpha_composite(back,layer);both=fade(both,q)
    if lang=='zh':
     dy=float(interp([(a,[13]),(a+1,[41]),(a+2,[54]),(a+3,[56]),(b-1,[56])],n)[0])*cfg.get('split_distance_scale',1);cut=top+layer.getchannel('A').getbbox()[3]-top;bb=layer.getchannel('A').getbbox();cut=(bb[1]+bb[3])/2;up,lo=split_rgba(both,cut,0,dy);out['zh_old_upper']=up;out['zh_old_lower']=lo;meta.append(dict(role='ZH03',old_split=True,cut_y=cut,dy=dy,opacity=q,FA_unchanged=True))
    else:out['en_old']=both;meta.append(dict(role='EN03',wholefade=True,opacity=q,no_halfclip=True))
   else:
    out[lang+'_current']=Image.alpha_composite(out[lang+'_current'],fade(layer,q));out[lang+'_shadow']=Image.alpha_composite(out[lang+'_shadow'],fade(back,q));meta.append(dict(role=c['id'],text=c['text'],opacity=q,top=top))
 return out,meta
@lru_cache(maxsize=1)
def grid_candidate():
 im=Image.new('RGBA',(1080,1920),(3,5,7,255));d=ImageDraw.Draw(im);line=(57,59,62,255)
 for x in range(-1800,2881,170):d.line((x,0,540+(x-540)*.04,900),fill=line,width=2);d.line((540+(x-540)*.04,1020,x,1920),fill=line,width=2)
 for y in [35,107,173,234,291,345,394,440,482,522,560,595,628,659,688,716,742,766,789,810,830,849,867,884,900,1020,1040,1070,1110,1160,1220,1290,1370,1460,1560,1670,1790,1915]:d.line((0,y,1080,y),fill=line,width=2)
 return im
def _old_render(cfg,n):
 s=schedule(cfg,n);layers={k:empty()for k in ROLES};layers['background']=grid_candidate();layers['poster_blur'],layers['poster_sharp']=posters(cfg,n,s);layers['presenter_window'],layers['window_glow'],layers['window_edge'],window=subject(cfg,n,s)
 phase=n if cfg['mode']=='source'else n*71/max(1,cfg.get('opening_end_frame',63));warm=cfg['mode']=='source'and n==0;tq=1 if warm else 0 if phase<2 or phase>=76 else min(1,(phase-1)/8)*(1-float(ease(70,76,phase)))
 if cfg.get('title')and tq:
  layer,back=textpair(cfg['title'],cfg['fonts']['title'],124,160,10,(12,40,63,255));layers['title_body']=fade(layer,tq);layers['title_shadow']=fade(back,tq)
 cs,cm=captions(cfg,n,s);layers.update(cs);layers={k:norm(v)for k,v in layers.items()};rgb=Image.new('RGBA',(1080,1920),(0,0,0,255))
 for k in ROLES:rgb.alpha_composite(layers[k])
 return rgb.convert('RGB'),layers,dict(frame=n,schedule=s,window=window,captions=cm,identity_policy='Native absent; no added badge in either source or new branch. Empty/disabled/name-only/desc-only metadata therefore do not activate a nonexistent native component.',EN_policy='Source literal observed English only; clean EN omitted, no confirmed translation.' )

def schedule(cfg,n):
 if cfg['mode']=='source':
  active=71<=n<217 or n>=302;return dict(active=active,phase=n,return_q=0,semantic_match=active,stage=0 if n<302 else 1)
 m=next((m for m in cfg['materials'] if m['start']-7<=n<m['end']+14),None)
 if not m:return dict(active=False,phase=70,return_q=0,semantic_match=False,stage=-1)
 q=float(ease(m['end'],m['end']+13,n));phase=min(100,71+max(0,n-m['start']+7))
 return dict(active=True,phase=phase,return_q=q,semantic_match=n<m['end'],asset_id=m['id'],stage=m['stage'],material=m)
def subject(cfg,n,s):
 if cfg['mode']=='source' and n<118:
  old=O;globals()['O']=Path(cfg['source_cache_root'])
  try:return _old_subject(cfg,n,s)
  finally:globals()['O']=old
 base=np.array([64,230,1016,1920.]);large=np.array([0,100,1080,1920.]);bottom=np.array([368,1344,706,1682.]);right=np.array([668,198,998,528.])
 if cfg['mode']=='source':
  if n<217:box=bottom;rad=169
  elif n<245:q=float(ease(217,244,n));box=bottom*(1-q)+large*q;rad=169*(1-q)+24*q
  elif n<302:box=large;rad=24
  else:q=float(ease(302,325,n));box=large*(1-q)+right*q;rad=24 if n<321 else 24+141*float(ease(321,325,n))
  raw=sample(cfg['source'],n);x,y,x2,y2=map(lambda v:round(float(v)),box);part=np.array(raw.crop((x,y,x2,y2))).copy();mask=np.zeros(part.shape[:2],np.uint8)
  if 118<=n<237:aa=max(0,1155-y);bb=min(part.shape[0],1340-y)
  else:aa=max(0,1475-y);bb=min(part.shape[0],1685-y)
  if aa<bb:
   color=part.astype(int);white=(color.max(2)-color.min(2)<65)&(color.min(2)>120);corridor=np.zeros(part.shape[:2],np.uint8);corridor[aa:bb]=255;mask=cv2.dilate((white&(corridor>0)).astype(np.uint8)*255,np.ones((5,5),np.uint8))
  if mask.any():
   before=part.copy();part=cv2.inpaint(part,mask,3,cv2.INPAINT_TELEA)
   if cfg.get('repair_dir') and n in [156,188,217,223,226,230,244,302,325,475]:
    folder=Path(cfg['repair_dir']);folder.mkdir(parents=True,exist_ok=True);Image.fromarray(mask).save(folder/f'f{n:04}-mask.png');Image.fromarray(np.abs(before.astype(int)-part.astype(int)).astype(np.uint8)).save(folder/f'f{n:04}-diff.png')
  tex=Image.fromarray(part);window=AV.v02(tex,[(x2-x)/1080,(y2-y)/1920,x,y],box,rad)
 else:
  raw=sample(cfg['source'],n);target=bottom if s['stage']==0 else right;q=float(ease(71,100,s['phase'])) if s['active'] else 0;q*=1-s['return_q'];box=base*(1-q)+target*q;rad=32*(1-q)+min(target[2]-target[0],target[3]-target[1])/2*q
  x,y,x2,y2=box;texture=M._fit(raw.convert('RGBA'),round(x2-x),round(y2-y),dict(fit='cover',anchor=[.5,.35]));window=AV.v02(texture,[(x2-x)/1080,(y2-y)/1920,x,y],box,rad)
 glow=edge=empty()
 if rad>40:
  mask=Image.new('L',(1080,1920));ImageDraw.Draw(mask).rounded_rectangle(tuple(box),radius=rad,fill=255);glow=Image.new('RGBA',(1080,1920),'white');glow.putalpha(mask.filter(ImageFilter.GaussianBlur(24)));ImageDraw.Draw(edge).rounded_rectangle(tuple(box),radius=rad,outline='white',width=4)
 return window,glow,edge,dict(box=box.tolist(),radius=rad,real_scene_window=True,headalpha=False,source_recovery=cfg['mode']=='source')
def posters(cfg,n,s):
 blur=sharp=empty()
 if not s['active']:return blur,sharp
 source=cfg['mode']=='source'
 if source and n<118:
  old=O;globals()['O']=Path(cfg['source_cache_root'])
  try:return _old_posters(cfg,n,s)
  finally:globals()['O']=old
 if source:
  path=Path(cfg['source_cache_root'])/'assets/sleep-v4-poster.png' if n<217 else Path(cfg['morning_source']);q=1 if n<208 else 1-float(ease(208,217,n)) if n<217 else float(ease(307,325,n));stage=0 if n<217 else 1
 else:
  m=s['material'];path=Path(m['path']);q=float(ease(m['start'],m['start']+9,n))*(1-float(ease(m['end']-7,m['end'],n)));stage=m['stage']
 image=M._sample(dict(path=str(path),type='image'),0,25);blur=fade(M._fit(image,1080,1920,dict(fit='cover')).filter(ImageFilter.GaussianBlur(48)),q)
 box=[0,462,1080,1459] if source and stage==0 else [54,380,1022,1606] if stage>0 else [54,350,1026,1130]
 late=1 if not source or n<483 else 1-float(ease(483,498,n));scale=.8+.2*late;cx=(box[0]+box[2])/2;cy=(box[1]+box[3])/2+90*(1-late);w=(box[2]-box[0])*scale;h=(box[3]-box[1])*scale;box=[cx-w/2,cy-h/2,cx+w/2,cy+h/2]
 entry=dict(id='actual',path=str(path),type='image',start_frame=0,entry_frames=0,entry_blur=0,rect=[v/2 for v in box],radius=12,fit='cover' if source else 'contain');sharp=fade(M.render('V03',None,n,dict(size=[1080,1920],fps=25,media_entries=[entry]))['media-actual'],q*late)
 return blur,sharp
def captions(cfg,n,s):
 if cfg['mode']=='source':return _old_captions(cfg,n,s)
 out={k:empty()for k in ['zh_shadow','zh_current','zh_old_upper','zh_old_lower','en_shadow','en_current','en_old']};meta=[]
 for c in cfg['captions_zh']:
  old=c.get('split') and c['split'][0]<=n<c['split'][1];q=capentry(c,n)
  if not q and not old:continue
  top=1174 if s['active'] and s['stage']==0 else 1496 if s['active'] else 1502;layer=empty();back=empty();lines=c['lines']
  for i,line in enumerate(lines):
   a,b=textpair(line['text'],cfg['fonts']['caption'],cfg.get('caption_size',72),top-(len(lines)-1-i)*90,2);layer.alpha_composite(a);back.alpha_composite(b)
  if old:
   a,b=c['split'];t=n-a;opacity=float(interp([(0,[.70]),(1,[.34]),(2,[.15]),(max(3,b-a-1),[.13])],t)[0]);both=fade(Image.alpha_composite(back,layer),opacity);bb=layer.getchannel('A').getbbox();up,lo=split_rgba(both,(bb[1]+bb[3])/2,0,float(interp([(0,[13]),(1,[41]),(2,[54]),(3,[56])],t)[0]));out['zh_old_upper'].alpha_composite(up);out['zh_old_lower'].alpha_composite(lo)
  else:out['zh_current'].alpha_composite(fade(layer,q));out['zh_shadow'].alpha_composite(fade(back,q))
  meta.append(dict(id=c['id'],FA_seconds=c['original_FA_seconds'],display_frames=c['frames'],split=bool(old)))
 return out,meta
def render(cfg,n):
 rgb,layers,meta=_old_render(cfg,n);start=217 if cfg['mode']=='source' else cfg['materials'][0]['end'] if cfg['materials'] else 10**9;phase=n-start
 if 0<=phase<10:
  raw=sample(cfg['source'],n);texture=M._fit(raw.convert('RGBA'),1404,2496,dict(fit='cover')).filter(ImageFilter.GaussianBlur(30));band=empty();band.alpha_composite(texture,(-162,-288));mask=Image.new('L',(1080,1920));d=ImageDraw.Draw(mask)
  if phase<=4:edge=20+(phase/4)**2*2600;d.polygon([(0,0),(edge,0),(edge-1000,1920),(0,1920)],fill=255)
  else:edge=(phase-4)/6*2700;d.polygon([(edge-1000,0),(1080,0),(1080,1920),(edge-1900,1920)],fill=255)
  band.putalpha(mask);layers['composite_wipe']=band
 if n>=cfg.get('fade_start',10**9):
  q=max(0,min(1,(cfg['black_at']-n)/max(1,cfg['black_at']-cfg['fade_start'])))
  for key,im in layers.items():
   if cfg['mode']=='source' and key=='presenter_window':continue
   arr=np.array(im);arr[:,:,:3]=np.round(arr[:,:,:3]*q).astype(np.uint8);layers[key]=Image.fromarray(arr)
 if n>=cfg.get('black_at',10**9):layers={k:empty() for k in layers}
 out=Image.new('RGBA',(1080,1920),(0,0,0,255))
 for im in layers.values():out.alpha_composite(im)
 return out.convert('RGB'),layers,meta
