"""One-use loopback key-entry page. Never logs or returns the submitted key."""
import argparse
import html
import re
import secrets
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
from urllib.parse import parse_qs


def run(env_file,port=8765):
    token=secrets.token_urlsafe(32);origin=f'http://127.0.0.1:{port}'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send_html(self,content,status=200):
            raw=content.encode();self.send_response(status);self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.send_header('Referrer-Policy','no-referrer');self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if self.headers.get('Host')!=f'127.0.0.1:{port}':self.send_error(403);return
            self.send_html('''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Enable Gemini — Sansad AI</title><style>body{font:17px system-ui;background:#f5f8f6;color:#213b2b;margin:0;padding:50px 20px}main{max-width:560px;margin:auto;background:white;padding:32px;border:1px solid #d7e5dc;border-radius:14px}h1{font-size:26px}p{line-height:1.6;color:#52665b}input{box-sizing:border-box;width:100%;padding:14px;font:inherit;border:1px solid #b9cdbf;border-radius:7px;margin:12px 0}button{background:#347e56;color:white;padding:13px 20px;font:inherit;border:0;border-radius:7px;cursor:pointer}small{display:block;margin-top:22px;color:#52665b}</style><main><h1>Enable Gemini for Sansad AI</h1><p>Paste your Gemini API key here. This one-use local page saves it only in the project's private .env file. Answers send your question and retrieved public source text to Google Gemini and use your API quota or billing.</p><form method="post" action="/save"><input type="hidden" name="token" value="'''+token+'''"><label for="key">Gemini API key</label><input id="key" name="key" type="password" autocomplete="off" required minlength="20" autofocus><button type="submit">Save key locally</button></form><small>Do not paste the key into chat. Nothing is stored in browser local storage. The setup service closes after saving.</small></main></html>''')
        def do_POST(self):
            if self.path!='/save' or self.headers.get('Host')!=f'127.0.0.1:{port}' or self.headers.get('Origin')!=origin:
                self.send_error(403);return
            try:length=int(self.headers.get('Content-Length','0'))
            except ValueError:self.send_error(400);return
            if not 0<length<4096:self.send_error(400);return
            form=parse_qs(self.rfile.read(length).decode())
            if not secrets.compare_digest(form.get('token',[''])[0],token):self.send_error(403);return
            key=form.get('key',[''])[0].strip()
            if not re.fullmatch(r'[A-Za-z0-9_.-]{20,}',key):
                self.send_html('<h1>Invalid key format</h1><p>Return to the setup page and paste the API key without spaces.</p>',400);return
            p=Path(env_file);text=p.read_text(encoding='utf-8') if p.exists() else ''
            for name,value in {'GEMINI_API_KEY':key,'AI_PROVIDER':'gemini','GEMINI_MODEL':'gemini-flash-lite-latest'}.items():
                pattern=rf'(?m)^\s*(?:export\s+)?{name}\s*=.*$'
                text=re.sub(pattern,lambda m:f'{name}={value}',text) if re.search(pattern,text) else text.rstrip()+f'\n{name}={value}\n'
            p.write_text(text,encoding='utf-8');key=None;text=None;form.clear()
            self.send_html('<!doctype html><title>Gemini key saved</title><main style="max-width:600px;margin:70px auto;font:20px system-ui"><h1>Gemini key saved locally</h1><p>Return to the chat and select Done. The assistant will activate Gemini and verify the AI features.</p><p>Your key is not displayed here.</p></main>')
            self.server.saved=True
    server=HTTPServer(('127.0.0.1',port),Handler);server.saved=False;server.timeout=1
    print(f'Local Gemini setup ready at {origin}',flush=True)
    while not server.saved:server.handle_request()
    server.server_close();print('Gemini key saved locally. Setup service closed.',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--env-file',default='.env');p.add_argument('--port',type=int,default=8765)
    a=p.parse_args();run(a.env_file,a.port)
