"""M7 graded-size glyph header, with explicit per-glyph clocks and advances.

Opening whole-line titles and multi-cue scheduling are outside this component.
Only the frozen cue component's pure glyph primitive and vendor placement are
reused; no project engine/header function is imported.
"""
import copy
import hashlib
import math
from pathlib import Path
from PIL import Image
from .cue_split_v1 import _glyph
from ...vendor.pilot import place_center

COMPONENT_ID='SC-GLYPH-STAGGER'
VERSION='1-candidate'


def _q(n,a,b):return max(0,min(1,(n-a)/max(1,b-a)))


class GlyphStaggerV1:
    def __init__(self,inputs):
        def fields(value,names,label):
            if not isinstance(value,dict)or set(value)!=set(names):raise ValueError(label+' explicit fields required')
        fields(inputs,['schema','text','font','glyph_start','size_group','font_sizes','advances','anchor','motion','whole_exit','shadow','size'],'header')
        if inputs['schema']!='motion.glyph-stagger-input/1' or inputs['size']!=[1080,1920]:
            raise ValueError('Current M7 native1080 contract required')
        if not isinstance(inputs['text'],str):raise ValueError('Explicit text required')
        count=len(inputs['text'])
        for name in ['glyph_start','size_group','advances']:
            if not isinstance(inputs[name],list)or len(inputs[name])!=count:
                raise ValueError('Every text glyph requires exactly one '+name+' item; no zip truncation')
        fields(inputs['font'],['path','sha256'],'font');path=Path(inputs['font']['path'])
        if not path.is_file()or hashlib.sha256(path.read_bytes()).hexdigest()!=inputs['font']['sha256']:
            raise ValueError('Actual font SHA mismatch')
        if not isinstance(inputs['font_sizes'],dict)or any(type(x)is not int or x<=0 for x in inputs['font_sizes'].values()):
            raise ValueError('Explicit positive font sizes required')
        if any(group not in inputs['font_sizes']for group in inputs['size_group']):raise ValueError('Unknown glyph size group')
        if any(isinstance(x,bool)or not isinstance(x,(int,float))or not math.isfinite(x)for x in inputs['glyph_start']+inputs['advances']):
            raise ValueError('Finite glyph phases/advances required')
        if any(x<0 for x in inputs['glyph_start'])or any(x<=0 for x in inputs['advances']):raise ValueError('Nonnegative starts and positive advances required')
        fields(inputs['anchor'],['cursor_x','baseline_y'],'anchor')
        fields(inputs['motion'],['entry_lead','entry_tail','angle_from','angle_to','scale_from','scale_to'],'motion')
        fields(inputs['shadow'],['enabled','x','y','blur'],'shadow')
        if type(inputs['shadow']['enabled'])is not bool:raise ValueError('Explicit shadow flag required')
        if not isinstance(inputs['whole_exit'],list)or len(inputs['whole_exit'])!=2 or not inputs['whole_exit'][0]<inputs['whole_exit'][1]:
            raise ValueError('Explicit increasing whole exit required')
        m=inputs['motion']
        if m['entry_lead']<0 or m['entry_tail']<=0 or not 0<m['scale_from']<=m['scale_to']:
            raise ValueError('Explicit positive native entry/scale required')
        self._input=copy.deepcopy(inputs);self._glyphs=[];cursor=inputs['anchor']['cursor_x'];boxes=[]
        shadow=inputs['shadow']
        for i,ch in enumerate(inputs['text']):
            size=inputs['font_sizes'][inputs['size_group'][i]]
            image,bb,pad,ink=_glyph(ch,str(path),inputs['font']['sha256'],size,'gold',0,shadow['enabled'],shadow['x'],shadow['y'],shadow['blur'])
            advance=inputs['advances'][i];center=cursor+advance/2;top=inputs['anchor']['baseline_y']+bb[1]-pad
            # Measure the final full word before any canvas clipping. Entry
            # rotation remains a deliberate transient, not a reading-layout fit.
            stable=image.rotate(m['angle_to'],Image.Resampling.BICUBIC,expand=True)
            if m['scale_to']!=1:stable=stable.resize((max(1,round(stable.width*m['scale_to'])),max(1,round(stable.height*m['scale_to']))),Image.Resampling.LANCZOS)
            box=stable.getchannel('A').getbbox();bounds=None
            if box:
                x=round(center-stable.width/2);y=round(top);bounds=[x+box[0],y+box[1],x+box[2],y+box[3]]
                if bounds[0]<0 or bounds[1]<0 or bounds[2]>1080 or bounds[3]>1920:
                    raise ValueError('Stable complete glyph word exceeds natural canvas; explicit replan required')
                boxes.append(bounds)
            self._glyphs.append(dict(index=i,char=ch,start=inputs['glyph_start'][i],size_group=inputs['size_group'][i],size=size,
                advance=advance,center_x=center,top=top,pad=pad,font_bbox=bb,stable_bounds=bounds,image=image))
            cursor+=advance
        if cursor>1080 or inputs['anchor']['cursor_x']<0:raise ValueError('Complete natural advance word exceeds canvas')
        self.stable_layout=dict(glyphs=[{k:v for k,v in g.items()if k!='image'}for g in self._glyphs],cursor_end=cursor,
            whole_bounds=[min(b[0]for b in boxes),min(b[1]for b in boxes),max(b[2]for b in boxes),max(b[3]for b in boxes)]if boxes else None,
            max_count_policy='No hardcoded four-glyph limit; complete counted lists and measured natural canvas bound capacity. Only current four-glyph inputs are regression verified.')

    def render(self,native_phase):
        if isinstance(native_phase,bool)or not isinstance(native_phase,(int,float))or not math.isfinite(native_phase):raise ValueError('Finite native phase required')
        cfg=self._input;n=native_phase;a,b=cfg['whole_exit'];leave=1-_q(n,a-1,b)if n>=a else 1;m=cfg['motion']
        roles=[];layout=[]
        for g in self._glyphs:
            entry=_q(n,g['start']-m['entry_lead'],g['start']+m['entry_tail'])
            angle=m['angle_to']+(m['angle_from']-m['angle_to'])*(1-entry)
            scale=m['scale_from']+(m['scale_to']-m['scale_from'])*(1-(1-entry)**3)
            active=entry>0 and leave>0
            if active:
                rotated=g['image'].rotate(angle,Image.Resampling.BICUBIC,expand=True)
                layer=Image.new('RGBA',tuple(cfg['size']))
                place_center(layer,rotated,g['center_x'],g['top'],entry*leave,scale)
                roles.append(dict(name=f'gli-{g["index"]:02}',index=g['index'],char=g['char'],image=layer))
            layout.append(dict(index=g['index'],char=g['char'],start=g['start'],font_size=g['size'],size_group=g['size_group'],
                advance=g['advance'],center_x=g['center_x'],top=g['top'],entry=entry,whole_leave=leave,opacity=entry*leave,
                angle=angle,scale=scale,active=active,stable_bounds=g['stable_bounds']))
        return dict(ordered_glyph_roles=roles,layout=layout)


def render_header(inputs,native_phase):
    return GlyphStaggerV1(inputs).render(native_phase)
