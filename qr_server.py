import os
import socket
import http.server
import socketserver
import qrcode
import io

cloud_url = "http://124.220.54.64/qingsu.apk"
display_name = "轻塑减脂塑形_v5.0_云端真数据与外卖严管版.apk"

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

ip = get_local_ip()
port = 8888
lan_url = f"http://{ip}:{port}/qingsu.apk"

print('=' * 65, flush=True)
print('    轻塑 · 减脂塑形严管伴侣 v5.0 (腾讯云真数据与外卖严管版)', flush=True)
print('=' * 65, flush=True)
print(f'\n🌐 【方式一：公网高速下载】手机任意网络/电脑均可直接打开：\n   {cloud_url}\n', flush=True)
print(f'📱 手机扫描下方公网二维码，无需连同WiFi，随时随地安装：\n', flush=True)

qr = qrcode.QRCode(border=1)
qr.add_data(cloud_url)
qr.make(fit=True)
f = io.StringIO()
qr.print_ascii(out=f)
print(f.getvalue(), flush=True)

print(f'🏡 【方式二：本地局域网备用下载】：\n   {lan_url}\n', flush=True)
print(f'📁 本地安装包物理路径：\n   {os.path.abspath(display_name)}\n', flush=True)
print('=' * 65, flush=True)
print('HTTP 局域网服务运行中... 手机下载完成后按 Ctrl+C 退出。', flush=True)

Handler = http.server.SimpleHTTPRequestHandler
os.chdir(os.path.dirname(os.path.abspath(__file__)))
with socketserver.TCPServer(('', port), Handler) as httpd:
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n服务已停止。')
