import copy
import json

import pytest

pytest.importorskip('matplotlib')
from scripts.export_assessment_figure import render, validate
from pypdf import PdfReader


def sample():
    return {'schema_version':'assessment-figure-2','kind':'series','title':'PSD','xLabel':'Frequency (Hz)',
            'yLabel':'dB','caption':'Missing point remains a gap; no smoothing.',
            'series':[{'id':'PSD','name':'PSD','points':[{'x':0,'y':1},{'x':1,'y':None},{'x':2,'y':3}]}],
            'rendering':{'viewBox':[0,0,780,416],'xDomain':[0,2],'yDomain':[0,4],
                         'xTicks':[{'value':0,'label':'0'},{'value':2,'label':'2'}],
                         'yTicks':[{'value':0,'label':'0'},{'value':4,'label':'4'}],
                         'styles':[{'color':'#0072B2','dash':'','marker':'circle'}]}}


def test_vector_exports_are_reproducible_embedded_and_data_sensitive(tmp_path):
    spec=sample(); original=copy.deepcopy(spec)
    first=render(spec,tmp_path/'first',dpi=300)
    second=render(spec,tmp_path/'second',dpi=300)
    assert first['outputs']==second['outputs']
    assert spec==original
    pdf=PdfReader(tmp_path/'first.pdf')
    assert float(pdf.pages[0].mediabox.width)==pytest.approx(183/25.4*72,abs=.01)
    assert '/Image' not in str(pdf.pages[0]['/Resources'].get('/XObject',{}))
    for font in pdf.pages[0]['/Resources']['/Font'].get_object().values():
        desc=font.get_object()['/DescendantFonts'][0].get_object()['/FontDescriptor'].get_object()
        assert '/FontFile2' in desc
    spec['series'][0]['points'][0]['y']=2
    changed=render(spec,tmp_path/'changed',dpi=300)
    assert changed['input_sha256']!=first['input_sha256']
    assert changed['outputs']['.png']!=first['outputs']['.png']
    assert json.loads((tmp_path/'first.manifest.json').read_text())['fonts']


def test_refuses_unfrozen_or_misaligned_inputs():
    with pytest.raises(ValueError,match='current assessment'):
        validate({'kind':'raw'})
    spec={'schema_version':'assessment-figure-2','kind':'heatmap','rows':['a'],'columns':['b','c'],
          'values':[[1]],'rendering':{'colorLimits':[0,1]}}
    with pytest.raises(ValueError,match='dimensions'):
        validate(spec)


def test_heatmap_colorbar_remains_vector_and_keeps_missing_cells(tmp_path):
    spec={'schema_version':'assessment-figure-2','kind':'heatmap','title':'ERDS','caption':'Paired baseline',
          'rows':['8 Hz','10 Hz'],'columns':['0 s','1 s'],'values':[[None,0],[-2,2]],'unit':'%',
          'rendering':{'viewBox':[0,0,900,468],'colorLimits':[-2,2],'colormap':'RdBu_r','missing_color':'#d5d9df',
                       'rowIndices':[1,0],'columnIndices':[0,1],'row_slots':2,'column_slots':2}}
    render(spec,tmp_path/'heatmap',dpi=300)
    page=PdfReader(tmp_path/'heatmap.pdf').pages[0]
    xobjects=page['/Resources'].get('/XObject',{})
    if hasattr(xobjects,'get_object'):
        xobjects=xobjects.get_object()
    assert not any(v.get_object().get('/Subtype')=='/Image' for v in xobjects.values())
    assert 'Missing' in page.extract_text()
