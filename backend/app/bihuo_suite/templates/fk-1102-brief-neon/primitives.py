from functools import lru_cache
import math
import numpy as np
from PIL import Image,ImageDraw,ImageFilter
W,H=1080,1920
LIME=(216,255,0,255);CYAN=(25,239,217,255)
def blank():return Image.new('RGBA',(W,H))

def op(im,q):
 if q>=1:return im
 im=im.copy();im.putalpha(im.getchannel('A').point(lambda a:round(a*max(0,q))));return im

@lru_cache(maxsize=512)
def tile(s,path,size,color,shear=0):
 im,_,_=text_image(s,path,size,color);b=im.getchannel('A').getbbox();im=im.crop(b)if b else Image.new('RGBA',(1,1))
 if shear:
  extra=round(abs(shear)*im.height)+2;im=im.transform((im.width+extra,im.height),Image.Transform.AFFINE,(1,shear,-extra if shear>0 else 0,0,1,0),Image.Resampling.BICUBIC);b=im.getchannel('A').getbbox();im=im.crop(b)if b else im
 return im

def put(im,s,path,size,color,xy,shear=0):
 if not s:return None
 t=tile(s,path,size,tuple(color),shear);im.alpha_composite(t,tuple(map(round,xy)));return[round(xy[0]),round(xy[1]),round(xy[0]+t.width),round(xy[1]+t.height)]

def place(out,im,center,scale=1,alpha=1,angle=0,blur=0):
 if scale<=0 or alpha<=0:return
 if scale!=1:im=im.convert('RGBa').resize((max(1,round(im.width*scale)),max(1,round(im.height*scale))),Image.Resampling.LANCZOS).convert('RGBA')
 if angle:im=im.rotate(angle,Image.Resampling.BICUBIC,expand=True)
 if blur:im=im.convert('RGBa').filter(ImageFilter.GaussianBlur(blur)).convert('RGBA')
 im=op(im,alpha);out.alpha_composite(im,(round(center[0]-im.width/2),round(center[1]-im.height/2)))

@lru_cache(maxsize=16)
def icon(kind,size,color=(0,0,0,255)):
 im=Image.new('RGBA',(80,80));d=ImageDraw.Draw(im);c=color
 if kind=='robot':
  d.rounded_rectangle((13,23,67,65),radius=8,outline=c,width=5);d.line((40,23,40,10),fill=c,width=4);d.ellipse((36,6,44,14),fill=c);d.ellipse((24,35,30,42),fill=c);d.ellipse((50,35,56,42),fill=c);d.rounded_rectangle((27,50,53,58),radius=3,outline=c,width=3)
 elif kind=='laptop':d.line((18,20,61,23,63,56,15,53,18,20),fill=c,width=4);d.line((10,58,68,61),fill=c,width=5);d.line((34,47,45,47),fill=c,width=3)
 elif kind=='gear':
  pts=[]
  for i in range(32):a=i*math.pi/16;r=31 if i%4 in[0,1] else 25;pts.append((40+math.cos(a)*r,40+math.sin(a)*r))
  d.polygon(pts,outline=c,width=4);d.ellipse((28,28,52,52),outline=c,width=4)
 elif kind=='image':d.rounded_rectangle((12,17,68,63),radius=5,outline=c,width=4);d.ellipse((48,26,57,35),fill=c);d.line((17,55,31,39,43,49,51,42,65,56),fill=c,width=4)
 else:d.line((19,41,34,56,62,25),fill=c,width=7)
 return im.resize((size,size),Image.Resampling.LANCZOS)

def pill(text,path,size,lime=False,kind='robot',padding=18,height=92):
 t=tile(text,path,size,(0,0,0,255));ic=round(height*.74);w=padding*2+ic+16+t.width;im=Image.new('RGBA',(w,height));d=ImageDraw.Draw(im);d.rounded_rectangle((0,0,w-1,height-1),radius=height/2,fill=LIME if lime else'white');cx=padding+ic/2;cy=height/2;d.ellipse((padding,(height-ic)/2,padding+ic,(height+ic)/2),fill=(0,0,0,255)if lime else LIME);im.alpha_composite(icon(kind,round(ic*.53),LIME if lime else(0,0,0,255)),(round(cx-ic*.265),round(cy-ic*.265)));im.alpha_composite(t,(padding+ic+16,round((height-t.height)/2)));return im

def agenda(cfg,n):
 out=blank();meta=[];a,b=cfg['agenda_exit']
 for row in cfg.get('agenda',[]):
  t=n-row['first'];first=row.get('entry_variant','first'if row is cfg['agenda'][0]else'second')=='first'
  times=[-1,0,1,2,3,4,5,6,8,13]if first else[-1,0,1,2,3,4,5,6,7,9,14];values=[0,.12,.51,.75,.91,.99,1.025,1.028,1.016,1]if first else[0,.02,.10,.36,.64,.84,.96,1.013,1.028,1.02,1];scale=float(np.interp(t,times,values));alpha=float(np.interp(t,[-1,0,1,2,3],[0,.3,.95,1,1]if first else[0,.05,.25,.85,1]))
  if cfg.get('warm0')and n==0 and row is cfg['agenda'][0]:scale=alpha=1
  alpha*=1-ease(a,b,n)
  if alpha<=0 or scale<=0:continue
  im=pill(row['text'],cfg['fonts']['pill'],row['size'],row['lime'],row['icon'],height=92 if row['size']>=46 else 82).rotate(row['angle'],Image.Resampling.BICUBIC,expand=True);left=row.get('left',row['center'][0]-im.width/2);center=[left+im.width*scale/2,row['center'][1]+(18 if first else-14)*(1-scale)];place(out,im,center,scale,alpha);meta.append(dict(text=row['text'],opacity=alpha,scale=scale,angle=row['angle'],center=center,left_anchor=left))
 return out,meta

def identity(cfg,n):
 out=blank();r=cfg.get('identity',{});name=r.get('name','').strip();desc=r.get('description','').strip();a,s,b=cfg['identity_clock']
 if not r.get('enabled',True)or not(name or desc):return out,dict(active=False)
 q=1 if cfg.get('warm0')and n==0 else ease(a-1,s,n)
 if n>=b or q<=0:return out,dict(active=False)
 lines=[]
 for role,text,size in [('name',name,80),('description',desc,48)]:
  if not text:continue
  cur=''
  for ch in text:
   if cur and tile(cur+ch,cfg['fonts']['name']if role=='name'else cfg['fonts']['body'],size,(255,255,255,255)).width>374:lines.append((role,cur,size));cur=ch
   else:cur+=ch
  lines.append((role,cur,size))
 widths=[tile(t,cfg['fonts']['name']if k=='name'else cfg['fonts']['body'],z,(255,255,255,255)).width for k,t,z in lines];height=sum(z for _,_,z in lines)+20*(len(lines)-1)+44;width=max(236,max(widths)+44)
 if name and desc and len(lines)==2:height=215
 assert 1124+height<1580,'Explicit identity too long before caption band'
 ImageDraw.Draw(out).rounded_rectangle((605,1124,605+width,1124+height),radius=5,fill=(0,0,0,235));y=1156
 for k,t,z in lines:
  if name and desc and len(lines)==2:y=1156 if k=='name' else 1280
  if k=='name':
   ti=tile(t,cfg['fonts']['name'],z,(255,255,255,255));wide=Image.new('RGBA',(ti.width+8,ti.height+8));wide.alpha_composite(ti,(4,4));wide.putalpha(wide.getchannel('A').filter(ImageFilter.MaxFilter(5)));out.alpha_composite(wide,(623,round(y)-4))
  else:put(out,t,cfg['fonts']['body'],z,LIME,(627,y))
  y+=z+20
 return op(out,q),dict(active=True,fields=[k for k,_,_ in lines],bounds=[605,1124,605+width,1124+height],opacity=q)

def caption(cfg,n,shadow_off=False):
 ls={k:blank()for k in['caption_body','caption_emphasis','caption_shadow','caption_glow']};meta=[]
 cue=next((c for c in cfg['captions']if c['frames'][0]<=n<c['frames'][1]),None)
 if cfg.get('warm0')and n==0:cue=cfg['captions'][1]
 if not cue:return ls,meta
 a,b=cue['frames'];q=1 if n==0 else min(1,max(0,(n-a+1)/8.65));pieces=[]
 for s,e in V.caption_parts(cue):
  path=cfg['fonts'].get('caption_body',cfg['fonts']['body'])if not e else cfg['fonts']['accent'];im=tile(s,path,68 if e else 58,LIME if e else(255,255,255,255),.055 if e else 0);pieces.append((s,e,im))
 x=(W-sum(t.width for _,_,t in pieces)-max(0,len(pieces)-1))/2
 for s,e,t in pieces:y=1608 if e else 1615;ls['caption_emphasis'if e else'caption_body'].alpha_composite(t,(round(x),y));meta.append(dict(text=s,emphasis=e,ink_box=[round(x),y,round(x+t.width),y+t.height]));x+=t.width+1
 joined=blank();joined.alpha_composite(ls['caption_body']);joined.alpha_composite(ls['caption_emphasis']);sh=blank();shift=Image.new('L',(W,H));shift.paste(joined.getchannel('A'),(3,5));sh.putalpha(shift.filter(ImageFilter.GaussianBlur(2)).point(lambda z:round(z*.8)));ls['caption_shadow']=blank()if shadow_off else sh
 gl=Image.new('RGBA',(W,H),(216,255,0,0));gl.putalpha(ls['caption_emphasis'].getchannel('A').filter(ImageFilter.GaussianBlur(3)).point(lambda z:round(z*.17)));ls['caption_glow']=gl
 return{k:op(v,q)for k,v in ls.items()},meta
