"""Real Edge/CDP UI interaction; save screenshot, console errors and API artifacts."""
from pathlib import Path
from urllib.request import urlopen
import argparse,asyncio,base64,hashlib,json,subprocess,time
import websockets
from app.preprocessing.storage import write_json,file_hash


async def audit(args):
    root=args.root.resolve();root.mkdir(parents=True,exist_ok=True)
    capability=json.load(urlopen(args.url.split('/preprocessing/units')[0]+'/api/preprocessing/capabilities'))
    expected_count=capability['counts']['profiles']
    write_json(root/'capabilities.json',capability)
    command=[args.browser,'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=0','--user-data-dir='+str(root/'edge-profile'),'about:blank']
    browser=subprocess.Popen(command,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for attempt in range(60):
            try:
                port=(root/'edge-profile/DevToolsActivePort').read_text().splitlines()[0]
                targets=json.load(urlopen('http://127.0.0.1:'+port+'/json/list'));target=next(t for t in targets if t['type']=='page');break
            except Exception:await asyncio.sleep(.5)
        else:raise RuntimeError('browser did not expose CDP')
        async with websockets.connect(target['webSocketDebuggerUrl'],max_size=20_000_000) as ws:
            seq=0;events=[]
            async def call(method,params=None):
                nonlocal seq
                seq+=1;expected=seq;await ws.send(json.dumps({'id':seq,'method':method,'params':params or {}}))
                while True:
                    reply=json.loads(await ws.recv())
                    if reply.get('id')==expected:
                        if 'error' in reply:raise RuntimeError(str(reply))
                        return reply.get('result',{})
                    if reply.get('method') in ('Runtime.exceptionThrown','Log.entryAdded'):events.append(reply)
            async def js(code):
                result=await call('Runtime.evaluate',{'expression':code,'returnByValue':True,'awaitPromise':True})
                if 'exceptionDetails' in result:raise RuntimeError(str(result))
                return result.get('result',{}).get('value')
            await call('Runtime.enable');await call('Log.enable');await call('Page.enable');await call('Emulation.setDeviceMetricsOverride',dict(width=1500,height=1100,deviceScaleFactor=1,mobile=False))
            await call('Page.navigate',{'url':args.url})
            for attempt in range(300):
                if await js("document.querySelectorAll('.catalog button').length === "+str(expected_count)):break
                await asyncio.sleep(.3)
            else:
                write_json(root/'failure.json',{'stage':'catalogue','body_text':await js('document.body.innerText'),'events':events})
                raise RuntimeError('full catalogue failed to render; see failure.json')
            await js("[...document.querySelectorAll('.catalog button')].find(b=>b.textContent.includes('EEG-REREFERENCE / reference') && b.textContent.includes('source')).click()")
            await asyncio.sleep(.2)
            await js("(()=>{const e=document.querySelector('[aria-label=\"步骤配置\"]');const s=JSON.parse(e.value);s.params.ref_channels='average';e.value=JSON.stringify(s);e.dispatchEvent(new Event('input',{bubbles:true}));return s})()")
            await js("[...document.querySelectorAll('button')].find(b=>b.textContent==='加入或更新方法步骤').click()")
            inp=json.loads(args.input_ref.read_text(encoding='utf-8'))
            await js("(()=>{const e=document.querySelector('[aria-label=\"已注册输入 ID\"]');e.value="+json.dumps(inp['id'])+";e.dispatchEvent(new Event('input',{bubbles:true}));})()")
            await asyncio.sleep(.2)
            await js("[...document.querySelectorAll('button')].find(b=>b.textContent==='绑定数据并编译执行计划').click()")
            for attempt in range(100):
                ready=await js("[...document.querySelectorAll('.preprocessing-actions button')].some(b=>!b.disabled)")
                if ready:break
                await asyncio.sleep(.3)
            else:raise RuntimeError('plan did not compile: '+str(await js('document.body.innerText')))
            await js("document.querySelector('.preprocessing-actions button').click()")
            for attempt in range(1000):
                status=await js("document.querySelector('.preprocessing-card [role=status]')?.textContent || ''")
                if '2 / 2' in status:break
                await asyncio.sleep(.3)
            else:
                write_json(root/'failure.json',{'status':status,'body_text':await js('document.body.innerText'),'events':events})
                raise RuntimeError('UI execution did not complete before browser timeout; see failure.json')
            text=await js('document.body.innerText');await js("document.querySelector('[aria-label=\"当前方法配方\"]').scrollIntoView()")
            screenshot=await call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True});(root/'execution.png').write_bytes(base64.b64decode(screenshot['data']))
            await js('window.scrollTo(0,0)');screenshot=await call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False});(root/'catalogue.png').write_bytes(base64.b64decode(screenshot['data']))
            links=await js("[...document.querySelectorAll('.preprocessing-card a')].map(a=>({name:a.textContent,url:a.href}))")
            downloaded=[]
            for name in ('axes.json','provenance.json'):
                link=next(v for v in links if v['name']==name)
                payload=json.load(urlopen(link['url']));write_json(root/('downloaded-'+name),payload)
                downloaded.append(dict(name=name,url=link['url'],sha256=file_hash(root/('downloaded-'+name))))
            module_urls=await js("[...document.scripts].filter(s=>s.src).map(s=>s.src)")
            modules=[dict(url=url,sha256=hashlib.sha256(urlopen(url).read()).hexdigest()) for url in module_urls]
            receipt=dict(url=args.url,passed=True,catalogue_rows=expected_count,numerically_verified_rows=sum(r['status']['numerically_verified'] for r in capability['rows']),capabilities_sha256=file_hash(root/'capabilities.json'),frontend_modules=modules,completed_records=2,downloaded=downloaded,body_text=text,browser_events=events,screenshots={p.name:file_hash(p) for p in root.glob('*.png')})
            write_json(root/'browser-receipt.json',receipt);print(json.dumps({k:v for k,v in receipt.items() if k not in ('body_text','browser_events')}),flush=True)
            await ws.send(json.dumps({'id':999999,'method':'Browser.close'}))
    finally:
        browser.terminate()
        try:browser.wait(timeout=10)
        except subprocess.TimeoutExpired:browser.kill()


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--input-ref',type=Path,required=True);p.add_argument('--url',default='http://127.0.0.1:8897/preprocessing/units');p.add_argument('--browser',default=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe');asyncio.run(audit(p.parse_args()))


if __name__=='__main__':main()
