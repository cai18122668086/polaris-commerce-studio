from pathlib import Path
from functools import lru_cache
import math,numpy as np
from PIL import Image,ImageDraw,ImageFilter
from .vendor import visual as approved_visual,media as approved_media
from .vendor.pilot import font,text_image
W,H=1080,1920


def blank():return Image.new('RGBA',(W,H))

def fade(im,q):
 im=im.copy();im.putalpha(im.getchannel('A').point([round(a*max(0,min(1,q))) for a in range(256)]));return im

def lerp(keys,n):
 if n<=keys[0][0]:return keys[0][1]
 for (a,v),(b,w) in zip(keys,keys[1:]):
  if a<=n<=b:return np.asarray(v)*(1-(n-a)/(b-a))+np.asarray(w)*(n-a)/(b-a)
 return keys[-1][1]

def v02(raw,matrix,rect,radius):
 key=dict(time=0,matrix=[[float(matrix[0]),0,float(matrix[2])/2],[0,float(matrix[1]),float(matrix[3])/2]],rect=[float(v)/2 for v in rect],radius=float(radius)/2,background_opacity=0)
 return approved_visual.render('V02',raw,0,dict(size=[W,H],fps=25,stage_color=[17,17,24],visual_keys=[key]))['presenter']

@lru_cache(maxsize=2)
def background(n,velocity=.6):
 yy=np.arange(H)[:,None,None]/(H-1);a=np.array([18,17,24]);b=np.array([25,23,66]);arr=np.broadcast_to((a*(1-yy)+b*yy),(H,W,3)).copy().astype(np.uint8)
 im=Image.fromarray(arr).convert('RGBA');d=ImageDraw.Draw(im)
 # Approximate early source drift, explicitly not recovered global author phase.
 for x in range(0,W,60):d.line((x,0,x,H),fill=(43,42,55,255),width=1)
 phase=(-n*velocity)%60
 for y in np.arange(phase-60,H+60,60):d.line((0,round(y),W,round(y)),fill=(43,42,55,255),width=1)
 return im

def pose(n):
 # Manually source-measured knots, linear interpolation between measured observations.
 box=lerp([(270,[74,497,1008,1425]),(280,[74,497,1008,1425]),(281,[124,476,958,1305]),(282,[169,465,912,1203]),(283,[214,451,868,1101]),(284,[257,433,827,1005]),(285,[290,414,796,919]),(286,[316,394,768,849]),(288,[354,359,731,735]),(292,[390,306,695,620]),(293,[390,306,695,620])],n)
 radius=float(lerp([(270,[32]),(280,[32]),(281,[58]),(282,[86]),(283,[105]),(284,[118]),(285,[136]),(286,[154]),(288,[175]),(292,[146])],n)[0])
 return np.asarray(box,float),radius

def foreground(raw,alpha,matrix,box,active,radius=0,base_alpha=None):
 if not active:return blank(),dict(active=False,visible_pixels=0,occluded_model_pixels=0)
 s,t,x,y=matrix; rgb=v02(raw,matrix,[0,0,W,H],0)
 inv=(1/s,0,-x/s,0,1/t,-y/t)
 warped=alpha.transform((W,H),Image.Transform.AFFINE,inv,resample=Image.Resampling.BICUBIC)
 arr=np.asarray(warped).copy();before=int((arr>4).sum());arr[math.ceil(box[1]+radius):]=0
 # Expose the real head above the top AND over transparent upper rounded corners.
 # A flat y=window_top cut creates false cheek gaps; actual bottom-window alpha must occlude it.
 if base_alpha is not None:arr=np.uint8(arr.astype(np.float32)*(255-np.asarray(base_alpha,dtype=np.float32))/255)
 rgb.putalpha(Image.fromarray(arr));return rgb,dict(active=True,visible_pixels=int((arr>4).sum()),occluded_model_pixels=before-int((arr>4).sum()),visible_alpha_bbox=rgb.getchannel('A').getbbox(),clip_rule='True model alpha exposed outside actual rounded bottom-window alpha, limited to upper rounded-cap/head region y<top+radius. No human silhouette generated geometrically.')

def window_layers(raw,box,radius,matrix,n,head=None,active=False,glow=True):
 layer=v02(raw,matrix,box,radius);edge=blank();gl=blank();plate=blank();q=max(0,min(1,(284-n)/4)) if n>=280 else 1
 if glow and q>0:
  d=ImageDraw.Draw(edge);d.rounded_rectangle(tuple(box),radius=radius,outline=(255,255,255,255),width=3)
  mask=Image.new('L',(W,H));md=ImageDraw.Draw(mask);md.rounded_rectangle(tuple(box),radius=radius,fill=245)
  gl=Image.new('RGBA',(W,H),(212,245,56,255));gl.putalpha(mask.filter(ImageFilter.GaussianBlur(22)));gl=fade(gl,q)
  edge=fade(edge,q)
  if n<281:ImageDraw.Draw(plate).rounded_rectangle((60,700,1020,1118),radius=44,fill=(220,249,104,255))
 f,stats=foreground(raw,head,matrix,box,active,radius,layer.getchannel('A')) if head is not None else (blank(),dict(active=False))
 return dict(backplate=plate,window_glow=gl,bottom_window=layer,window_edge=edge,head_foreground=f),stats

@lru_cache(maxsize=128)
def word_tile(text,path,size,color,stroke=0,shear=0):
 tile=text_image(text,path,size,color)[0];box=tile.getchannel('A').getbbox();tile=tile.crop(box)
 if stroke:
  alpha=tile.getchannel('A');back=Image.new('RGBA',tile.size,(14,14,18,255));back.putalpha(alpha.filter(ImageFilter.MaxFilter(stroke*2+1)));back.alpha_composite(tile);tile=back
 if shear:
  width=tile.width+math.ceil(abs(shear)*tile.height);tile=tile.transform((width,tile.height),Image.Transform.AFFINE,(1,shear,-shear*tile.height if shear>0 else 0,0,1,0),resample=Image.Resampling.BICUBIC)
 return tile

def painted_line(text,path,size,color,top,center=540,shadow=(0,0),stroke=0,shear=0,scale_xy=None):
 tile=word_tile(text,path,size,color,stroke,shear).copy()
 if scale_xy:tile=tile.resize((round(tile.width*scale_xy[0]),round(tile.height*scale_xy[1])),Image.Resampling.LANCZOS)
 a=tile.getchannel('A');layer=blank()
 if shadow!=(0,0):
  shadowim=Image.new('RGBA',tile.size,(38,83,183,255));shadowim.putalpha(a);layer.alpha_composite(shadowim,(round(center-tile.width/2+shadow[0]),round(top+shadow[1])))
 layer.alpha_composite(tile,(round(center-tile.width/2),round(top)));return layer

def title_layers(cfg,n):
 layer=blank();support=blank();warm=cfg['mode']=='baseline' and n==0
 phase=n if cfg['mode']=='baseline' else n/0.8
 if (not cfg.get('title') and not cfg.get('support')) or (phase>=77 and not warm):return dict(title=layer,support=support)
 if warm:phase=40
 if phase<6:return dict(title=layer,support=support)
 shift=float(lerp([(6,[15]),(11,[44]),(14,[50]),(17,[44]),(20,[30]),(25,[13]),(29,[6]),(36,[0]),(71,[0])],phase)[0])*cfg.get('title_motion_scale',1)
 tile=painted_line(cfg['title'],cfg['fonts']['title'],cfg.get('title_size',100),(255,255,255,255),295,540+shift,(9,7),scale_xy=cfg.get('title_scale',[1,1])) if cfg.get('title') else blank()
 q=1 if phase<72 else max(0,(77-phase)/5)
 reveal=max(0,min(1,(phase-5)/26));mask=Image.new('L',(W,H));ImageDraw.Draw(mask).rectangle((0,0,round((275+shift)+530*reveal),H),fill=255)
 tile.putalpha(Image.fromarray(np.uint8(np.asarray(tile.getchannel('A'),dtype=np.float32)*np.asarray(mask)/255)))
 layer=fade(tile,q)
 if cfg.get('support'):
  support=painted_line(cfg['support'],cfg['fonts']['title'],cfg.get('support_size',52),(255,255,255,255),1390,540,(6,5),shear=-.08)
  under=ImageDraw.Draw(support);under.arc((590,1435,730,1468),0,140,fill=(42,86,189,255),width=7)
  # Independent native support prefix, not an opacity fade of all words.
  # Observed source6partial/11oneword/14three/20six/29complete; curve remains approximate.
  progress=float(lerp([(6,[.005]),(11,[.15]),(14,[.40]),(20,[.86]),(24,[1])],phase)[0])
  bb=support.getchannel('A').getbbox();alpha=np.asarray(support.getchannel('A')).copy()
  if bb:alpha[:,round(bb[0]+(bb[2]-bb[0])*progress):]=0
  support.putalpha(Image.fromarray(alpha));support=fade(support,q)
 return dict(title=layer,support=support)