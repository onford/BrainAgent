"""Render an assessment-figure-2 JSON with Matplotlib (PDF, SVG and 600-dpi PNG).

Example, from the repository root:
  backend/.venv-eeg/Scripts/python.exe -X utf8 backend/scripts/export_assessment_figure.py figure.json --output figures/psd
The browser JSON freezes data, missingness, limits, palette, styles and page indices.
This exporter does not recompute EEG metrics or smooth curves.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import warnings
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap, Normalize
from matplotlib.patches import Patch
from matplotlib import font_manager

PROFILES = {'research-double': (183, 8), 'nature-double': (183, 6.5), 'nature-single': (89, 6.5), 'ieee-double': (182, 8)}
PALETTES = Path(__file__).resolve().parents[2] / 'frontend/src/utils/figurePalettes.json'


def finite_array(values):
    result = np.array([np.nan if v is None else v for v in values], dtype=float)
    result[~np.isfinite(result)] = np.nan
    return result


def validate(spec):
    if spec.get('schema_version') != 'assessment-figure-2' or spec.get('kind') not in {'series', 'heatmap'}:
        raise ValueError('Expected a current assessment-figure-2 chart JSON, not a raw EEG receipt')
    rendering = spec['rendering']
    for key in (('xDomain', 'yDomain') if spec['kind'] == 'series' else ('colorLimits',)):
        domain = rendering[key]
        if len(domain) != 2 or not np.isfinite(domain).all() or domain[0] >= domain[1]:
            raise ValueError(f'Invalid frozen {key}')
    if spec['kind'] == 'heatmap':
        if len(spec['values']) != len(spec['rows']) or any(len(row) != len(spec['columns']) for row in spec['values']):
            raise ValueError('Matrix dimensions do not match the saved axis labels')
        for key, length in [('rowIndices', len(spec['rows'])), ('columnIndices', len(spec['columns']))]:
            indices = rendering[key]
            if not indices or any(type(i) is not int or i < 0 or i >= length for i in indices) or len(indices) != len(set(indices)):
                raise ValueError(f'Invalid {key}')


def render(spec, output: Path, profile='research-double', dpi=600):
    validate(spec)
    if dpi < 300:
        raise ValueError('Use at least 300 dpi for the raster copy; PDF/SVG remain vector')
    output.parent.mkdir(parents=True, exist_ok=True)
    canonical = json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    source_hash = hashlib.sha256(canonical.encode()).hexdigest()
    width, font = PROFILES[profile]
    r = spec['rendering']
    height = width * r['viewBox'][3] / r['viewBox'][2]
    # Dense single-column exports need more height for readable labels.
    if width < 100:
        height = max(height, 72 if spec['kind'] == 'series' else 95)
    if profile.startswith('nature') and height > 170:
        raise ValueError('This page exceeds the Nature 170 mm height; select a smaller page')
    fonts = {}
    for name in ['Arial', 'Microsoft YaHei', 'Noto Sans CJK SC', 'DejaVu Sans']:
        try:
            filename = font_manager.findfont(name, fallback_to_default=False)
        except ValueError:
            continue
        fonts[name] = {'file': Path(filename).name, 'sha256': hashlib.sha256(Path(filename).read_bytes()).hexdigest()}
    # Explicit families enable per-glyph fallback; generic sans-serif picks one
    # family and can silently lose Chinese labels in PDF/PNG.
    with warnings.catch_warnings(), plt.rc_context({'font.family':list(fonts),
                         'font.size':font, 'axes.labelsize':font, 'xtick.labelsize':font, 'ytick.labelsize':font,
                         'legend.fontsize':font, 'axes.linewidth':.6, 'pdf.fonttype':42, 'ps.fonttype':42,
                         'svg.fonttype':'none', 'svg.hashsalt':source_hash, 'path.simplify':False,
                         'agg.path.chunksize':0, 'figure.dpi':dpi, 'savefig.dpi':dpi}):
        warnings.filterwarnings('error', message='Glyph .* missing from font')
        fig = plt.figure(figsize=(width/25.4, height/25.4), facecolor='white')
        if spec['kind'] == 'series':
            ax = fig.add_axes([.13,.26,.81,.57])
            markers = {'circle':'o','square':'s','triangle':'^','diamond':'D'}
            for series, style in zip(spec['series'], r['styles'], strict=True):
                x = finite_array([p['x'] for p in series['points']])
                y = finite_array([p['y'] for p in series['points']])
                # Invalid x also breaks a line; never drop missing points to join gaps.
                y[~np.isfinite(x)] = np.nan
                connected = series.get('connect') is not False
                dash = tuple(float(v) for v in style.get('dash','').split())
                ax.plot(x, y, label=series['name'], color=style['color'], linewidth=1,
                        linestyle=(0,dash) if connected and dash else '-' if connected else 'None',
                        marker=markers[style['marker']] if not connected or len(x)<=24 else None,
                        markersize=3.4, markeredgewidth=.35, markeredgecolor='white')
                for point in series['points']:
                    if point.get('annotation') and np.isfinite(point['x']) and point['y'] is not None and np.isfinite(point['y']):
                        ax.annotate(point['annotation'], (point['x'], point['y']), xytext=(4, 4), textcoords='offset points', fontsize=font)
            if r.get('reference') is not None:
                ax.axhline(r['reference'], color='#68727c', linestyle=(0,(4,3)), linewidth=.6)
            ax.set(xlim=r['xDomain'], ylim=r['yDomain'], xlabel=spec['xLabel'], ylabel=spec['yLabel'])
            for axis in ['x','y']:
                ticks = r[axis+'Ticks']
                getattr(ax,'set_'+axis+'ticks')([v['value'] for v in ticks], [v['label'] for v in ticks])
            if r.get('xTickRotation'):
                plt.setp(ax.get_xticklabels(), rotation=-r['xTickRotation'], ha='left')
            if r.get('equalAspect'):
                ax.set_aspect('equal', adjustable='box')
            ax.spines[['top','right']].set_visible(False)
            ax.grid(axis='y', color='#e6eaee', linewidth=.5)
            ax.set_axisbelow(True)
            ax.tick_params(length=2.5, width=.5, colors='#445460')
            fig.legend(*ax.get_legend_handles_labels(), loc='lower center', bbox_to_anchor=(.55,.025),
                       ncol=1 if width<100 else min(2,len(spec['series'])), frameon=False)
        else:
            ax = fig.add_axes([.2,.27,.73,.49])
            rows, columns = r['rowIndices'], r['columnIndices']
            matrix = np.asarray([[np.nan if v is None else v for v in row] for row in spec['values']],dtype=float)
            values = np.ma.masked_invalid(matrix[np.ix_(rows,columns)])
            palette = json.loads(PALETTES.read_text(encoding='utf8'))[r['colormap']]
            cmap = ListedColormap(palette).with_extremes(bad=r['missing_color'])
            mesh = ax.pcolormesh(np.arange(len(columns)+1),np.arange(len(rows)+1),values,
                                 cmap=cmap,norm=Normalize(*r['colorLimits']),shading='flat',edgecolors='none',rasterized=False)
            # A short last page leaves blank space instead of stretching cells.
            ax.set_xlim(0,r['column_slots']); ax.set_ylim(r['row_slots'],0)
            step = max(1,int(np.ceil(r['column_slots']/(6 if width<100 else 12))))
            ids=list(range(0,len(columns),step))
            if r.get('full_matrix'):
                ids=sorted(set(np.linspace(0,len(columns)-1,min(11,len(columns))).round().astype(int)))
            ax.set_xticks([i+.5 for i in ids],[spec['columns'][columns[i]] for i in ids],rotation=45,ha='right')
            row_ticks=list(range(0,len(rows),max(1,int(np.ceil(len(rows)/24)))))
            ax.set_yticks([i+.5 for i in row_ticks],[spec['rows'][rows[i]] for i in row_ticks])
            ax.set_xlabel(spec.get('xLabel') or '')
            ax.set_ylabel(spec.get('yLabel') or '')
            ax.tick_params(length=0,pad=3)
            for spine in ax.spines.values(): spine.set_color('#ccd4dd')
            cax=fig.add_axes([.60,.86,.33,.022])
            colorbar=fig.colorbar(mesh,cax=cax,orientation='horizontal')
            # Matplotlib rasterizes a dense colorbar by default, even when the
            # heatmap itself is vector. Keep the entire publication PDF editable.
            if colorbar.solids is not None:
                colorbar.solids.set_rasterized(False)
            color_ticks = [r['colorLimits'][0],sum(r['colorLimits'])/2,r['colorLimits'][1]]
            colorbar.set_ticks(color_ticks, labels=[f'{v:.5g}' for v in color_ticks])
            colorbar.ax.tick_params(labelsize=font,length=2)
            colorbar.outline.set_visible(False)
            fig.text(.2,.85,spec['unit'],fontsize=font)
            fig.legend(handles=[Patch(facecolor=r['missing_color'],label='Missing / unavailable')],
                       loc='lower center',bbox_to_anchor=(.52,.015),frameon=False)
        fig.text(.13 if spec['kind']=='series' else .2,.95,spec['title'],fontsize=font,fontweight='bold',va='top')
        fig.canvas.draw()
        # Diagnose clipping rather than silently changing font size or figure size.
        renderer=fig.canvas.get_renderer()
        clipped=[]
        for label in fig.findobj(matplotlib.text.Text):
            if not label.get_visible() or not label.get_text(): continue
            box=label.get_window_extent(renderer)
            if box.x0 < -1 or box.y0 < -1 or box.x1 > fig.bbox.width+1 or box.y1 > fig.bbox.height+1:
                clipped.append(label.get_text())
        if clipped:
            plt.close(fig)
            raise ValueError('Text exceeds the selected page; choose a wider profile or shorter labels: '+repr(clipped))
        fig.savefig(output.with_suffix('.pdf'),metadata={'Creator':'BrainAgent assessment-figure-2','CreationDate':None,'ModDate':None,'Subject':source_hash})
        fig.savefig(output.with_suffix('.png'),dpi=dpi,metadata={'Software':'BrainAgent assessment-figure-2','SourceSHA256':source_hash})
        fig.savefig(output.with_suffix('.svg'),metadata={'Date':None,'Creator':'BrainAgent assessment-figure-2','Description':source_hash})
        plt.close(fig)
    receipt={'schema_version':'assessment-figure-export-1','input_sha256':source_hash,'profile':profile,'width_mm':width,'height_mm':height,
             'font_pt':font,'dpi':dpi,'matplotlib':matplotlib.__version__,'numpy':np.__version__,
             'fonts': fonts, 'exporter_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'palette_sha256':hashlib.sha256(PALETTES.read_bytes()).hexdigest(),'caption':spec['caption'],
             'rendering':r,'outputs':{suffix:hashlib.sha256(output.with_suffix(suffix).read_bytes()).hexdigest() for suffix in ['.pdf','.png','.svg']}}
    output.with_suffix('.manifest.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    output.with_suffix('.caption.txt').write_text(spec['caption']+'\n',encoding='utf8')
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--profile',choices=PROFILES,default='research-double');parser.add_argument('--dpi',type=int,default=600)
    parser.add_argument('--full-matrix', action='store_true', help='Export all heatmap rows/columns using the same frozen color limits')
    args=parser.parse_args()
    spec=json.loads(args.input.read_text(encoding='utf8'))
    if args.full_matrix:
        if spec.get('kind') != 'heatmap':
            parser.error('--full-matrix requires a heatmap JSON')
        r=spec['rendering']
        reverse=r.get('reverse_rows',len(r['rowIndices'])>1 and r['rowIndices'][0]>r['rowIndices'][1])
        rows=list(range(len(spec['rows'])))
        r.update(rowIndices=rows[::-1] if reverse else rows,columnIndices=list(range(len(spec['columns']))),
                 row_slots=len(rows),column_slots=len(spec['columns']),page=1,column_page=1,
                 viewBox=[0,0,900,228+len(rows)*20],scope='full matrix')
    result=render(spec,args.output,args.profile,args.dpi)
    print(json.dumps({'output':str(args.output),'source_sha256':result['input_sha256'],'profile':args.profile}))
