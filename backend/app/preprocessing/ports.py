"""Closed data constructors for typed graph ports; no expressions or code eval."""
from copy import deepcopy
import numpy as np
from .artifact_codec import fingerprint
from .units.contracts_v2 import _finite_json


def sources(expression):
    if expression.kind=='port':yield expression.source
    for child in expression.fields.values():yield from sources(child)
    for child in expression.items:yield from sources(child)


def port_value(port,nodes):
    node=nodes[port.step]
    value=node['packet'].data if port.port=='data' else node[port.port]
    for key in port.path:
        value=value[int(key)] if isinstance(value,(list,tuple,np.ndarray)) and key.isdecimal() else value[key]
    if port.transpose is not None:
        if not isinstance(value,np.ndarray) or sorted(port.transpose)!=list(range(value.ndim)):raise ValueError('transpose must declare a complete array axis permutation')
        value=value.transpose(port.transpose)
    return deepcopy(value)


def evaluate(expression,nodes):
    if expression.kind=='port':return port_value(expression.source,nodes)
    if expression.kind=='literal':_finite_json(expression.value);return deepcopy(expression.value)
    if expression.kind=='object':return {k:evaluate(v,nodes) for k,v in expression.fields.items()}
    values=[evaluate(v,nodes) for v in expression.items]
    if expression.kind in ('equal','greater','less'):
        left,right=map(np.asarray,values)
        if left.shape!=right.shape and left.ndim!=0 and right.ndim!=0:raise ValueError('diagnostic comparison requires matching axes or a scalar threshold')
        return {'equal':np.equal,'greater':np.greater,'less':np.less}[expression.kind](left,right)
    if expression.kind=='nonzero':
        mask=np.asarray(values[0])
        if mask.dtype.kind!='b' or mask.ndim!=1:raise ValueError('component index selection requires a one-dimensional boolean mask')
        return np.flatnonzero(mask).tolist()
    return fingerprint(values) if expression.kind=='digest' else values
