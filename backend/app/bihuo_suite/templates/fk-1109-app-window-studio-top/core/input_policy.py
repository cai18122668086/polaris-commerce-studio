"""Optional creative inputs. Never infer a person's identity from a video."""
from __future__ import annotations
from typing import Any

def clean(value: Any, field: str) -> str:
    if value is None:return ''
    if not isinstance(value,str):raise ValueError(f'{field} must be text')
    return value.strip()

def name_card(value: dict | None) -> dict:
    value=value or {}
    name=clean(value.get('name'),'name_card.name');description=clean(value.get('description'),'name_card.description')
    if len(name)>50 or len(description)>50:raise ValueError('Name and description each allow at most50 characters')
    enabled=value.get('enabled',True)
    if type(enabled) is not bool:raise ValueError('name_card.enabled must be boolean')
    visible=enabled and bool(name or description)
    return dict(enabled=enabled,visible=visible,name=name if visible else '',description=description if visible else '',reason='disabled' if not enabled else 'no identity supplied' if not visible else 'explicit creative input',slots=[key for key,text in [('name',name),('description',description)] if visible and text])

def resolve(value: dict) -> dict:
    card=name_card(value.get('name_card'))
    title=clean(value.get('title'),'title');subtitle=clean(value.get('subtitle'),'subtitle')
    mode=value.get('material_mode','none')
    if mode not in {'none','provided','auto'}:raise ValueError('Unknown material mode')
    materials=value.get('materials',[])
    if not isinstance(materials,list):raise ValueError('materials must be an array')
    if mode=='provided' and not materials:
        material_decision='use validated no-material variant; do not draw empty slots'
    elif mode=='auto':
        material_decision='planning may propose assets; generation requires its own authorized actual job, never a placeholder'
    elif mode=='none':material_decision='omit external material layers and reflow native information'
    else:material_decision='use named supplied assets bound to semantic clock'
    return dict(name_card=card,title=title,subtitle=subtitle,material_mode=mode,material_decision=material_decision,logo=value.get('logo') or None,cover=value.get('cover') or None)
