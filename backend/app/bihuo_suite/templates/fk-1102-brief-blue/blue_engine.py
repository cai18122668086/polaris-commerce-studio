"""Blue pilot composition; pinned media/rounded-affine/text primitives, local style recipe only."""
from pathlib import Path
import sys,json,hashlib
from functools import lru_cache
import numpy as np
import cv2
from PIL import Image,ImageDraw,ImageFilter
O=Path(__file__).resolve().parent/'data'
from .vendor.apple_minimal import visual as V,media as M
from .vendor.apple_minimal.pilot import font,text_image,ease
W,H=1080,1920;BLUE=(38,95,245,255)
def read(p):return json.loads(Path(p).read_text('utf8'))
def sha(p):return hashlib.file_digest(Path(p).open('rb'),'sha256').hexdigest()
def blank():return Image.new('RGBA',(W,H))
def sample(path,n):
 raw=M._sample(dict(path=str(path),type='video',start_frame=0,end_policy='hold'),n,25).convert('RGB')
 return raw if raw.size==(W,H) else M._fit(raw.convert('RGBA'),W,H,dict(fit='cover',anchor=[.5,.5])).convert('RGB')
def opacity(im,q):
 if q>=1:return im
 out=im.copy();out.putalpha(out.getchannel('A').point(lambda a:round(a*max(0,q))));return out
def observed_entry(role,start,steady,n):
 values=[0,.10,.293,.519,.709,.850,.947,1]if role=='identity'else[0,.292,.513,.681,.799,.884,.939,.975,1]
 q=max(0,min(1,(n-(start-1))/(steady-(start-1))));return float(np.interp(q,np.linspace(0,1,len(values)),values))
@lru_cache(maxsize=512)
def tile(text,path,size,color,shear=0):
 im,_,_=text_image(text,path,size,color)
 box=im.getchannel('A').getbbox();im=im.crop(box) if box else Image.new('RGBA',(1,1))
 if shear:
  extra=round(abs(shear)*im.height)+2
  im=im.transform((im.width+extra,im.height),Image.Transform.AFFINE,(1,shear,-extra if shear>0 else 0,0,1,0),Image.Resampling.BICUBIC)
  b=im.getchannel('A').getbbox();im=im.crop(b) if b else im
 return im
def put(layer,text,path,size,color,x,y,center=False,shear=0):
 if not text:return None
 im=tile(text,path,size,tuple(color),shear);x=round(x-im.width/2)if center else round(x);y=round(y);layer.alpha_composite(im,(x,y));return [x,y,x+im.width,y+im.height]
def lerp(keys,n):
 if n<=keys[0][0]:return np.array(keys[0][1],float)
 for (a,x),(b,y) in zip(keys,keys[1:]):
  if n<=b:return np.array(x)*(1-(n-a)/(b-a))+np.array(y)*(n-a)/(b-a)
 return np.array(keys[-1][1],float)
@lru_cache(maxsize=1)
def gradient():
 y=np.arange(H)[:,None,None]/(H-1);top=np.array([210,226,250]);bottom=np.array([255,241,233]);a=np.repeat((top[None,None,:]*(1-y)+bottom[None,None,:]*y).astype('uint8'),W,axis=1);return Image.fromarray(a).convert('RGBA')
@lru_cache(maxsize=1)
def material_entry_parameters():return read(O/'style-parameters.json')['material_entry']
def presenter(texture,box,radius):
 x,y,x2,y2=box;key=dict(time=0,matrix=[[(x2-x)/W,0,x/2],[0,(y2-y)/H,y/2]],rect=[v/2 for v in box],radius=radius/2,background_opacity=0)
 return V.render('V02',texture,0,dict(size=[W,H],fps=25,visual_keys=[key]))['presenter']
def active_schedule(cfg):
 wanted={r['asset_id'] for r in cfg.get('materials',[])};rows=[];prev_end=None
 for a in cfg.get('semantic_assignments',[]):
  if a['asset_id'] not in wanted:continue
  start,end=a['frames'];pre=max(start-14,prev_end+8 if prev_end is not None else start-14);pre=pre if pre<start-2 else start-14;rows.append(dict(**a,pre=pre,settle=start-2,return_end=end+8));prev_end=end
 return rows
def composition_pose(cfg,n):
 if cfg['mode']=='baseline':
  pose=read(O/'recovery/poses.json')[str(n)];return pose['box'],pose['radius'],None
 q=0;selected=None
 for row in active_schedule(cfg):
  a,b=row['frames'];enter=ease(row['pre'],row['settle'],n);leave=1-ease(b,row['return_end'],n)
  z=enter*leave if row['pre']<=n<row['return_end'] else 0
  if z>q:q=z;selected=row
 full=np.array([0,135,1080,1920]);small=np.array([395,1183,686,1573]);return [float(v)for v in full*(1-q)+small*q],28*q,selected
def identity(cfg,n):
 out=blank();data=cfg.get('identity',{});name=data.get('name','').strip();desc=data.get('description','').strip()
 if data.get('enabled',True)is False or not(name or desc):return out,dict(active=False,bounds=None)
 a,steady,end=cfg['identity_clock'];q=1 if cfg.get('warm0') and n==0 else observed_entry('identity',a,steady,n)
 if n>=end:q=0
 if q<=0:return out,dict(active=False,bounds=None)
 # A fitted white source-style panel; empty rows removed. Explicit field values only.
 x,y=605,1123;maxw=420;pad=22;lines=[]
 for role,s,size,path,color in [('name',name,80,cfg['fonts']['name'],(0,0,0,255)),('description',desc,44,cfg['fonts']['body'],(105,105,105,255))]:
  if not s:continue
  current=''
  for ch in s:
   if current and tile(current+ch,path,size,color,.17 if role=='name' else 0).width>maxw-2*pad:lines.append((role,current,size,path,color));current=ch
   else:current+=ch
  if current:lines.append((role,current,size,path,color))
 widths=[tile(s,p,z,c,.17 if role=='name' else 0).width for role,s,z,p,c in lines];heights=[tile(s,p,z,c,.17 if role=='name' else 0).height for role,s,z,p,c in lines]
 w=max(160,max(widths)+2*pad);h=sum(heights)+2*pad+22*(len(lines)-1)
 if name and desc and len(lines)==2:w=max(w,236);h=max(h,216)
 if y+h>1575:raise ValueError('Identity fields overflow before ordinary caption; shorten explicit fields')
 d=ImageDraw.Draw(out);d.rounded_rectangle((x,y,x+w,y+h),radius=7,fill='white');cy=y+pad
 if name and desc and len(lines)==2:cy=y+32
 for k,(role,s,z,path,color) in enumerate(lines):
  if name and desc and len(lines)==2:cy=y+(32 if role=='name' else 157)
  put(out,s,path,z,color,x+pad,cy,False,.17 if role=='name' else 0);cy+=heights[k]+22
 return opacity(out,q),dict(active=True,bounds=[x,y,x+w,y+h],opacity=q,fields=[r[0]for r in lines])
def header(cfg,n):
 out=blank();data=cfg.get('header',{});lines=data.get('lines',[]);label=data.get('label','')
 if not data.get('enabled',True)or not(label or any(lines)):return out
 start,steady=cfg['header_entry'];end=cfg.get('header_exit');q=1 if cfg.get('warm0') and n==0 else observed_entry('header',start,steady,n)
 if end:q*=max(0,min(1,1-(n-(end[0]-1))/(end[1]-(end[0]-1))))
 if q<=0:return out
 d=ImageDraw.Draw(out);d.rounded_rectangle((59,219,1020,419),radius=42,fill='white');d.line((257,290,257,349),fill=(221,221,221,255),width=2)
 put(out,label,cfg['fonts']['body'],29,(102,102,102,255),166,310,True)
 for k,s in enumerate(lines):
  im=tile(s,cfg['fonts']['name'],48,BLUE,.17);strong=Image.new('RGBA',im.size,BLUE);strong.putalpha(im.getchannel('A').filter(ImageFilter.MaxFilter(5)));out.alpha_composite(strong,(284,266+65*k))
 return opacity(out,q)
def _single_captions(cfg,n,disabled_shadow=False):
 roles={k:blank()for k in ['caption_body','caption_emphasis','caption_shadow','caption_glow']};meta=[]
 for row in cfg['captions']:
  a,b=row['frames'];warm=cfg.get('warm0')and n==0 and row==cfg['captions'][0]
  if not(a<=n<b or warm):continue
  q=1 if warm else max(0,min(1,(n-a+1)/min(8.65,max(1,b-a))))
  parts=V.caption_parts(dict(text=row['text'],emphasis_spans=row.get('emphasis_spans',[])));pieces=[]
  for s,emph in parts:
   size=cfg.get('caption_size',58)+10 if emph else cfg.get('caption_size',58);path=cfg['fonts']['accent']if emph else cfg['fonts'].get('caption_body',cfg['fonts']['body']);im=tile(s,path,size,BLUE if emph else(255,255,255,255),.08 if emph else 0);pieces.append((im,emph,s))
  width=sum(im.width for im,_,_ in pieces)+max(0,len(pieces)-1)*1
  if width>1010:raise ValueError(('Caption natural ink overflow',row['text'],width))
  x=round(540-width/2)
  for im,emph,s in pieces:
   y=1608 if emph else 1612;k='caption_emphasis'if emph else'caption_body';roles[k].alpha_composite(im,(x,y));meta.append(dict(text=s,emphasis=emph,ink_box=[x,y,x+im.width,y+im.height]));x+=im.width+1
  combined=blank();combined.alpha_composite(roles['caption_body']);combined.alpha_composite(opacity(roles['caption_emphasis'],.25));mask=combined.getchannel('A');shadow=blank();sh=Image.new('RGBA',(W,H),(0,0,0,0));shift=Image.new('L',(W,H));shift.paste(mask,(3,5));sh.putalpha(shift.filter(ImageFilter.GaussianBlur(2)).point(lambda z:round(z*.72)));shadow.alpha_composite(sh);roles['caption_shadow']=blank()if disabled_shadow else shadow
  glow=Image.new('RGBA',(W,H),(255,248,222,0));glow.putalpha(roles['caption_emphasis'].getchannel('A').filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(2)).point(lambda z:round(z*.82)));roles['caption_glow']=glow
  roles={k:opacity(v,q)for k,v in roles.items()}
 return roles,meta
def _source_material(cfg,n):
 out=blank();active=[]
 for r in (cfg.get('materials',[])if cfg['mode']=='baseline'else active_schedule(cfg)):
  a,b=r['frames']
  if not a<=n<b:continue
  # Actual V03 media role; the encoded source slot has a separate local entry fade.
  entry=dict(id=r['asset_id'],path=r['path'],type='image',start_frame=a,entry_frames=0,entry_blur=0,rect=[27,72.5,513,571.5],radius=15,fit='cover')
  role=M.render('V03',None,n,dict(size=[W,H],fps=25,media_entries=[entry]))['media-'+r['asset_id']]
  measured=material_entry_parameters();q=float(np.clip(np.interp(n-a+1,measured['relative_frames'],measured['relative_contrast']),0,1))
  out.alpha_composite(opacity(role,q));active.append(r['asset_id'])
 return out,active
def _full_render(cfg,n,disabled_shadow=False):
 box,radius,scheduled=composition_pose(cfg,n);bg=gradient().copy()
 if cfg['mode']=='baseline':
  texture=Image.open(O/f'recovery/textures/f{n:04}.png').convert('RGB')
  if n<357:
   raw=sample(cfg['source'],n);bg.paste(raw.crop((0,0,W,135)),(0,0))
  elif n<360:
   raw=sample(cfg['source'],n);strip=raw.crop((0,0,W,135)).resize((W,round(box[1])));base=gradient().copy();base.paste(strip,(0,0));bg=Image.blend(base,bg,ease(357,360,n))
 else:
  raw=sample(cfg['source'],n);q=max(0,min(1,(box[0]/395)))
  # One continuous camera crop, not a crossfade between two differently scaled faces.
  texture=raw.crop((0,round(200*q),W,round(1785+(1648-1785)*q))).resize((W,H),Image.Resampling.LANCZOS)
  if q<1:
   blur=raw.crop((0,0,W,400)).resize((W,135)).filter(ImageFilter.GaussianBlur(26)).convert('RGBA');band=blank();band.alpha_composite(blur,(0,0));band_alpha=1
   if scheduled:band_alpha=(1-ease(scheduled['pre'],scheduled['pre']+3,n))if n<scheduled['frames'][1]else ease(scheduled['return_end']-3,scheduled['return_end'],n)
   bg.alpha_composite(opacity(band,band_alpha))
 person=presenter(texture,box,radius);mat,active=material(cfg,n);ident,idmeta=identity(cfg,n);hd=header(cfg,n);caps,capmeta=captions(cfg,n,disabled_shadow)
 layers=dict(background=bg,material=mat,presenter=person,identity=ident,header=hd,**caps);out=bg.copy()
 for role in ['material','presenter','identity','header','caption_glow','caption_shadow','caption_body','caption_emphasis']:out.alpha_composite(layers[role])
 # Tail is source-wide only; source pilot stops before it, migration scoped independently.
 return out,layers,dict(frame=n,presenter_box=box,presenter_radius=radius,material_active=active,material_schedule=scheduled['asset_id']if scheduled else None,identity=idmeta,caption=capmeta,header_active=hd.getchannel('A').getbbox()is not None)

@lru_cache(maxsize=8)
def safe_picture(path):
 rect=[27,72.5,513,571.5]
 def part(tag,fit):return M.render('V03',None,0,dict(size=[W,H],fps=25,media_entries=[dict(id=tag,path=path,type='image',start_frame=0,entry_frames=0,entry_blur=0,rect=rect,radius=15,fit=fit)]))['media-'+tag]
 full=part('fill','cover');a=full.getchannel('A');full=full.filter(ImageFilter.GaussianBlur(32));full.putalpha(a);full.alpha_composite(part('clear','contain'));return full
def material(cfg,n):
 if cfg['mode']=='baseline':return _source_material(cfg,n)
 out=blank();active=[];measured=material_entry_parameters()
 for row in active_schedule(cfg):
  a,b=row['frames']
  if a<=n<b:
   q=float(np.clip(np.interp(n-a+1,measured['relative_frames'],measured['relative_contrast']),0,1));out.alpha_composite(opacity(safe_picture(row['path']),q));active.append(row['asset_id'])
 return out,active
def captions(cfg,n,disabled_shadow=False):
 if cfg['mode']=='baseline':return _single_captions(cfg,n,disabled_shadow)
 output={k:blank() for k in ['caption_body','caption_emphasis','caption_shadow','caption_glow']};meta=[]
 for row in cfg['captions']:
  if not row['frames'][0]<=n<row['frames'][1]:continue
  lines=row.get('lines') or [dict(text=row['text'],emphasis_spans=row.get('emphasis_spans',[]))]
  for i,line in enumerate(lines):
   local=dict(cfg,captions=[dict(row,text=line['text'],emphasis_spans=line.get('emphasis_spans',[]))]);layers,mm=_single_captions(local,n,disabled_shadow);dy=-(len(lines)-1-i)*82
   for k,im in layers.items():output[k].alpha_composite(im,(0,dy))
   meta.extend(mm)
 return output,meta
@lru_cache(maxsize=1)
def tail_curve():return {r['frame']:min(1,max(0,r['relative_RGB'])) for r in read(O/'native-tail-curve.json')['rows']}
def render(cfg,n,disabled_shadow=False):
 out,layers,meta=_full_render(cfg,n,disabled_shadow)
 if n>=cfg['fade_start']:
  phase=513+n-cfg['fade_start'];q=tail_curve().get(min(525,phase),0);out=Image.fromarray(np.uint8(np.clip(np.array(out.convert('RGB')).astype(float)*q,0,255)));meta['wholecanvas_RGB_postfade']=q
 if n>=cfg['black_at']:out=Image.new('RGB',(W,H))
 return out.convert('RGB'),layers,meta
