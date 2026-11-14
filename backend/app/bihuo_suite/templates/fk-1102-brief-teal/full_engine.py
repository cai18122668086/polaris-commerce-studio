"""Teal full recipe. Real approved first-two runtime/helpers, own late stage clocks."""
from pathlib import Path
from functools import lru_cache
import sys,json,hashlib,copy
sys.dont_write_bytecode=True
import numpy as np
from PIL import Image,ImageDraw,ImageFilter
S=Path(__file__).resolve().parent
from . import topfill_adapter as approved
B=approved.base;W,H=1080,1920;blank=B.blank;fade=B.fade;out=B.out;composite=B.composite
ROLES=['background','card','material','presenter','presenter_glow','card_label','card_items','identity','caption_shadow','caption']
@lru_cache(maxsize=1)
def recovery():return {r['frame']:r for r in json.loads((C/'source-recovery/recovery.json').read_text('utf-8'))['frames']}
@lru_cache(maxsize=1)
def source_geometry():return json.loads((C/'reviews/source-geometry.json').read_text('utf-8'))
def configure(cfg):
 c=copy.deepcopy(cfg)
 if c['mode']=='new':
  catalog=c.get('material_assignments',json.loads((S/'bindings.json').read_text('utf-8'))['catalog']);ids=c.get('uploaded_asset_ids',[]);c['materials']=[]
  for r in catalog:
   if r['asset_id'] in ids:
    assert hashlib.sha256(Path(r['path']).read_bytes()).hexdigest()==r['sha256']
    c['materials'].append({'id':r['asset_id'],'path':r['path'],'sha256':r['sha256'],'start':r['start_ms']/1000,'end':r['end_ms']/1000,'label':r.get('label',''),'scene_role':r.get('scene_role','opening' if r['start_ms']<7000 else 'first-card'),'tokens':[r['first_token_id'],r['last_token_id']]})
  if len(c['materials'])>4:raise ValueError('More than4 assignments requires separately validated stage map')
 return c
def match(cfg,t):return B.match(cfg,t)
def person_box(cfg,t):
 if cfg['mode']=='baseline':return recovery()[round(t*25)]['native_box']
 if t<cfg['return_start'] or any(m.get('scene_role')=='opening' and m['start']-.04<=t<m['end']+.24 for m in cfg['materials']):return approved.person_box(cfg,t)
 first=np.array([0,284,1080,1920],float)
 if t<(cfg['return_start']+.32):
  q=B.ease(cfg['return_start'],(cfg['return_start']+.32),t);return (np.array([0,314,1080,1920])*(1-q)+first*q).tolist()
 info=cfg.get('second_information',{});items=info.get('items',[])
 if not info.get('enabled',True) or not items:return first.tolist()
 a,b=cfg['second_person']['shrink'];c,d=cfg['second_person']['return'];q=B.ease(a,b,t);medium=np.array([295,1150,786,1800],float)
 if t<c:return (first*(1-q)+medium*q).tolist()
 q=B.ease(c,d,t);return (medium*(1-q)+np.array([0,0,1080,1920])*q).tolist()
def person_window(texture,box,glowq=0,radius=30):
 x,y,x2,y2=box;w=x2-x;h=y2-y;key={'time':0,'matrix':[[w/W,0,x/2],[0,h/H,y/2]],'rect':[x/2,y/2,x2/2,y2/2],'radius':radius/2,'background_opacity':0};layer=B.V.render('V02',texture.resize((W,H),Image.Resampling.LANCZOS),0,{'size':[W,H],'fps':25,'stage_color':[5,14,12],'visual_keys':[key]})['presenter'];glow=blank()
 if glowq>0:
  border=blank();ImageDraw.Draw(border).rounded_rectangle(box,radius=radius,outline=B.MINT,width=4);glow=border.convert('RGBa').filter(ImageFilter.GaussianBlur(14)).convert('RGBA');glow.putalpha(glow.getchannel('A').point([min(255,v*5) for v in range(256)]));glow=fade(glow,.9*glowq);glow.alpha_composite(fade(border,glowq))
 return layer,glow
def render_pills(cfg,t):
 result=blank();items=cfg.get('pills',[]);ending=cfg.get('pills_exit',[0,0]);exitq=1-B.ease(*ending,t)
 if not items or exitq<=0:return result
 if len(items)>4:raise ValueError('More than4 pills requires validated paging')
 for i,item in enumerate(items):
  if t<item['start']:continue
  text=B.ink(item['text'],cfg['fonts']['bold'],32,(0,112,87,255) if t<item.get('active_end',ending[1]) else (0,0,0,255));width=text.width+100;height=76;tile=Image.new('RGBA',(width,height));d=ImageDraw.Draw(tile);d.rounded_rectangle((0,0,width-1,height-1),radius=38,fill='white');d.line([(35,39),(41,45),(52,33)],fill=(0,125,97,255),width=3);tile.alpha_composite(text,(72,(height-text.height)//2))
  elapsed=(t-item['start'])*25;scale=float(np.interp(elapsed,[0,1,2,3,4,5],[.15,.45,.71,.92,.98,1]));q=float(np.interp(elapsed,[0,1,2,3],[.35,.85,1,1]));cx=60+width/2;cy=208+i*90
  tile=tile.resize((max(1,round(width*scale)),max(1,round(height*scale))),Image.Resampling.BICUBIC);result.alpha_composite(fade(tile,q),(round(cx-tile.width/2),round(cy-tile.height/2)))
 if t>=ending[0]:result=result.convert('RGBa').filter(ImageFilter.GaussianBlur(min(18,(t-ending[0])*25*3))).convert('RGBA')
 return fade(result,exitq)
def card2(cfg,t):
 card=blank();media=blank();labels=blank();items=blank();c=cfg.get('second_information',{});rows=c.get('items',[])
 if not c.get('enabled',True) or not rows or not c['start']-.04<=t<c['clear']:return card,media,labels,items
 src=cfg['mode']=='baseline';q=B.ease(c['start']-.04,c['near'],t)*(1-B.ease(c['end'],c['clear'],t));matched=next((m for m in cfg['materials'] if m.get('scene_role')=='second-card' and m['start']<=t<m['end']),None) if not src else cfg['materials'][2];has_image=bool(matched)
 rect=[72,478,1008,1029] if src or has_image else [150,600,930,809+75*(len(rows)-1)];imagebox=[134,536,945,829];ImageDraw.Draw(card).rounded_rectangle(rect,radius=42,fill='white')
 if has_image:media=B.image_slot(matched['path'],imagebox,t,radius=28,fit='cover' if src else 'contain')
 top=555 if src or has_image else 625;left=152 if src or has_image else 190;face=B.ink(c['label'],cfg['fonts']['bold'],26,(0,20,16,255));d=ImageDraw.Draw(labels);d.rounded_rectangle([left,top,left+face.width+82,top+54],radius=27,fill=B.MINT);d.rectangle((left+26,top+19,left+42,top+35),outline=(0,20,16,255),width=2);d.line((left+31,top+20,left+31,top+34),fill=(0,20,16,255),width=2);labels.alpha_composite(face,(left+56,top+13));labels=fade(labels,B.ease(c['label_at']-.04,c['label_at']+.24,t))
 ybase=861 if src or has_image else 715
 if len(rows)>4:raise ValueError('More than4 card rows requires separately validated paging')
 # Actual input quantity drives card text, not source two-row count.
 if len(rows)>2 and (src or has_image):
  rect[-1]+=75*(len(rows)-2);card=blank();ImageDraw.Draw(card).rounded_rectangle(rect,radius=42,fill='white')
 for i,row in enumerate(rows):
  layer=blank();yy=ybase+i*75;dd=ImageDraw.Draw(layer);xx=135 if src or has_image else 190;dd.ellipse([xx,yy-8,xx+45,yy+37],fill=(241,244,243,255))
  for dx,dy in [(0,0),(11,0),(0,11),(11,11)]:dd.rectangle([xx+14+dx,yy+5+dy,xx+20+dx,yy+11+dy],outline=(0,158,124,255),width=2)
  B.put(layer,row['text'],cfg['fonts']['bold'],30,xx+67,yy+4,(5,14,11,255));dd.line((rect[0]+63,yy+62,rect[2]-63,yy+62),fill=(235,237,236,255),width=2);items.alpha_composite(fade(layer,B.ease(row['start']-.04,row['near'],t)))
 # Reuse the measured first-card transform sampler at the equivalent local phase,
 # after checking native second-card535→478 entry and upward exit: candidate same family curve.
 proxy=copy.copy(cfg);proxy['mode']='baseline';n=193+(t-c['start'])*25 if t<c['near'] else (248+(t-c['end'])*25 if t>=c['end'] else 220)
 return tuple(fade(B.card_motion(layer,n/25,proxy),q) for layer in [card,media,labels,items])
def render_layers(frame,t,cfg):
 n=round(t*25)
 if cfg['mode']=='new' and t<cfg['return_start']:layers=approved.render_layers(frame,t,cfg)
 else:
  layers={r:blank() for r in ROLES};layers['background']=(B.grid() if cfg['mode']=='baseline' else B.clean_grid()).copy();box=person_box(cfg,t)
  if cfg['mode']=='baseline':
   texture=Image.open(recovery()[n]['texture']).convert('RGBA');glowq=1-out(263/25,267/25,t) if n<371 else out(374/25,387/25,t)*(1-out(477/25,483/25,t));layers['card'],layers['material'],layers['card_label'],layers['card_items']=B.materials(cfg,t);layers['identity']=B.identity(cfg,t)
   if 280<=n<=370:
    fill=texture.resize((W,H)).filter(ImageFilter.GaussianBlur(45));layers['background'].alpha_composite(fill.crop((0,0,W,round(box[1]))),(0,0))
  else:
   texture=B.M._fit(frame.convert('RGBA'),round(box[2]-box[0]),round(box[3]-box[1]),{'fit':'cover','anchor':[.5,.35]});second_enabled=cfg.get('second_information',{}).get('enabled',True) and bool(cfg.get('second_information',{}).get('items'));glowq=B.ease(*cfg['second_person']['shrink'],t)*(1-B.ease(*cfg['second_person']['return'],t)) if second_enabled else 0
   if cfg['return_start']<=t and (t<cfg['second_person']['shrink'][0] or not second_enabled):
    fill=B.M._fit(frame.convert('RGBA'),W,H,{'fit':'cover','anchor':[.5,.35]}).crop((0,0,W,round(box[1]))).filter(ImageFilter.GaussianBlur(45));layers['background'].alpha_composite(fill,(0,0))
  radius=0 if cfg['mode']=='new' and box[0]==0 and box[2]==1080 else 30;layers['presenter'],layers['presenter_glow']=person_window(texture,box,glowq,radius);layers['caption_shadow'],layers['caption']=B.caption(cfg,t)
 if cfg['mode']=='new' and t>=cfg['return_start']:
  _,repeat_media,_,_=B.materials(cfg,t);layers['material'].alpha_composite(repeat_media)
 card,media,label,items=card2(cfg,t)
 for role,layer in zip(['card','material','card_label','card_items'],[card,media,label,items]):layers[role].alpha_composite(layer)
 layers['card_items'].alpha_composite(render_pills(cfg,t))
 if cfg['mode']=='baseline' and n>=563:
  f=source_geometry()['tail_original_light_factors'].get(str(n),0);layers['caption']=fade(layers['caption'],f);layers['caption_shadow']=fade(layers['caption_shadow'],f);bg=np.asarray(layers['background']).copy();bg[:,:,:3]=(bg[:,:,:3].astype(float)*f).clip(0,255).astype('uint8');layers['background']=Image.fromarray(bg)
 if cfg['mode']=='baseline' and n==575:
  layers={r:blank() for r in ROLES};layers['background']=Image.new('RGBA',(W,H),'black')
 return {r:layers[r] for r in ROLES}
