"""One editable capsule-list expression with honest shared group post-effects.

Raw geometry/text leaves -> joint row/footer groups -> joint card blur/alpha.
No legacy renderer, person/source sampler, asset loader, planner or identity.
"""
import copy,hashlib,inspect,math
from pathlib import Path
from PIL import Image,ImageDraw,ImageFilter
import numpy as np
from ...vendor.apple_minimal.pilot import font,text_image,ease

SCHEMA='motion.capsule-list/1-candidate'
PILOT_SHA='1a2d7f7d2fb4abc6ab8b22ed917925769a2c266e90f87af366e00b2d5335ea42'
GEOMETRY=dict(panel_x=54,panel_y=289,panel_width=972,panel_radius=48,panel_min_height=390,max_bottom=1000,entry_slide=100,inner_top=66,title_x=120,title_size=48,title_line_height=1.18,title_min_height=60,title_max_width=840,row_gap_after_title=50,row_min_height=88,row_extra_height=36,row_line_height=1.25,plus_center_x=137,plus_half=11,plus_y_offset=15,plus_width=3,row_text_x=189,row_size=36,row_entry_rise=12,row_blur=2,separator_x=120,separator_right_wide=962,separator_right_narrow=620,separator_offset_bottom=23,separator_width=2,footer_reserve=193,empty_footer_reserve=28,footer_gap=35,footer_x=120,footer_width=840,footer_height=97,footer_radius=48,footer_center_x=540,footer_text_offset=27,footer_size=40,footer_max_width=750,arrow_width=4,final_blur=20,fade_power=3,zero_top=40,zero_text_gap=24,zero_bottom=28)
COLORS=dict(panel=[255,255,255,255],text=[0,0,0,255],plus=[110,110,110,255],separator=[233,233,233,255],capsule=[38,93,232,255],conclusion_text=[255,255,255,255])
def blank():return Image.new('RGBA',(1080,1920))
def phase(im,opacity,blur):
 if blur:im=im.convert('RGBa').filter(ImageFilter.GaussianBlur(blur)).convert('RGBA')
 if opacity<1:
  im=im.copy();im.putalpha(im.getchannel('A').point([round(a*max(0,opacity))for a in range(256)]))
 return im
def _number(x,label):
 if isinstance(x,bool)or not isinstance(x,(int,float))or not math.isfinite(x):raise ValueError(label+' requires finite number')
def _clock(v,label):
 if not isinstance(v,list)or len(v)!=2:raise ValueError(label+' requires explicit two-point clock')
 for x in v:_number(x,label)
 if v[0]>=v[1]:raise ValueError(label+' must increase')
def _text(x,label):
 if not isinstance(x,str)or '\n'in x or '\r'in x:raise ValueError(label+' requires planned text without embedded newlines')
def evaluate(node):
 """Replay one explicit group, preserving nonlinear joint blur/resampling."""
 if node['kind']=='leaf':return node['image']
 im=blank()
 for child in node['children']:im.alpha_composite(evaluate(child))
 if node['kind']=='row':return phase(im,node['opacity'],node['blur'])
 if node['kind']=='arrow':return phase(im,node['opacity'],0)
 if node['kind']=='footer':
  crop=im.crop(tuple(node['crop']));z=node['scale']
  crop=crop.convert('RGBa').resize((max(1,round(crop.width*z)),max(1,round(crop.height*z))),Image.Resampling.LANCZOS).convert('RGBA')
  result=blank();cx,cy=node['center'];result.alpha_composite(crop,(round(cx-crop.width/2),round(cy-crop.height/2)));return result
 raise ValueError('Unknown explicit list stage')
def compose(result):
 im=blank()
 for node in result['ordered_nodes']:im.alpha_composite(evaluate(node))
 return phase(im,result['card_effect']['opacity'],result['card_effect']['blur'])

class CapsuleListV1:
 def __init__(self,spec):
  fields={'schema','size','fps','enabled','title','items','conclusion','fonts','events','conclusion_scale_keys','geometry','colors','image_layout_intervals'}
  if not isinstance(spec,dict)or set(spec)!=fields:raise ValueError('Explicit capsule-list fields required')
  s=copy.deepcopy(spec)
  if s['schema']!=SCHEMA or s['size']!=[1080,1920]or s['fps']!=25:raise ValueError('Current1080x1920/25 capsule-list profile required')
  if type(s['enabled'])is not bool:raise ValueError('Explicit enabled boolean required')
  if hashlib.sha256(Path(inspect.getsourcefile(font.__wrapped__)).read_bytes()).hexdigest()!=PILOT_SHA:raise ValueError('Pinned pure typography/ease helper required')
  _text(s['title'],'title');s['title']=s['title'].strip()
  if not isinstance(s['items'],list)or len(s['items'])>3:raise ValueError('At most3 measured rows; explicit pagination not implemented')
  for row in s['items']:
   if not isinstance(row,dict)or set(row)!={'text','at'}:raise ValueError('Each row requires text+actual clock')
   _text(row['text'],'row');_number(row['at'],'row.at')
   if not row['text'].strip():raise ValueError('Empty row rejected; omit row and its clock explicitly')
  if not isinstance(s['conclusion'],dict)or set(s['conclusion'])!={'text','at'}:raise ValueError('Explicit optional conclusion text+clock required')
  _text(s['conclusion']['text'],'conclusion');s['conclusion']['text']=s['conclusion']['text'].strip();_number(s['conclusion']['at'],'conclusion.at')
  if not isinstance(s['fonts'],dict)or set(s['fonts'])!={'title','rows'}:raise ValueError('Explicit title/rows font refs required')
  for k,f in s['fonts'].items():
   if not isinstance(f,dict)or set(f)!={'path','sha256'}or not Path(f['path']).is_file()or hashlib.sha256(Path(f['path']).read_bytes()).hexdigest()!=f['sha256']:raise ValueError('Actual font SHA mismatch: '+k)
  if set(s['geometry'])!=set(GEOMETRY):raise ValueError('Complete measured geometry required')
  for k,v in s['geometry'].items():_number(v,k)
  if any(s['geometry'][k]<=0 for k in ['panel_width','panel_radius','title_size','row_size','footer_size','panel_min_height','fade_power']):raise ValueError('Positive measured geometry required')
  if s['geometry']['panel_x']<0 or s['geometry']['panel_x']+s['geometry']['panel_width']>1080 or not 0<s['geometry']['max_bottom']<=1920:raise ValueError('Panel reading bounds exceed canvas')
  if set(s['colors'])!=set(COLORS):raise ValueError('Complete named role palette required')
  for color in s['colors'].values():
   if not isinstance(color,list)or len(color)!=4 or any(type(x)is not int or not 0<=x<=255 for x in color):raise ValueError('RGBA palette required')
  e=s['events']
  if set(e)!={'entry','exit','row_reveal_seconds','arrow_lead'}:raise ValueError('Explicit entry/exit/row/arrow clocks required')
  _clock(e['entry'],'entry');_clock(e['exit'],'exit');_clock(e['arrow_lead'],'arrow_lead');_number(e['row_reveal_seconds'],'row reveal')
  if e['row_reveal_seconds']<=0:raise ValueError('Positive row reveal required')
  if not isinstance(s['image_layout_intervals'],list):raise ValueError('Explicit caller-resolved narrow-layout intervals required')
  for v in s['image_layout_intervals']:_clock(v,'image-layout interval')
  keys=s['conclusion_scale_keys']
  if not isinstance(keys,list)or len(keys)<2:raise ValueError('Explicit original conclusion scale curve required')
  last=-math.inf
  for row in keys:
   if not isinstance(row,list)or len(row)!=2:raise ValueError('Scale key requires delta+scale')
   for x in row:_number(x,'scale key')
   if row[0]<=last or row[1]<0:raise ValueError('Ordered scale times and nonnegative scale required')
   last=row[0]
  self.spec=s;self._tiles={};self.layouts={False:self._layout(False)}
  if s['image_layout_intervals']:self.layouts[True]=self._layout(True)
 def _wrap(self,text,path,size,width,max_lines):
  lines=[''];face=font(path,size)
  for ch in text:
   if lines[-1]and face.getlength(lines[-1]+ch)>width:lines.append(ch)
   else:lines[-1]+=ch
  if len(lines)>max_lines:raise ValueError('Natural text exceeds fixed line capacity; explicitly replan, never silently shrink')
  return lines if text else[]
 def _layout(self,narrow):
  s=self.spec;g=s['geometry'];title=self._wrap(s['title'],s['fonts']['title']['path'],g['title_size'],g['title_max_width'],2)
  rows=[self._wrap(r['text'],s['fonts']['rows']['path'],g['row_size'],400 if narrow else 750,2)for r in s['items']]
  footer=self._wrap(s['conclusion']['text'],s['fonts']['title']['path'],g['footer_size'],g['footer_max_width'],1)
  header=max(g['title_min_height'],len(title)*g['title_size']*g['title_line_height'])if title else 0
  heights=[max(g['row_min_height'],len(lines)*g['row_size']*g['row_line_height']+g['row_extra_height'])for lines in rows]
  top=g['inner_top']+header+g['row_gap_after_title'];reserve=g['footer_reserve']if footer else g['empty_footer_reserve']
  height=max(g['panel_min_height'],top+sum(heights)+reserve)
  zero=not rows
  if zero:
   # Explicit new optional-input adaptation, never claimed old if-not-items parity.
   foot_top=(g['inner_top']+header+g['zero_text_gap'])if title else g['zero_top']
   height=(foot_top+g['footer_height']+g['zero_bottom'])if footer else(g['inner_top']+header+g['zero_bottom'])
   top=foot_top
  if g['panel_y']+height>g['max_bottom']:raise ValueError('Information card exceeds validated reading area; explicit pagination required')
  return dict(title_lines=title,row_lines=rows,footer_lines=footer,header_height=header,row_top_offset=top,row_heights=heights,panel_height=height,zero_item_adaptation=zero,meaningful=bool(title or rows or footer))
 def _put(self,layer,text,path,size,x,y,color,align='left'):
  key=(text,path,size,tuple(color))
  if key not in self._tiles:
   im=text_image(text,path,size,tuple(color))[0];box=im.getchannel('A').getbbox();self._tiles[key]=im.crop(box)
  im=self._tiles[key]
  if align=='center':x-=im.width/2
  layer.alpha_composite(im,(round(x),round(y)))
 def render(self,native_frame):
  _number(native_frame,'native frame')
  if native_frame<0:raise ValueError('Nonnegative native frame required')
  s=self.spec;g=s['geometry'];co=s['colors'];t=native_frame/25;e=s['events'];q=ease(*e['entry'],t);leave=ease(*e['exit'],t)
  narrow=any(a<=t<b for a,b in s['image_layout_intervals']);layout=self.layouts[narrow];nodes=[];leaves=[]
  result=dict(ordered_nodes=nodes,raw_leaf_roles=leaves,layout=copy.deepcopy(layout),card_effect=dict(opacity=q*(1-leave)**g['fade_power'],blur=leave*g['final_blur']),phase=dict(native_frame=native_frame,time_seconds=t,entry=q,exit=leave,narrow_layout=narrow),meaningful=layout['meaningful']and s['enabled'])
  if not s['enabled']or not layout['meaningful']or q<=0:
   result['card_effect']=dict(opacity=1,blur=0);result['card']=blank();return result
  def leaf(name):
   im=blank();node=dict(kind='leaf',name=name,image=im);leaves.append(node);return node
  y0=g['panel_y']+(1-q)*g['entry_slide'];h=layout['panel_height'];panel=leaf('panel');ImageDraw.Draw(panel['image']).rounded_rectangle((g['panel_x'],y0,g['panel_x']+g['panel_width'],y0+h),radius=g['panel_radius'],fill=tuple(co['panel']));nodes.append(panel)
  if layout['title_lines']:
   title=leaf('title');ty=y0+g['inner_top']
   for line in layout['title_lines']:self._put(title['image'],line,s['fonts']['title']['path'],g['title_size'],g['title_x'],ty,co['text']);ty+=g['title_size']*g['title_line_height']
   nodes.append(title)
  y=y0+layout['row_top_offset']
  for i,(lines,item,rh)in enumerate(zip(layout['row_lines'],s['items'],layout['row_heights'])):
   if i<len(s['items'])-1:
    separator=leaf(f'row{i}-separator');ImageDraw.Draw(separator['image']).line((g['separator_x'],y+rh-g['separator_offset_bottom'],g['separator_right_narrow']if narrow else g['separator_right_wide'],y+rh-g['separator_offset_bottom']),fill=tuple(co['separator']),width=max(1,round(g['separator_width'])));nodes.append(separator)
   p=ease(item['at'],item['at']+e['row_reveal_seconds'],t)
   if p:
    plus=leaf(f'row{i}-plus');d=ImageDraw.Draw(plus['image']);cx=g['plus_center_x'];cy=y+g['plus_y_offset'];half=g['plus_half'];width=max(1,round(g['plus_width']));d.line((cx-half,cy,cx+half,cy),fill=tuple(co['plus']),width=width);d.line((cx,cy-half,cx,cy+half),fill=tuple(co['plus']),width=width)
    text=leaf(f'row{i}-text')
    for j,line in enumerate(lines):self._put(text['image'],line,s['fonts']['rows']['path'],g['row_size'],g['row_text_x'],y+j*g['row_size']*g['row_line_height']+(1-p)*g['row_entry_rise'],co['text'])
    nodes.append(dict(kind='row',name=f'row{i}',children=[plus,text],opacity=p,blur=(1-p)*g['row_blur']))
   y+=rh
  if layout['footer_lines']:
   bar_y=y if layout['zero_item_adaptation']else y+g['footer_gap']
   if not layout['zero_item_adaptation']:
    arrow=leaf('arrow');d=ImageDraw.Draw(arrow['image']);cx=g['footer_center_x'];d.line((cx,bar_y-48,cx,bar_y-25),fill=tuple(co['plus']),width=max(1,round(g['arrow_width'])));d.line((cx-11,bar_y-36,cx,bar_y-25,cx+11,bar_y-36),fill=tuple(co['plus']),width=max(1,round(g['arrow_width'])));at=s['conclusion']['at'];nodes.append(dict(kind='arrow',name='arrow-phase',children=[arrow],opacity=ease(at+e['arrow_lead'][0],at+e['arrow_lead'][1],t)))
   keys=s['conclusion_scale_keys'];z=float(np.interp(t-s['conclusion']['at'],[v[0]for v in keys],[v[1]for v in keys]))
   if z>0:
    capsule=leaf('conclusion-capsule');x=g['footer_x'];w=g['footer_width'];fh=g['footer_height'];ImageDraw.Draw(capsule['image']).rounded_rectangle((x,bar_y,x+w,bar_y+fh),radius=g['footer_radius'],fill=tuple(co['capsule']))
    text=leaf('conclusion-text');self._put(text['image'],layout['footer_lines'][0],s['fonts']['title']['path'],g['footer_size'],g['footer_center_x'],bar_y+g['footer_text_offset'],co['conclusion_text'],'center')
    nodes.append(dict(kind='footer',name='joint-capsule-scale',children=[capsule,text],crop=[round(x),round(bar_y),round(x+w),round(bar_y+fh)],scale=z,center=[g['footer_center_x'],bar_y+fh/2]))
  result['card']=compose(result);return result

def render_capsule_list(spec,native_frame):return CapsuleListV1(spec).render(native_frame)
