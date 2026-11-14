from PIL import Image,ImageDraw,ImageFilter
import numpy as np
def card_layers(t,cfg):
 roles={r:blank() for r in ['card','card-title','card-items','card-links','card-button','card-conclusion']}
 if not card_active(cfg,t):return roles
 c=cfg['card'];src=False;entry=c['entry'];end=c['exit'];q=out(entry-.04,entry+.32,t)*(1-out(*end,t));items=c['items'];count=len(items)
 if count>4:raise ValueError('More than4 card items needs validated paging')
 rows=2 if count==4 else 1;card_height=464+(rows-1)*110
 ImageDraw.Draw(roles['card']).rounded_rectangle((72,396,1008,396+card_height),radius=40,fill=(248,243,229,255))
 title=ink(c.get('title',''),cfg['fonts']['title'],50,(22,21,17,255));roles['card-title'].alpha_composite(title,(136,469))
 centers=[(255,593),(825,593)] if src and count==2 else ([(540,593)] if count==1 else ([(270,593),(540,593),(810,593)] if count==3 else ([(300,583),(780,583),(300,687),(780,687)] if count==4 else [(280,593),(800,593)])))
 font_size=40 if src else (34 if count==3 else 40)
 for item,(cx,cy) in zip(items,centers):
  at=item['at'];iq=out(at-.04,at+.28,t);face=ink(item['text'],cfg['fonts']['title'],font_size,(22,21,17,255))
  if face.width>(430 if count!=3 else 254):
   text=item['text'];cut=text.find('和')+1
   if cut<=0:raise ValueError('Card item requires semantic wrap rather than distorted glyphs')
   lines=[ink(v,cfg['fonts']['title'],font_size,(22,21,17,255)) for v in [text[:cut],text[cut:]]];face=Image.new('RGBA',(max(v.width for v in lines),sum(v.height for v in lines)+8));yy=0
   for line in lines:face.alpha_composite(line,((face.width-line.width)//2,yy));yy+=line.height+8
   if face.width>254:raise ValueError('Card semantic wrap still overflows')
  if iq<1:face=face.filter(ImageFilter.GaussianBlur((1-iq)*5))
  place(roles['card-items'],face,cx,cy-face.height/2,iq)
 a,b=c['links'];progress=max(0,min(1,(t-a)/(b-a)));button_y=708+(rows-1)*110
 if progress>0:
  d=ImageDraw.Draw(roles['card-links'])
  for cx,cy in centers:
   p0=np.array([cx,cy+33.]);p1=np.array([cx,cy+72.]);p2=np.array([540,button_y-40.]);p3=np.array([540,button_y-4.]);u=np.linspace(0,progress,max(2,round(progress*100)));points=[tuple((1-v)**3*p0+3*(1-v)**2*v*p1+3*(1-v)*v*v*p2+v**3*p3) for v in u];d.line(points,fill=(173,137,40,110),width=2)
 at=c['button_at'];bq=out(at-.04,at+.20,t)
 if bq>0:
  elapsed=t-at;s=(.14+1.02*out(0,.20,elapsed)) if elapsed<.20 else (1.16-.16*out(.20,.36,elapsed))
  tile=Image.new('RGBA',(430,94));ImageDraw.Draw(tile).rounded_rectangle((0,0,429,93),radius=47,fill=(173,137,40,255));text=ink(c.get('button',''),cfg['fonts']['title'],40,(20,18,13,255))
  if text.width>390:raise ValueError('Conclusion too long')
  place(roles['card-button'],tile,540,button_y+(94-94*s)/2,bq,s);place(roles['card-conclusion'],text,540,button_y+(94-text.height*s)/2,bq,s)
 for r in roles:roles[r]=fade(roles[r],q)
 return roles
