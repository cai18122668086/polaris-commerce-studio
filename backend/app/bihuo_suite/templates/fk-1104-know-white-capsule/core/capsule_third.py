import numpy as np
from PIL import Image,ImageDraw
from . import capsule_engine as K
def transform_card(layer,q,scale,blur,cfg):
 if scale!=1:
  height=189+99*len(cfg['third']['items'])+19;tile=layer.crop((60,352,1020,352+height));tile=tile.convert('RGBa').resize((max(1,round(tile.width*scale)),max(1,round(tile.height*scale))),Image.Resampling.LANCZOS).convert('RGBA');out=K.blank(cfg);cx,cy=540,352+height/2;out.alpha_composite(tile,(round(cx-tile.width/2),round(cy-tile.height/2)));layer=out
 return K.alpha(layer,q,blur)

def third_layers(cfg,n):
 t=n/25;data=cfg['third'];items=data.get('items',[]);roles={k:K.blank(cfg)for k in['third_plate','third_rules','third_title','third_rows']}
 if not items or t<data['title_at']:return roles,dict(active=False)
 qs=K.ease(data['title_at']-.04,data['title_at']+.20,t);qp=K.ease(data['plate_at']-.04,data['settle_at'],t);h=189+99*len(items)+19
 if 352+h>1000:raise ValueError('Explicit third-card item capacity exceeded; split input instead of squeezing text')
 ImageDraw.Draw(roles['third_plate']).rounded_rectangle((60,352,1019,352+h),radius=48,fill='white');roles['third_plate']=K.alpha(roles['third_plate'],qp)
 for i in range(len(items)-1):ImageDraw.Draw(roles['third_rules']).line((125,603+i*99,955,603+i*99),fill=(231,231,231,255),width=2)
 roles['third_rules']=K.alpha(roles['third_rules'],qp)
 K.text_at(roles['third_title'],data['title'],cfg['fonts']['title'],48,125,418,(0,0,0,255));roles['third_title']=K.alpha(roles['third_title'],qs,(1-qs)*5)
 current=max([i for i,row in enumerate(items)if t>=row['at']],default=-1);rowmeta=[]
 for i,row in enumerate(items):
  q=K.ease(row['at']-.04,row['at']+cfg.get('third_reveal_duration',.28)-.04,t)
  if q<=0:continue
  layer=K.blank(cfg);color=(38,93,232,255)if i==current else(0,0,0,255);path=cfg['fonts'].get('third_body',cfg['fonts']['title']);lines,s=K.fit_lines(row['text'],path,34,820,2,30)
  for j,line in enumerate(lines):K.text_at(layer,line,path,s,125,541+i*99+j*s*1.25,color)
  roles['third_rows'].alpha_composite(K.alpha(layer,q,(1-q)*6));rowmeta.append(dict(index=i,text=row['text'],blue=i==current,opacity=q))
 start,end=data['tail_start'],data['tail_end'];z=max(0,min(1,(n-start)/(end-start)));scale=1-.45*z*z;op=(1-z)**2;blur=z*10
 if z:
  roles={k:transform_card(v,op,scale,blur,cfg)for k,v in roles.items()}
 return roles,dict(active=True,rows=rowmeta,current_blue=current,plate_h=h,tail_scale=scale,tail_opacity=op,tail_blur=blur)
