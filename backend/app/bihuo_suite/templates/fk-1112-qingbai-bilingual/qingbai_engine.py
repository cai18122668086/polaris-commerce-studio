"""Qingbai front2 composition; true pinned V02/V03/text + Navy RGBA transport interfaces."""
import sys,json,copy,math
sys.dont_write_bytecode=True
from pathlib import Path
from functools import lru_cache
import cv2,numpy as np
from PIL import Image,ImageDraw,ImageFilter
H=Path(__file__).resolve().parent
from .vendor import qingbai_primitives as T
N=T
from .vendor.apple_minimal import visual as V,media as M
from .vendor.apple_minimal.pilot import font,text_image,ease
SIZE=(1080,1920);blank=T.blank;opacity=T.opacity;normalize=T.normalize
FIT=json.loads((H/'data/layer-fit-candidates-v2.json').read_text(encoding='utf-8'));PREP=json.loads((H/'data/source-preparation.json').read_text(encoding='utf-8'));BOOK=json.loads((H/'data/book-composite-phase-v2.json').read_text(encoding='utf-8'))
BOUNDS={k:[0,0,1080,1920] for k in ['background','cover_plate','picture_book','picture_food','presenter_glow','presenter_border','presenter','title_main','title_support','identity','caption_chinese_shadow','caption_chinese_body','caption_chinese_emphasis','caption_english_shadow','caption_english']}
def active(c,segment):return next((m for m in c['materials'] if m['id'] in c['selected_asset_ids'] and m['semantic_segment']==segment),None)
def active_signature(c):return [(i,active(c,i)['id'] if active(c,i) else None) for i in [0,1]]
def maskrect(rect,radius):
 im=Image.new('L',SIZE);ImageDraw.Draw(im).rounded_rectangle(tuple(round(v) for v in rect),radius=radius,fill=255);return im
@lru_cache(maxsize=2)
def background(warm=False):
 y,x=np.mgrid[0:1920,0:1080];xx=x/1080;yy=y/1920;arr=np.stack([np.ones_like(xx),xx,yy,xx*xx,xx*yy,yy*yy,xx**3,xx*xx*yy,xx*yy*yy,yy**3],axis=-1)@np.array(FIT['stage']['0' if warm else '1']['polynomial_coefficients']);return Image.fromarray(np.uint8(np.clip(np.round(arr),0,255))).convert('RGBA')
def out(a,b,n):t=max(0,min(1,(n-a)/(b-a)));return 1-(1-t)**3
def _old_pose(c,n):
 normal=np.array([97,413,983,1192.]);small=np.array([396,1208,685,1594.]);right=np.array([710,188,1020,601.]);e=c['events'];book=active(c,0);food=active(c,1)
 if c['mode']=='baseline':
  rect=normal*(1-out(*e['person_shrink'],n))+small*out(*e['person_shrink'],n)
  if n>=226:
   if n<=239:
    a=PREP['person_raise_components'][str(n)]['color_component_candidates'][0][1];rect=np.array(a)+[-3,-3,3,3]
   else:
    a=np.array(PREP['person_raise_components']['239']['color_component_candidates'][0][1])+[-3,-3,3,3];q=out(239,247,n);rect=a*(1-q)+right*q
 elif not book and not food:rect=normal
 elif book:
  q=out(*e['person_shrink'],n);rect=normal*(1-q)+small*q
  if food:
   s=226+21*(n-e['person_raise'][0])/(e['person_raise'][1]-e['person_raise'][0]);s=max(225,min(247,s))
   if s<239:
    lo=max(225,math.floor(s));hi=min(239,lo+1);t=s-lo;a=np.array(PREP['person_raise_components'][str(lo)]['color_component_candidates'][0][1])+[-3,-3,3,3];b=np.array(PREP['person_raise_components'][str(hi)]['color_component_candidates'][0][1])+[-3,-3,3,3];mapped=a*(1-t)+b*t;rect=rect if n<e['person_raise'][0] else mapped
   else:
    a=np.array(PREP['person_raise_components']['239']['color_component_candidates'][0][1])+[-3,-3,3,3];q=out(239,247,s);rect=a*(1-q)+right*q
  else:
   q=ease(e['book_exit'][0],e['book_exit'][1]+10,n);rect=rect*(1-q)+normal*q
 else:
  q=ease(*e['person_raise'],n);rect=normal*(1-q)+right*q
 return rect.tolist()
def presenter(c,n,raw):
 rect=pose(c,n);x,y,x2,y2=rect;w=x2-x;h=y2-y;repairs=[]
 if c['mode']=='baseline':
  a=np.asarray(raw).copy();mask=np.zeros((1920,1080),np.uint8)
  if any(cue['tracks'][0]['first']<=n<cue['tracks'][0]['clear'] for cue in c['captions']):mask[1490:1695,:]=255
  mask=cv2.bitwise_and(mask,np.asarray(maskrect(rect,22)));fixed=cv2.inpaint(a,mask,3,cv2.INPAINT_TELEA) if mask.any() else a;texture=Image.fromarray(fixed).crop((round(x+3),round(y+3),round(x2-3),round(y2-3)));target=[x+3,y+3,x2-3,y2-3]
  if mask.any():repairs.append(dict(mask=Image.fromarray(mask),before=raw,after=Image.fromarray(fixed),kind='Source-only burnedCN/EN inside native person window; unknownblouse pixels'))
 else:
  ratio=w/h;ch=min(1080,1080/ratio);cw=ch*ratio;cy=720;top=max(0,cy-ch/2);texture=raw.crop((round(540-cw/2),round(top),round(540+cw/2),round(top+ch)));target=rect
 xx,yy,xx2,yy2=target;key=dict(time=0,matrix=[[(xx2-xx)/1080,0,xx/2],[0,(yy2-yy)/1920,yy/2]],rect=[v/2 for v in target],radius=10,background_opacity=0);person=V.render('V02',texture,0,dict(size=list(SIZE),fps=25,visual_keys=[key]))['presenter'];border=Image.new('RGBA',SIZE,(245,245,240,0));ma=maskrect(rect,22);inside=ma.filter(ImageFilter.MinFilter(5));rim=np.uint8(np.maximum(0,np.asarray(ma).astype(int)-np.asarray(inside).astype(int)));border.putalpha(Image.fromarray(rim));glow=Image.new('RGBA',SIZE,(255,255,255,0));q=ease(c['events']['glow_start']-1,c['events']['glow_start']+1,n) if active(c,1) else 0;glow.putalpha(ma.filter(ImageFilter.GaussianBlur(24)).point(lambda a:round(a*.95*q)))
 return {'presenter_glow':glow,'presenter_border':border,'presenter':person},dict(rect=rect,source_inset_px=3 if c['mode']=='baseline' else 0,no_head_matte=True),repairs
def _old_picture(c,n):
 book=blank();food=blank();e=c['events'];one=active(c,0);two=active(c,1);meta=dict(book_id=None,food_id=None)
 if one:
  en=75+11*(n-e['book_entry'][0])/(e['book_entry'][1]-e['book_entry'][0]);ex=213+10*(n-e['book_exit'][0])/(e['book_exit'][1]-e['book_exit'][0]);entry=np.interp(en,[74]+list(range(75,87))+[87],[0]+[BOOK['entry'][str(i)]['relative_contrast_opacity'] for i in range(75,87)]+[1]);leave=np.interp(ex,[212]+list(range(213,224))+[224],[1]+[BOOK['exit'][str(i)]['relative_contrast_opacity'] for i in range(213,224)]+[0]);q=float(entry*leave)
  if q>0:
   ent=dict(id='book',path=one['path'],type='image',start_frame=0,entry_frames=0,entry_blur=0,rect=[27,82,509.5,577.5],radius=11,fit='cover');book=M.render('V03',None,n,dict(size=list(SIZE),fps=25,media_entries=[ent]))['media-book'];book=opacity(book.filter(ImageFilter.GaussianBlur(12*(1-out(74,86,en)))),q);meta.update(book_id=one['id'],book_opacity_candidate=q,book_blur_separate=True)
 if two and n>=e['food_entry'][0]:
  t=max(231,min(248,231+17*(n-e['food_entry'][0])/(e['food_entry'][1]-e['food_entry'][0])));lo=math.floor(t);hi=min(248,lo+1);f=t-lo;left=FIT['food_boundary'][str(lo)]['top_y'][0]*(1-f)+FIT['food_boundary'][str(hi)]['top_y'][0]*f
  if t<=240:
   def sl(i):r=FIT['food_boundary'][str(i)];return (r['top_y'][1]-r['top_y'][0])/1035
   slope=sl(lo)*(1-f)+sl(hi)*f
  else:slope=(FIT['food_boundary']['240']['top_y'][1]-FIT['food_boundary']['240']['top_y'][0])/1035*(1-ease(240,247,t))
  if t>=247:left=0;slope=0
  left-=40*slope;entry=dict(id='foodtexture',path=two['path'],type='image',start_frame=0,entry_frames=0,entry_blur=0,rect=[0,0,540,960],radius=0,fit='cover');food=M.render('V03',None,n,dict(size=list(SIZE),fps=25,media_entries=[entry]))['media-foodtexture'];poly=np.array([[0,left],[1080,left+1080*slope],[1080,1920],[0,1920]]);food.putalpha(N.quadmask(poly,32));meta.update(food_id=two['id'],food_top_left=left,food_slope_candidate=slope,topline_not_author_angle=True,late_right_proxy_occluded_by_glow=True,stationary_texture_independent_slanted_mask=True)
 return {'picture_book':book,'picture_food':food},meta
def text_run(text,path,size,color,stroke=0,edge=(0,30,36,255)):
 im=text_image(text,path,size,color,stroke,edge)[0];b=im.getchannel('A').getbbox();return im.crop(b) if b else Image.new('RGBA',(1,1))
def mixed_line(text,spans,path,size,emsize=0,stroke=0):
 parts=[]
 for s,active_ in V.caption_parts(dict(text=text,emphasis_spans=spans)):
  im=text_run(s,path,emsize if active_ and emsize else size,(35,194,190,255) if active_ else (255,255,255,255),stroke);parts.append(im)
 width=sum(i.width for i in parts);assert width<1040,(text,width);out=Image.new('RGBA',(width,max(i.height for i in parts)))
 x=0
 for im in parts:out.alpha_composite(im,(x,out.height-im.height));x+=im.width
 return out
def title(c,n):
 main=blank();support=blank();path=c['fonts']['title'];e=c['title_events'];a=ease(e['main_entry'][0]-1,e['main_entry'][1],n)*(1-ease(*e['exit'],n));b=ease(e['support_entry'][0]-1,e['support_entry'][1],n)*(1-ease(*e['exit'],n))
 if c['mode']=='baseline' and n==0:
  for text,spans,y in [('舒服的周末',[[0,2]],318),('不想出门?',[[0,5]],510)]:
   im=mixed_line(text,spans,path,156,156,8);main.alpha_composite(im,(round((1080-im.width)/2),y))
  im=text_run('不用安排满，也能很充实',path,46,(235,235,235,255));ImageDraw.Draw(support).rounded_rectangle((270,712,810,780),radius=34,fill=(31,40,59,255));support.alpha_composite(im,(round((1080-im.width)/2),726));return {'title_main':main,'title_support':support}
 if c['title']:
  size=128
  while font(path,size).getlength(c['title'])+24>970:size-=1
  im=mixed_line(c['title'],c.get('title_emphasis',[]),path,size,size,7);main.alpha_composite(im,(round((1080-im.width)/2),120));main=opacity(main,a)
 if c['support']:
  size=64
  while font(path,size).getlength(c['support'])>970:size-=1
  im=text_run(c['support'],path,size,(35,194,190,255),3);support.alpha_composite(im,(round((1080-im.width)/2),282 if c['title'] else 120));support=opacity(support,b)
 return {'title_main':main,'title_support':support}
def identity(c,n):
 out=blank();v=c['name_card'];name=v.get('name','').strip();desc=v.get('description','').strip()
 if not v.get('enabled',True) or not(name or desc) or n==0:return out
 q=ease(c['identity_events']['entry'][0]-1,c['identity_events']['entry'][1],n)*(1-ease(*c['identity_events']['exit'],n));lines=[(name,72),(desc,42)];tiles=[text_run(t,c['fonts']['body'],s,(10,20,20,255)) for t,s in lines if t];w=max(im.width for im in tiles)+32;hh=sum(im.height+12 for im in tiles)+12
 if c['mode']=='baseline':w=210;hh=180
 assert w<=285;ImageDraw.Draw(out).rectangle((78,1212,78+w,1212+hh),fill=(250,250,247,255));ImageDraw.Draw(out).rectangle((78,1212,85,1212+hh),fill=(30,195,190,255));y=1224
 for im in tiles:out.alpha_composite(im,(94,y));y+=im.height+12
 return opacity(out,q)
def captions(c,n):
 layers={k:blank() for k in ['caption_chinese_body','caption_chinese_emphasis','caption_chinese_shadow','caption_english','caption_english_shadow']};meta={}
 if c['mode']=='baseline':
  cue=next((r for r in c['captions'] if r['tracks'][0]['first']<=n<r['tracks'][0]['clear']),None)
  if cue is None:return layers,meta
  cn,en=cue['tracks'];text=cn['text'];spans=cue['emphasis_spans'];first=cn['first'];steady=cn['steady'];clear=cn['clear'];english=en['text'] if c['english_enabled'] else '';enfirst=en['first'];ensteady=en['steady'];id_=cue['id']
 else:
  cue=next((r for r in c['captions'] if r['range'][0]<=n<r['range'][1]),None)
  if cue is None:return layers,meta
  text=cue['text'];spans=cue['archived_semantic_spans'];first=cue['range'][0];clear=cue['range'][1];steady=min(first+8,math.ceil(clear)-1);english='';enfirst=first;ensteady=steady;id_=cue['id']
 parts=[]
 for s,yes in V.caption_parts(dict(text=text,emphasis_spans=spans)):
  size=76 if yes else 64;im=text_run(s,c['fonts']['body'],size,(35,194,190,255) if yes else (255,255,255,255));parts.append((im,yes,s))
 width=sum(i.width for i,_,_ in parts);assert width<=1040,(text,width);x=round((1080-width)/2);q=ease(first-1,steady,n);runs=[]
 for im,yes,s in parts:
  y=1513 if yes else 1527;layers['caption_chinese_emphasis' if yes else 'caption_chinese_body'].alpha_composite(im,(x,y));runs.append(dict(text=s,emphasis=yes,bounds=[x,y,x+im.width,y+im.height]));x+=im.width
 both=blank();both.alpha_composite(layers['caption_chinese_body']);both.alpha_composite(layers['caption_chinese_emphasis']);mask=both.getchannel('A');shadow=Image.new('L',SIZE);shadow.paste(mask,(3,5));sh=Image.new('RGBA',SIZE,(0,15,20,0));sh.putalpha(shadow.filter(ImageFilter.GaussianBlur(3)));layers['caption_chinese_shadow']=sh
 if english:
  im=text_run(english,c['fonts']['english'],48,(255,255,255,255));assert im.width<=1040;layers['caption_english'].alpha_composite(im,(round((1080-im.width)/2),1604));mask=layers['caption_english'].getchannel('A');shmask=Image.new('L',SIZE);shmask.paste(mask,(2,4));sh=Image.new('RGBA',SIZE,(0,10,15,0));sh.putalpha(shmask.filter(ImageFilter.GaussianBlur(2)));layers['caption_english_shadow']=sh
 for k in ['caption_chinese_body','caption_chinese_emphasis','caption_chinese_shadow']:layers[k]=opacity(layers[k],q)
 for k in ['caption_english','caption_english_shadow']:layers[k]=opacity(layers[k],ease(enfirst-1,ensteady,n))
 return layers,dict(id=id_,text=text,opacity=q,first=first,steady=steady,clear=clear,runs=runs,English=english,English_confirmed=c['mode']=='baseline',new_FA_unchanged=True,wholeline_opacity_not_progressiveglyph=True)
def composite(layers):
 out=blank()
 for im in layers.values():out.alpha_composite(im)
 return out.convert('RGB')
def _old_render_layers(c,n):
 raw=M._sample(dict(path=c['source'],start_frame=0,end_policy='hold'),n,25).convert('RGB');cover=blank();warm=c['mode']=='baseline' and n==0
 if warm:
  cover=Image.open(H/'data/warm-cover-lower-composite.png').convert('RGBA');prs={k:blank() for k in ['presenter_glow','presenter_border','presenter']};pm=dict(source_cover_unreconstructed=True,no_head_matte=True);rep=[]
 else:prs,pm,rep=presenter(c,n,raw)
 pics,picmeta=picture(c,n);caps,capmeta=captions(c,n);layers={'background':background(warm).copy(),'cover_plate':cover,**pics,**prs,**title(c,n),'identity':identity(c,n),**caps};layers={k:normalize(layers[k]) for k in BOUNDS}
 return layers,dict(frame=n,PTS=n/25,person=pm,materials=picmeta,caption=capmeta,active_signature=active_signature(c),source_repair=c['mode']=='baseline',normal_head_matte=False),rep

def pose(c,n):
 if c['mode']=='baseline':
  if n<471:return _old_pose(c,n)
  q=out(471,475,n);return (np.array([710,188,1020,601.])*(1-q)+np.array([398,134,683,514.])*q).tolist()
 normal=np.array([97,413,983,1192.]);rect=normal.copy()
 for m in c['materials']:
  if m['id'] not in c['selected_asset_ids']:continue
  target=np.array([396,1208,685,1594.]) if m['semantic_segment']==0 else np.array([398,134,683,514.]) if m['semantic_segment']>=3 else np.array([710,188,1020,601.])
  q=out(m['start'],m['start']+20,n)*(1-out(m['end'],m['end']+12,n))
  if q>0:rect=rect*(1-q)+target*q
 return rect.tolist()

def _fit_picture(m,n,rect,radius):
 # Same contain+same-image soft fill principle as the approved fit-v2.
 def draw(tag,box,fit):
  e=dict(id=tag,path=m['path'],type=m.get('media_type','image'),start_frame=m.get('start',0),source_in=0,end_policy='hold',entry_frames=0,entry_blur=0,rect=[v/2 for v in box],radius=radius/2,fit=fit)
  return M.render('V03',None,n,dict(size=list(SIZE),fps=25,media_entries=[e]))['media-'+tag]
 fill=draw('fill',rect,'cover');a=fill.getchannel('A');fill=fill.filter(ImageFilter.GaussianBlur(32));fill.putalpha(a)
 clear=draw('clear',rect,'contain');fill.alpha_composite(clear);return fill

def picture(c,n):
 old,meta=_old_picture(c,n);layers=dict(old)
 for role,seg in [('picture_book',0),('picture_food',1)]:
  m=active(c,seg)
  if not m:continue
  if c['mode']!='baseline':
   q=1-ease(m['end']-8,m['end'],n)
   if n<m['start'] or q<=0:layers[role]=blank();continue
   rect=[54,164,1019,1155] if seg==0 else [0,0,1080,1920]
   im=_fit_picture(m,n,rect,22 if seg==0 else 0)
   if seg==0:
    en=75+11*(n-c['events']['book_entry'][0])/(c['events']['book_entry'][1]-c['events']['book_entry'][0]);im=im.filter(ImageFilter.GaussianBlur(12*(1-out(74,86,en))))
   im.putalpha(layers[role].getchannel('A'));layers[role]=opacity(im,q)
 walk=active(c,2);bed=active(c,3)
 if c['mode']=='baseline' and n>=365:
  q=out(365,379,n);food=layers['picture_food'];food=food.resize((1080,max(1,round(1920*(1-q)+951*q))),Image.Resampling.BICUBIC);plane=blank();plane.alpha_composite(food,(0,0));layers['picture_food']=plane
 for kind,m,rect in [('walk',walk,[0,969,1080,1920]),('bed',bed,[58,568,1020,1483])]:
  if not m or not m['start']<=n<m['end']:continue
  q=out(m['start'],m['start']+14,n);last=1-ease(m['end']-11,m['end'],n)
  if kind=='bed':rect=np.array(rect)+np.array([0,180,0,180])*(1-q)
  im=_fit_picture(m,n,rect,30) if c['mode']!='baseline' else next(iter(M.render('V03',None,n,dict(size=list(SIZE),fps=25,media_entries=[dict(id=kind,path=m['path'],type='image',start_frame=0,rect=[float(v)/2 for v in rect],radius=15,fit='cover',entry_frames=0,entry_blur=0)])).values()))
  if kind=='walk':
   ma=Image.new('L',SIZE);ImageDraw.Draw(ma).rounded_rectangle((0,round(1920-951*q),1080,1920),radius=30,fill=255)
   from PIL import ImageChops
   im.putalpha(ImageChops.multiply(im.getchannel('A'),ma))
  layers['picture_'+kind]=opacity(im,q*last)
 if c['mode']=='baseline':
  if n>=458:
   q=1-ease(458,469,n)
   for k in ['picture_food','picture_walk']:
    if k in layers:layers[k]=opacity(layers[k],q)
 return layers,meta

_legacy_captions=captions
def captions(c,n):
 if c['mode']=='baseline':return _legacy_captions(c,n)
 names=['caption_chinese_body','caption_chinese_emphasis','caption_chinese_shadow','caption_english','caption_english_shadow'];roles={k:blank() for k in names}
 row=next((r for r in c['captions'] if r['range'][0]<=n<r['range'][1]),None)
 if row is None:return roles,{}
 lines=row.get('lines') or [dict(text=row['text'],emphasis_spans=row['archived_semantic_spans'])];path=c['fonts']['body'];body=c.get('caption_size',64);q=ease(row['range'][0]-1,min(row['range'][0]+8,math.ceil(row['range'][1])-1),n)
 for index,line in enumerate(lines):
  parts=[]
  for s,yes in V.caption_parts(line):parts.append((text_run(s,path,body+12 if yes else body,(35,194,190,255) if yes else (255,255,255,255)),yes))
  width=sum(im.width for im,_ in parts);assert width<=1040;xx=round((1080-width)/2)
  for im,yes in parts:
   yy=1513+index*92-(len(lines)-1)*92+(0 if yes else 14);roles['caption_chinese_emphasis' if yes else 'caption_chinese_body'].alpha_composite(im,(xx,yy));xx+=im.width
 both=blank();both.alpha_composite(roles['caption_chinese_body']);both.alpha_composite(roles['caption_chinese_emphasis']);mask=Image.new('L',SIZE);mask.paste(both.getchannel('A'),(3,5));shadow=Image.new('RGBA',SIZE,(0,15,20,0));shadow.putalpha(mask.filter(ImageFilter.GaussianBlur(3)));roles['caption_chinese_shadow']=shadow
 for key in names:roles[key]=opacity(roles[key],q)
 return roles,dict(id=row['id'],wholeline_opacity_not_progressiveglyph=True,English='',FA_unchanged=True)

def render_layers(c,n):
 raw=M._sample(dict(path=c['source'],start_frame=0,end_policy='hold'),n,25).convert('RGB');warm=c['mode']=='baseline' and n==0;cover=blank()
 if warm:cover=Image.open(H/'data/warm-cover-lower-composite.png').convert('RGBA');prs={k:blank() for k in ['presenter_glow','presenter_border','presenter']};pm={};rep=[]
 else:prs,pm,rep=presenter(c,n,raw)
 pictures,picmeta=picture(c,n);caps,cm=captions(c,n);layers=dict(background=background(warm).copy(),cover_plate=cover,**pictures,**prs,**title(c,n),identity=identity(c,n),**caps)
 if c['mode']=='baseline' and n>=471:layers['presenter_glow']=blank()
 if n>=c.get('fade_start',10**9):
  q=max(0,min(1,(c['black_at']-n)/max(1,c['black_at']-c['fade_start'])))
  for key,im in layers.items():
   if c['mode']=='baseline' and key=='presenter':continue
   arr=np.array(im);arr[:,:,:3]=np.round(arr[:,:,:3].astype(float)*q).astype(np.uint8);layers[key]=Image.fromarray(arr)
 if n>=c.get('black_at',10**9):layers={k:blank() for k in layers}
 return layers,dict(frame=n,PTS=n/25,person=pm,caption=cm,materials=picmeta,no_head_matte=True),rep
