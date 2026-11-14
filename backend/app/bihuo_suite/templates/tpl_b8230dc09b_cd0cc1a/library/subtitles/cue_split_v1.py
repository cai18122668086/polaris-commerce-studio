"""One complete M7 cue: scale entry, reading, optional complementary split.

Only frozen pure split/shadow and vendor typography primitives are imported.
The host exposes the trusted motion skill scripts on Python's import path;
there is no old renderer import, scene sampling or multi-cue scheduling here.
"""
import copy
import hashlib
import inspect
import math
from pathlib import Path
from functools import lru_cache

from PIL import Image
from .split_title import split_rgba, with_shadow
from ...vendor.pilot import text_image, font, place_center

COMPONENT_ID='SC-CUE-SPLIT'
VERSION='1-candidate'
PURE_HELPER_SHA='43e0989a8ba2ab3730d8fd681d42cfe49d9b5faff718f852b95dde0c7c996237'
if hashlib.sha256(Path(inspect.getsourcefile(split_rgba)).read_bytes()).hexdigest()!=PURE_HELPER_SHA:
    raise ValueError('Pinned pure split/shadow helper SHA required')


def _q(n,a,b):
    return max(0,min(1,(n-a)/max(1,b-a)))


def _fade(image,opacity):
    if opacity>=1:return image
    image=image.copy()
    image.putalpha(image.getchannel('A').point([round(v*max(0,opacity)) for v in range(256)]))
    return image


def _wrap(text,path,size,width,max_lines):
    face=font(path,size);lines=[];line=''
    for ch in text:
        if line and face.getlength(line+ch)>width:lines.append(line);line=ch
        else:line+=ch
    if line:lines.append(line)
    if len(lines)>max_lines:
        raise ValueError('Text requires more than3 natural-size lines; replan semantic phrases')
    return lines


@lru_cache(maxsize=250)
def _glyph(text,path,font_sha,size,style,outline,shadow_enabled,shadow_x,shadow_y,shadow_blur):
    # Same material math and pre-shadow ink box as the recognized source.
    fill=(244,196,24,255)if style=='gold'else(0,0,0,0)
    stroke=(64,56,12,255)if style=='gold'else(255,255,255,255)
    image,box,pad=text_image(text,path,size,fill,outline if style!='gold'else 0,stroke)
    ink=image.getchannel('A').getbbox()
    if shadow_enabled:
        image=with_shadow(image,dict(shadowX=shadow_x,shadowY=shadow_y,shadowBlur=shadow_blur))
    return image,box,pad,ink


class CueSplitV1:
    """Prepared single cue; changing source/font/parameters invalidates evidence."""
    def __init__(self,inputs):
        def fields(value,allowed,label):
            if not isinstance(value,dict)or set(value)!=set(allowed):raise ValueError(label+' explicit fields required')
        fields(inputs,['schema','text','font','style','font_size','outline','shadow','layout','events','motion'],'cue')
        if inputs['schema']!='motion.cue-split-input/1' or inputs['style']not in ['gold','white']:
            raise ValueError('Only current M7 gold/white cue profiles supported')
        if not isinstance(inputs['text'],str):raise ValueError('Explicit text required')
        fields(inputs['font'],['path','sha256'],'font')
        path=Path(inputs['font']['path']);digest=hashlib.sha256(path.read_bytes()).hexdigest()if path.is_file()else None
        if digest!=inputs['font']['sha256']:raise ValueError('Font actual bytes SHA mismatch')
        fields(inputs['shadow'],['enabled','x','y','blur'],'shadow')
        if type(inputs['shadow']['enabled'])is not bool:raise ValueError('Explicit shadow enabled flag required')
        fields(inputs['layout'],['size','center_x','caption_top','line_gap','max_width','max_lines','lines'],'layout')
        layout=inputs['layout']
        if layout['size']!=[1080,1920]or layout['max_width']!=1000 or layout['max_lines']!=3:
            raise ValueError('Current native1080/1000px/max3line contract required')
        if type(inputs['font_size'])is not int or inputs['font_size']<=0 or type(inputs['outline'])is not int or inputs['outline']<0:
            raise ValueError('Positive native font size and nonnegative outline required')
        fields(inputs['events'],['first','settle','exit','gone','split'],'events')
        e=inputs['events']
        if any(type(e[k])is not int for k in ['first','settle','exit','gone']) or not 0<=e['first']<=e['settle']<e['gone'] or not e['first']<=e['exit']<=e['gone']:
            raise ValueError('Native cue event ordering invalid')
        if e['split']is not None and(type(e['split'])is not int or not e['settle']<=e['split']<e['gone']):
            raise ValueError('Only explicitly timed settled cues may split')
        fields(inputs['motion'],['entry_scale_from','split_distance','split_travel_frames','split_fade_fraction'],'motion')
        self._inputs=copy.deepcopy(inputs);self._path=str(path)
        explicit=layout['lines']
        if explicit is not None and(not isinstance(explicit,list)or any(not isinstance(x,str)or not x for x in explicit)):
            raise ValueError('Explicit lines must be nonempty strings or null')
        if not inputs['text']:
            if explicit:raise ValueError('Empty text cannot retain stale line payload')
            self._lines=[]
        else:
            self._lines=copy.deepcopy(explicit)if explicit else _wrap(inputs['text'],self._path,inputs['font_size'],1000,3)
            if ''.join(self._lines)!=inputs['text']or len(self._lines)>3:
                raise ValueError('Natural lines must cover the exact text with max3 lines')
            if any(font(self._path,inputs['font_size']).getlength(line)>1000 for line in self._lines):
                raise ValueError('Natural caption width exceeds1000; no squeezing or clipping')
            # Reading-position ink/shadow must fit before entry/exit travel.
            # Explicit split motion may leave this region during its exit.
            top=layout['caption_top']-(len(self._lines)-1)*layout['line_gap']/2
            for i,line in enumerate(self._lines):
                shadow=inputs['shadow']
                image,_,pad,_=_glyph(line,self._path,inputs['font']['sha256'],inputs['font_size'],inputs['style'],inputs['outline'],shadow['enabled'],shadow['x'],shadow['y'],shadow['blur'])
                box=image.getchannel('A').getbbox()
                x=round(layout['center_x']-image.width/2);y=round(top+i*layout['line_gap']-pad)
                if box and(x+box[0]<0 or y+box[1]<0 or x+box[2]>1080 or y+box[3]>1920):
                    raise ValueError('Natural reading ink/shadow exceeds canvas; explicit replan required')

    def render(self,native_phase):
        if isinstance(native_phase,bool)or not isinstance(native_phase,(int,float))or not math.isfinite(native_phase):
            raise ValueError('Finite explicit native phase required')
        cfg=self._inputs;e=cfg['events'];n=native_phase
        if not self._lines or n<e['first']or n>=e['gone']:return dict(ordered_roles=[],layout=[])
        opacity=1;scale=1;motion=cfg['motion']
        if n<e['settle']:
            z=_q(n,e['first']-1,e['settle']);opacity=z;scale=motion['entry_scale_from']+(1-motion['entry_scale_from'])*(1-(1-z)**3)
        if e['split']is None and n>=e['exit']:opacity*=1-_q(n,e['exit']-1,e['gone'])
        layout=cfg['layout'];top=layout['caption_top']-(len(self._lines)-1)*layout['line_gap']/2
        roles=[];boxes=[];shadow=cfg['shadow']
        for i,line in enumerate(self._lines):
            image,box,pad,ink=_glyph(line,self._path,cfg['font']['sha256'],cfg['font_size'],cfg['style'],cfg['outline'],shadow['enabled'],shadow['x'],shadow['y'],shadow['blur'])
            layer=Image.new('RGBA',tuple(layout['size']));height=ink[3]-ink[1]
            yy=top+i*layout['line_gap']+(1-scale)*height/2
            place_center(layer,image,layout['center_x'],yy-pad*scale,opacity,scale)
            if e['split']is not None and n>=e['split']:
                z=_q(n,e['split']-1,e['gone']);travel=_q(n,e['split']-1,e['split']+motion['split_travel_frames'])
                dy=motion['split_distance']*travel*travel*(3-2*travel)
                layer=_fade(layer,1-z*motion['split_fade_fraction'])
                upper,lower=split_rgba(layer,top+i*layout['line_gap']+height/2,dy=dy)
                # Preserve the source loop: each line's upper THEN lower before
                # the next line. Grouping all uppers first changes compositing.
                roles.extend([dict(name=f'line{i}-upper',line=i,kind='upper',image=upper),
                              dict(name=f'line{i}-lower',line=i,kind='lower',image=lower)])
            else:roles.append(dict(name=f'line{i}-whole',line=i,kind='whole',image=layer))
            boxes.append(dict(text=line,ink_width=ink[2]-ink[0],ink_height=height,top=top+i*layout['line_gap'],split_center=top+i*layout['line_gap']+height/2))
        return dict(ordered_roles=roles,layout=boxes)


def render_cue(inputs,native_phase):
    """A complete single-cue caller; multiple cue handoffs remain recipe work."""
    return CueSplitV1(inputs).render(native_phase)
