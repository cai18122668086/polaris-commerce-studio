"""Orange derivative front2. Pinned V02/V03, Paper texture, Qingci glyphclock and Navy atlas reuse."""
import sys,json,math,importlib.util
sys.dont_write_bytecode=True
from pathlib import Path
from functools import lru_cache
import numpy as np,cv2
from PIL import Image,ImageDraw,ImageFilter
H=Path(__file__).resolve().parent
from .vendor import paper_primitives as PP,glyph_caption as CAP,qingbai_primitives as T
from .vendor.apple_minimal import visual as V,media as M
from .vendor.apple_minimal.pilot import font,text_image,ease
SIZE=(1080,1920);blank=T.blank;normalize=T.normalize;opacity=T.opacity;PREP=json.loads((H/'data/source-preparation.json').read_text(encoding='utf-8'))
BOUNDS={'background':[0,0,1080,1920],'blur_material_0':[0,0,1080,1920],'blur_material_1':[0,0,1080,1920],'material_0':[20,300,1060,1390],'material_1':[20,300,1060,1390],'info_plate_0':[20,300,1060,1390],'info_text_0':[20,300,1060,1390],'info_plate_1':[20,300,1060,1390],'info_text_1':[20,300,1060,1390],'presenter_glow':[0,100,1080,1460],'presenter':[60,100,1020,1410],'title_halo':[50,60,1030,275],'title_main':[50,60,1030,275],'topic_pill':[60,80,1020,430],'topic_support':[60,80,1020,430],'identity':[110,1080,440,1335],'caption_shadow':[0,1390,1080,1720],'caption':[0,1400,1080,1705]}
LAYER_ORDER=['background','blur_material_0','blur_material_1','info_plate_0','material_0','info_text_0','info_plate_1','material_1','info_text_1','presenter_glow','presenter','title_halo','title_main','topic_pill','topic_support','identity','caption_shadow','caption']
def out(a,b,n):q=max(0,min(1,(n-a)/(b-a)));return 1-(1-q)**3
def asset(c,i):
 s=c['phases'][i]
 if not s['enabled']:return None
 return next((m for m in c['materials'] if m['id']==s['asset_id'] and m['id'] in c['selected_asset_ids'] and m['semantic_segment']==i),None)
def meaningful(c,i):s=c['phases'][i];return s['enabled'] and bool(asset(c,i) or s['note_title'].strip() or s['note_detail'].strip())
def active_signature(c):return [dict(phase=i,enabled=meaningful(c,i),asset_id=asset(c,i)['id'] if asset(c,i) else None,note_title=c['phases'][i]['note_title'].strip(),note_detail=c['phases'][i]['note_detail'].strip()) for i in range(len(c['phases']))]
@lru_cache(maxsize=2)
def paper(original):
 if original:return Image.open(H/'data/source-paper.png').convert('RGBA')
 a=np.asarray(PP.paper().convert('RGB')).astype(float);palette=np.array(PREP['source_repairs'][-1]['palette_RGB']);a+=palette-np.mean(a,axis=(0,1));return Image.fromarray(np.uint8(np.clip(a,0,255))).convert('RGBA')
def phase(c,i,n):
 s=c['phases'][i];return out(s['entry'][0]-1,s['entry'][1],n)*(1-ease(s['exit'][0]-1,s['exit'][1],n)) if meaningful(c,i) else 0
def media_layer(path,rect,radius=0,fit='cover',id='image'):
 entry=dict(id=id,path=path,type='image',start_frame=0,entry_frames=0,entry_blur=0,rect=[v/2 for v in rect],radius=radius/2,fit=fit);return M.render('V03',None,0,dict(size=list(SIZE),fps=25,media_entries=[entry]))['media-'+id]
def pixel_phase(im,rect,q):
 # Nativepart expands around its ownmaterialcenter, not canvascenter.
 if q<=0:return blank()
 x,y,x2,y2=rect;scale=.25+.75*q;part=im.crop(tuple(round(v) for v in rect));part=part.resize((max(1,round((x2-x)*scale)),max(1,round((y2-y)*scale))),Image.Resampling.LANCZOS);out_=blank();out_.alpha_composite(part,(round((x+x2-part.width)/2),round((y+y2-part.height)/2)));return opacity(out_,q)
def ink(text,path,size,fill,stroke=0):return PP.ink(text,path,size,fill,stroke)
def fitink(text,path,size,width,color):
 while font(path,size).getlength(text)>width and size>28:size-=1
 return ink(text,path,size,color),size
def _old_materials(c,n):
 roles={k:blank() for k in ['blur_material_0','blur_material_1','material_0','material_1','info_plate_0','info_text_0','info_plate_1','info_text_1']};meta=[]
 for i,s in enumerate(c['phases']):
  m=asset(c,i);q=phase(c,i,n);note=bool(s['note_title'].strip() or s['note_detail'].strip());entryq=out(s['entry'][0]-1,s['entry'][1],n);leave=1-ease(s['exit'][0]-1,s['exit'][1],n)
  if m:
   bgq=out(s['background_entry'][0]-1,s['background_entry'][1],n)*(1-ease(s['background_exit'][0]-1,s['background_exit'][1],n));bg=media_layer(m['path'],[0,0,1080,1920]);roles[f'blur_material_{i}']=opacity(bg.filter(ImageFilter.GaussianBlur(32)),bgq)
  if q<=0:meta.append(dict(phase=i,asset_id=m['id'] if m else None,visible=False,meaningful=meaningful(c,i)));continue
  plate=blank();words=blank();photo=blank();rect=[54,355,1026,1327]
  if m:
   if c['mode']=='baseline':
    photo=media_layer(m['path'],rect,30 if i else 0);ImageDraw.Draw(photo).rectangle(tuple(rect),outline=(248,247,240,255),width=2)
   else:
    ImageDraw.Draw(plate).rounded_rectangle(tuple(rect),radius=26,fill=(240,229,208,255),outline=(252,249,239,255),width=3);photo=media_layer(m['path'],[70,460,1010,1307],18,'contain');path=c['fonts']['title'];title,_=fitink(s['note_title'].strip(),path,44,560,(61,43,24,255));words.alpha_composite(title,(440,372));example,_=fitink(s['example'],path,30,380,(99,70,40,255));words.alpha_composite(example,(1010-example.width,380));detail,_=fitink(s['note_detail'].strip(),path,32,560,(71,52,32,255));words.alpha_composite(detail,(440,424))
  elif note:
   rect=[450,550,1026,830 if s['note_title'].strip() and s['note_detail'].strip() else 750];ImageDraw.Draw(plate).rounded_rectangle(tuple(rect),radius=26,fill=(244,233,213,255),outline=(252,249,239,255),width=3);y=600;path=c['fonts']['title']
   for text,size in [(s['note_title'].strip(),64),(s['note_detail'].strip(),44)]:
    if not text:continue
    im,_=fitink(text,path,size,520,(65,45,25,255));words.alpha_composite(im,(round((rect[0]+rect[2]-im.width)/2),y));y+=100
  for key,im in [(f'material_{i}',photo),(f'info_plate_{i}',plate),(f'info_text_{i}',words)]:roles[key]=pixel_phase(im,rect,entryq);roles[key]=opacity(roles[key],leave)
  # Panel behind photo, text ahead; zorder is explicitly corrected by render_layers.
  meta.append(dict(phase=i,asset_id=m['id'] if m else None,visible=True,q=q,note_only=not bool(m),rectangle=rect,notes_independent_of_upload_count=True,example_is_different_SKU=i==1 and c['mode']=='replacement'))
 return roles,meta
def _old_pose(c,n):
 normal=np.array([102,508,894,868.]);circle=np.array([86,164,324,324.]);eligible=[s for i,s in enumerate(c['phases']) if meaningful(c,i)]
 if not eligible:return normal.tolist(),20,0
 first=eligible[0];a,b=first['person_entry'];mapped=58+(n-a)*22/(b-a);q=0 if n<a else out(57.75,78,mapped)
 if c['mode']=='replacement':
  last=max(s['background_exit'][1] for s in eligible);q*=1-ease(last+1,last+19,n)
  if not any(asset(c,i) for i in range(len(c['phases']))):circle[1]=508
 rect=normal*(1-q)+circle*q;corner=20+(min(rect[2:])/2-20)*ease(58,68,mapped);return rect.tolist(),corner,q
def _old_presenter(c,n,raw):
 rect,r,q=pose(c,n);x,y,w,h=rect;shape=Image.new('L',SIZE);ImageDraw.Draw(shape).rounded_rectangle((round(x),round(y),round(x+w),round(y+h)),radius=r,fill=255);rep=[]
 if c['mode']=='baseline':
  a=np.asarray(raw);mask=np.zeros((1920,1080),np.uint8)
  if n==0 or 3<=n<57:
   hsv=cv2.cvtColor(a,cv2.COLOR_RGB2HSV); local=((hsv[:,:,1]<80)&(hsv[:,:,2]>170)).astype(np.uint8)*255; roi=np.zeros_like(local);roi[1130:1275,135:290]=255;mask=cv2.dilate(cv2.bitwise_and(local,roi),np.ones((3,3),np.uint8),iterations=1)
  if 58<=n<76:mask[93:233,85:1000]=255;mask[298:408,280:800]=255
  mask=cv2.bitwise_and(mask,np.asarray(shape));fixed=cv2.inpaint(a,mask,3,cv2.INPAINT_TELEA) if mask.any() else a;im=blank();box=(round(x),round(y),round(x+w),round(y+h));im.paste(Image.fromarray(fixed).crop(box).convert('RGBA'),box[:2]);im.putalpha(shape)
  if mask.any():rep.append(dict(mask=Image.fromarray(mask),before=raw,after=Image.fromarray(fixed),kind='Source-only identity/titleburn inside nativevideo; forehead/hair behindpill unknown, not authorraw'))
 else:
  ratio=w/h;ch=min(1080,1080/ratio);cw=ch*ratio;top=max(0,720-ch/2);texture=raw.crop((round(540-cw/2),round(top),round(540+cw/2),round(top+ch)));key=dict(time=0,matrix=[[w/1080,0,x/2],[0,h/1920,y/2]],rect=[x/2,y/2,(x+w)/2,(y+h)/2],radius=r/2,background_opacity=0);im=V.render('V02',texture,0,dict(size=list(SIZE),fps=25,visual_keys=[key]))['presenter']
 glow=Image.new('RGBA',SIZE,(255,255,255,0));glow.putalpha(shape.filter(ImageFilter.GaussianBlur(22)).point(lambda v:round(v*.95*q)));return {'presenter_glow':glow,'presenter':im},dict(rect_xywh=rect,radius=r,shape_is_video_window_not_head_matte=True,layout_q=q),rep
def titles(c,n):
 main=blank();halo=blank();pill=blank();support=blank();e=c['title_events'];q=1 if c['mode']=='baseline' and n==0 else ease(e['entry'][0]-1,e['entry'][1],n)*(1-ease(e['exit'][0]-1,e['exit'][1],n));p=1-ease(e['exit'][0]-1,e['exit'][1],n);path=c['fonts']['title']
 if c['title'].strip():
  im,_=fitink(c['title'],path,110,925,(255,255,252,255));# Inkhelper providesnaturalmetrics; outline explicitly separatemask.
  tile=text_image(c['title'],path,110,(255,255,252,255),5,(76,48,13,255))[0];bb=tile.getchannel('A').getbbox();tile=tile.crop(bb);main.alpha_composite(tile,(round((1080-tile.width)/2),100));mask=main.getchannel('A').filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(1));halo=Image.new('RGBA',SIZE,(252,246,219,0));halo.putalpha(mask);halo=opacity(halo,q*.7);main=opacity(main,q)
 if c['support'].strip():
  im,_=fitink(c['support'],path,64,860,(255,255,251,255));ww=516 if c['mode']=='baseline' else im.width+64;yy=300 if c['title'].strip() else 100;ImageDraw.Draw(pill).rounded_rectangle(((1080-ww)/2,yy,(1080+ww)/2,yy+106),radius=53,fill=(34,29,31,245));support.alpha_composite(im,(round((1080-im.width)/2),round(yy+(106-im.height)/2)));pill=opacity(pill,p if c['mode']=='baseline' else q);support=opacity(support,q)
 return {'title_halo':halo,'title_main':main,'topic_pill':pill,'topic_support':support}
def identity(c,n):
 im=blank();v=c['identity'];name=v['name'].strip();desc=v['description'].strip()
 if not v['enabled'] or not(name or desc) or(c['mode']=='baseline' and n in [1,2]):return im
 q=1 if c['mode']=='baseline' and n==0 else ease(v['entry'][0]-1,v['entry'][1],n)*(1-ease(v['exit'][0]-1,v['exit'][1],n));path=c['fonts']['body'];y=1146
 for text,size in [(name,54),(desc,34)]:
  if not text:continue
  tile=ink(text,path,size,(255,255,255,255));assert tile.width<290;im.alpha_composite(tile,(140,y));y+=70
 if name and desc:ImageDraw.Draw(im).line((140,1207,300,1207),fill='white',width=2)
 if n<v['entry'][1] and not(c['mode']=='baseline' and n==0):
  # Source only proveslocalclip/position+alpha, not an exactauthorcurve.
  opening=out(v['entry'][0]-1,v['entry'][1],n);clip=Image.new('L',SIZE);ImageDraw.Draw(clip).rectangle((round(300-170*opening),1080,440,1335),fill=255);a=np.asarray(im).copy();a[:,:,3]=np.minimum(a[:,:,3],np.asarray(clip));im=Image.fromarray(a)
 return opacity(im,q)
def _old_captions(c,n):
 cc=dict(c);cc['caption_style']=dict(body_size=c['body_size'],emphasis_size=c['body_size'],body_fill=[255,255,255,255],emphasis_fill=[255,255,255,255],stroke=1,baseline=c['caption_baseline'],line_gap=c['caption_line_gap'],shadow=False,grow_from=1,glyph_entry_frames=4)
 if c['mode']=='baseline' and n==0:cc['captions']=[dict(id='warm-not-speechcue',text='来山西旅游',range=[0,1],glyph_firsts=[-10,-10,-10,100,100],emphasis_spans=[])]
 layer,meta=CAP.original_caption(cc,n) if c['mode']=='baseline' else CAP.caption(cc,n);mask=layer.getchannel('A');shift=Image.new('L',SIZE);shift.paste(mask,(2,3));shadow=Image.new('RGBA',SIZE,(45,32,18,0));shadow.putalpha(shift.filter(ImageFilter.GaussianBlur(1.5)).point(lambda v:round(v*.65)));return {'caption_shadow':shadow,'caption':layer},meta
def composite(layers):
 out_=blank()
 for im in layers.values():out_.alpha_composite(im)
 return out_.convert('RGB')
def _old_render_layers(c,n):
 raw=M._sample(dict(path=c['source'],start_frame=0,end_policy='hold'),n,25).convert('RGB');mat,mm=materials(c,n);person,pm,rep=presenter(c,n,raw);caps,cm=captions(c,n);layers={'background':paper(c['mode']=='baseline').copy(),**mat,**person,**titles(c,n),'identity':identity(c,n),**caps};# Plates must precede images; headertext remainsinfront.
 layers={k:normalize(layers[k]) for k in LAYER_ORDER}
 return layers,dict(frame=n,PTS=n/25,person=pm,materials=mm,caption=cm,English_generated=False,source_repairs_only=c['mode']=='baseline',active_signature=active_signature(c)),rep

def pose(c,n):
 normal=np.array([102,508,894,868.]);circle=np.array([86,164,324,324.]);full=np.array([0,0,1080,1920.]);lower=np.array([292,1257,498,376.])
 if c['mode']=='baseline':
  if n<243:return _old_pose(c,n)
  if n<265:q=out(243,264,n);rect=circle*(1-q)+full*q;return rect.tolist(),162*(1-q),1-q
  if n<319:return full.tolist(),0,0
  if n<339:q=out(319,338,n);return (full*(1-q)+lower*q).tolist(),18*q,1
  if n<428:return lower.tolist(),18,1
  q=out(428,448,n);return (lower*(1-q)+circle*q).tolist(),18+144*q,1
 rect=normal.copy();radius=20;glow=0
 for i,s in enumerate(c['phases']):
  if not meaningful(c,i):continue
  start,end=s['person_entry'];leave=s['background_exit'][1];q=out(start,end,n)*(1-ease(leave+1,leave+19,n))
  target=lower if i in [2,3] else circle.copy()
  if not asset(c,i) and i<2:target[1]=508
  if q>0:rect=rect*(1-q)+target*q;radius=20+(min(target[2:])/2-20)*q if i not in [2,3] else 18;glow=max(glow,q)
 return rect.tolist(),radius,glow

def presenter(c,n,raw):
 roles,meta,rep=_old_presenter(c,n,raw)
 if c['mode']!='baseline' or n<243:return roles,meta,rep
 rect,r,_=pose(c,n);x,y,w,h=rect;shape=Image.new('L',SIZE);ImageDraw.Draw(shape).rounded_rectangle((round(x),round(y),round(x+w),round(y+h)),radius=r,fill=255)
 cap,_=captions(c,n);support=np.asarray(cap['caption'].getchannel('A'));arr=np.asarray(raw);white=(arr.max(2).astype(int)-arr.min(2).astype(int)<65)&(arr.min(2)>110);mask=cv2.dilate(((support>1)&white).astype(np.uint8)*255,np.ones((7,7),np.uint8));mask=cv2.bitwise_and(mask,np.array(shape));fixed=cv2.inpaint(arr,mask,3,cv2.INPAINT_TELEA) if mask.any() else arr
 im=blank();box=(round(x),round(y),round(x+w),round(y+h));im.paste(Image.fromarray(fixed).crop(box).convert('RGBA'),box[:2]);im.putalpha(shape);roles['presenter']=im
 if mask.any() and c.get('repair_dir') and n in [250,264,319,325,328,331,338,429]:
  folder=Path(c['repair_dir']);folder.mkdir(parents=True,exist_ok=True);Image.fromarray(mask).save(folder/f'f{n:04}-mask.png');Image.fromarray(np.abs(arr.astype(int)-fixed.astype(int)).astype(np.uint8)).save(folder/f'f{n:04}-diff.png')
 return roles,meta,rep

def materials(c,n):
 first=dict(c,phases=c['phases'][:2]);roles,meta=_old_materials(first,n)
 for i,s in enumerate(c['phases'][2:],2):
  m=asset(c,i);q=phase(c,i,n);entryq=out(s['entry'][0]-1,s['entry'][1],n);leave=1-ease(s['exit'][0]-1,s['exit'][1],n)
  keys=[f'blur_material_{i}',f'material_{i}',f'info_plate_{i}',f'info_text_{i}'];roles.update({k:blank() for k in keys})
  if m:
   bq=out(s['background_entry'][0]-1,s['background_entry'][1],n)*(1-ease(s['background_exit'][0]-1,s['background_exit'][1],n));roles[keys[0]]=opacity(media_layer(m['path'],[0,0,1080,1920]).filter(ImageFilter.GaussianBlur(32)),bq)
  if q<=0:continue
  rect=[44,96,1038,974] if i==2 else [44,156,610,910] if i==3 else [54,355,1026,1327]
  if i==2 and len(c['phases'])>3:
   t=out(c['phases'][3]['entry'][0],c['phases'][3]['entry'][1],n);rect=(np.array(rect)*(1-t)+np.array([610,228,1038,840])*t).tolist()
  if m:im=media_layer(m['path'],rect,26,'cover' if c['mode']=='baseline' else 'contain')
  else:
   im=blank();ImageDraw.Draw(im).rounded_rectangle(tuple(rect),radius=26,fill=(244,233,213,255),outline=(252,249,239,255),width=3)
  if i in [2,3] and entryq<1:
   x,y,x2,y2=rect;w=x2-x;hh=y2-y;src=np.float32([[x,y],[x2,y],[x2,y2],[x,y2]]);initial=np.float32([[-w,y+hh*.15],[x+w*.2,y],[x+w*.28,y2-hh*.1],[-w,y2]])
   dst=initial*(1-entryq)+src*entryq;mat=cv2.getPerspectiveTransform(src,dst);im=Image.fromarray(cv2.warpPerspective(np.asarray(im.convert('RGBa')),mat,SIZE,flags=cv2.INTER_CUBIC),'RGBa').convert('RGBA');im=opacity(im,entryq*leave)
  else:im=opacity(pixel_phase(im,rect,entryq),leave)
  roles[keys[1] if m else keys[2]]=im
  if s['note_title'].strip() or s['note_detail'].strip():
   words=blank();yy=rect[1]+36
   for text,size_ in [(s['note_title'],56),(s['note_detail'],38)]:
    if not text.strip():continue
    tile,_=fitink(text,c['fonts']['title'],size_,rect[2]-rect[0]-50,(65,45,25,255));words.alpha_composite(tile,(round((rect[0]+rect[2]-tile.width)/2),round(yy)));yy+=100
   roles[keys[3]]=opacity(words,q)
  meta.append(dict(phase=i,actual_asset_id=m['id'] if m else None,rect=rect,entry_perspective=i in [2,3],text_without_image=not bool(m)))
 return roles,meta

def captions(c,n):
 local=dict(c);upper=False
 if c['mode']=='baseline':upper=322<=n<427
 else:upper=any(i in [2,3] and meaningful(c,i) and s['entry'][0]<=n<s['exit'][1] for i,s in enumerate(c['phases']))
 local['caption_baseline']=1140 if upper else c['caption_baseline']
 return _old_captions(local,n)

def render_layers(c,n):
 raw=M._sample(dict(path=c['source'],start_frame=0,end_policy='hold'),n,25).convert('RGB');mat,mm=materials(c,n);person,pm,rep=presenter(c,n,raw);caps,cm=captions(c,n);roles={'background':paper(c['mode']=='baseline').copy()}
 for i in range(len(c['phases'])):
  key=f'blur_material_{i}'
  if key in mat:roles[key]=mat[key]
 for i in range(len(c['phases'])):
  for key in [f'info_plate_{i}',f'material_{i}',f'info_text_{i}']:
   if key in mat:roles[key]=mat[key]
 roles.update(person);roles.update(titles(c,n));roles['identity']=identity(c,n);roles.update(caps)
 if n>=c.get('fade_start',10**9):
  q=max(0,min(1,(c['black_at']-n)/max(1,c['black_at']-c['fade_start'])))
  for key,im in roles.items():
   if c['mode']=='baseline' and key=='presenter':continue
   a=np.array(im);a[:,:,:3]=np.round(a[:,:,:3]*q).astype(np.uint8);roles[key]=Image.fromarray(a)
 if n>=c.get('black_at',10**9):roles={k:blank() for k in roles}
 return roles,dict(frame=n,PTS=n/25,person=pm,materials=mm,caption=cm,English_generated=False,active_signature=active_signature(c)),rep

