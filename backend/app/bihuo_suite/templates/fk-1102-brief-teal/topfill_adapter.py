"""r3: source-specific top-only blur fill. Keep the outside-window grid intact."""
from . import fullwidth_adapter as previous
from PIL import ImageFilter
base=previous.base
def render_layers(frame,t,cfg):
 layers=base.render_layers(frame,t,cfg);weight=previous.large_weight(cfg,t)
 if weight:
  fill=base.M._fit(frame.convert('RGBA'),1080,1920,dict(fit='cover',anchor=[.5,.35])).crop((0,0,1080,314)).filter(ImageFilter.GaussianBlur(45))
  layers['background'].alpha_composite(base.fade(fill,weight),(0,0))
 return layers
person_box=previous.person_box;blank=base.blank;composite=base.composite;match=base.match
