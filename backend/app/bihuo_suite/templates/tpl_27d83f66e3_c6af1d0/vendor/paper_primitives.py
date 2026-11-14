import numpy as np,math
from PIL import Image
from .apple_minimal.pilot import text_image
W,H=1080,1920
def paper():
 # Deterministic editable approximation, not recovered authortexture.
 rng=np.random.default_rng(1029);base=np.zeros((H,W,3),np.float32);noise=rng.normal(0,2.5,(H,W));low=np.asarray(Image.fromarray(rng.integers(0,255,(90,50),np.uint8)).resize((W,H),Image.Resampling.BICUBIC),np.float32)-127
 yy,xx=np.mgrid[:H,:W];grain=noise+low*.07
 for i in range(35):
  x=rng.uniform(-W,W*2);slope=rng.uniform(-.7,.7);dist=xx-(x+yy*slope+18*np.sin(yy/rng.uniform(90,300)));grain+=rng.uniform(-12,10)*np.exp(-dist*dist/rng.uniform(18,80)**2)
 for c,v in enumerate([177,153,120]):base[:,:,c]=v+grain
 return Image.fromarray(np.clip(base,0,255).astype(np.uint8)).convert('RGBA')

def ink(text,path,size,fill,stroke=0,slant=0):
 im=text_image(text,path,size,fill,stroke,(30,29,27,255))[0];box=im.getchannel('A').getbbox();im=im.crop(box) if box else Image.new('RGBA',(1,1))
 if slant:
  shift=math.ceil(abs(slant)*im.height);im=im.transform((im.width+shift,im.height),Image.Transform.AFFINE,(1,slant,-shift,0,1,0),Image.Resampling.BICUBIC)
 return im