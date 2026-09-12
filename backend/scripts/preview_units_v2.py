"""Local integration preview using the real API, Worker and built frontend."""
from pathlib import Path
import argparse,threading,time,sqlite3
import uvicorn
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.main import create_app
from app.core.config import Settings
from app.preprocessing.worker import Worker
from app.preprocessing.storage import write_json
from tests.preprocessing.conftest import make_dataset
from tests.preprocessing.test_integration import KEY
from tests.fakes import ScriptedLLMClient


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--port',type=int,default=8897);args=parser.parse_args();root=args.root.resolve();root.mkdir(parents=True,exist_ok=True)
    data=make_dataset(root/'bids');write_json(root/'input.json',data.model_dump(mode='json'))
    settings=Settings(database_url_override='sqlite+aiosqlite:///'+str(root/'preview.db'),brain_agent_credential_encryption_key=KEY,preprocessing_root=str(root/'store'),preprocessing_input_roots=[str(root/'bids')])
    app=create_app(settings,ScriptedLLMClient([]));ref=app.state.preprocessing.register_input(settings.default_owner_id,data);write_json(root/'input-ref.json',ref.model_dump())
    dist=Path(__file__).resolve().parents[2]/'frontend/dist'
    @app.get('/preprocessing/units',include_in_schema=False)
    def page():return FileResponse(dist/'index.html')
    app.mount('/',StaticFiles(directory=dist,html=True),name='ui')
    worker=Worker(app.state.preprocessing.store,app.state.preprocessing.allowed_roots)
    stop=threading.Event()
    def loop():
        while not stop.is_set():
            try:worker.run_once()
            except sqlite3.OperationalError as e:
                if 'locked' not in str(e):raise
                write_json(root/'preview-lock-retry.json',{'error':str(e),'time':time.time(),'action':'retry on next poll; completed attempts retained'})
            stop.wait(1)
    thread=threading.Thread(target=loop,daemon=True);thread.start()
    try:uvicorn.run(app,host='127.0.0.1',port=args.port,log_level='warning')
    finally:stop.set();thread.join(timeout=5)


if __name__=='__main__':main()
