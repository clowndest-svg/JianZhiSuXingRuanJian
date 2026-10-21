"""Isolated real API and decoder checks for voice and sticker messages."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from PIL import Image
from app_modules import audio, stickers


class ChatMedia(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        cls.addClassCleanup(cls.temp.cleanup)
        for key in ('DB', 'UPLOAD', 'KEY'):
            os.environ['QINGSU_' + key + '_DIR'] = str(cls.folder / key)
        os.environ['QINGSU_WEB_DIR'] = str(ROOT / 'app/src/main/assets')
        spec = importlib.util.spec_from_file_location('media_test_server', ROOT / 'server.py')
        cls.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.m)
        cls.m._redis_cmd = lambda *a, **k: (False, None)
        cls.m.rate_hit = lambda *a, **k: (True, 'test', 1)
        cls.c = TestClient(cls.m.app)
        cls.addClassCleanup(cls.c.close)
        cls.users = []
        for index in range(3):
            r = cls.c.post('/api/register', json=dict(username='mediauser' + str(index), password='Review!123',
                age=30, height=170, weight_jin=160, target_weight_jin=140))
            assert r.status_code == 200, r.text
            cls.users.append(r.json())
        cls.ids = []
        for u in cls.users:
            cls.ids.append(cls.c.get('/api/account', headers={'Authorization': 'Bearer ' + u['token']}).json().get('id'))
        # Use the authoritative DB ID (account response shape is independent).
        conn = cls.m.get_db()
        cls.ids = [conn.execute('SELECT id FROM users WHERE username=?', ('mediauser' + str(i),)).fetchone()[0] for i in range(3)]
        conn.close()
        ffmpeg = audio._tool('ffmpeg')
        for ext, options in [('webm', ['-c:a', 'libopus']), ('m4a', ['-c:a', 'aac']),
                             ('ogg', ['-c:a', 'libopus']), ('aac', ['-c:a', 'aac', '-f', 'adts'])]:
            subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                'sine=frequency=440:sample_rate=24000', '-t', '1', *options, str(cls.folder / ('voice.' + ext))], check=True)

    def auth(self, who=0):
        return {'Authorization': 'Bearer ' + self.users[who]['token']}

    def send(self, kind, who=0, **kw):
        return self.c.post('/api/chat/send', headers=self.auth(who),
            json={'to': self.ids[1], 'kind': kind, **kw})

    def upload(self, ext='ogg', who=0):
        mime = {'ogg': 'audio/ogg', 'aac': 'audio/aac', 'm4a': 'audio/mp4', 'webm': 'audio/webm'}[ext]
        return self.c.post('/api/chat/media', headers=self.auth(who), data={'to': self.ids[1]},
            files={'file': ('voice.' + ext, (self.folder / ('voice.' + ext)).read_bytes(), mime)})

    def picture(self, fmt='PNG'):
        out = io.BytesIO()
        Image.new('RGBA', (20, 20), (20, 180, 90, 255)).save(out, format=fmt)
        return out.getvalue()

    def test_voice_all_containers_and_authoritative_duration(self):
        for ext in ('webm', 'm4a', 'ogg', 'aac'):
            with self.subTest(ext=ext):
                up = self.upload(ext)
                self.assertEqual(up.status_code, 200, up.text)
                data = up.json()
                self.assertEqual(data['mime'], 'audio/ogg')
                self.assertIn(data['duration'], (1, 2))
                self.assertEqual(self.c.get(data['url']).headers['content-type'], 'audio/ogg')
                rid = 'voice-' + ext
                sent = self.send('audio', media_name=data['name'], duration=999999, request_id=rid)
                self.assertEqual(sent.status_code, 200, sent.text)
                self.assertEqual(sent.json()['message']['duration'], data['duration'])
                again = self.send('audio', media_name=data['name'], request_id=rid)
                self.assertTrue(again.json()['duplicate'])
                self.assertEqual(again.json()['message']['id'], sent.json()['message']['id'])

    def test_voice_duration_rounds_to_nearest_second(self):
        # 1 秒整的语音显示 1″；向上取整会显示 2″（r170 及以前）。
        for ext in ('ogg', 'webm'):
            with self.subTest(ext=ext):
                up = self.upload(ext)
                self.assertEqual(up.status_code, 200, up.text)
                self.assertEqual(up.json()['duration'], 1)

    def test_asr_contract_denies_strangers_and_stays_honest(self):
        up = self.upload('ogg').json()
        sent = self.send('audio', media_name=up['name'], request_id='asr-p').json()['message']
        text_msg = self.c.post('/api/chat/send', headers=self.auth(),
            json={'to': self.ids[1], 'text': '文字消息', 'request_id': 'asr-t'}).json()['message']
        stranger = self.c.post('/api/chat/asr', headers=self.auth(2), json={'message_id': sent['id']})
        self.assertEqual(stranger.status_code, 404)
        wrong_kind = self.c.post('/api/chat/asr', headers=self.auth(), json={'message_id': text_msg['id']})
        self.assertEqual(wrong_kind.status_code, 400)
        # 本机没有配置 ASR 时必须明说不可用（不能假装转了）
        r = self.c.post('/api/chat/asr', headers=self.auth(), json={'message_id': sent['id']})
        self.assertIn(r.status_code, (200, 503))
        if r.status_code == 503:
            self.assertIn('暂不可用', r.json()['detail'])
        else:
            self.assertIsInstance(r.json().get('text'), str)

    def test_asr_result_is_cached_on_the_message(self):
        up = self.upload('ogg').json()
        sent = self.send('audio', media_name=up['name'], request_id='asr-c').json()['message']
        with patch.object(self.m.asr, 'transcribe', return_value='你好，这是转出来的文字。'):
            r = self.c.post('/api/chat/asr', headers=self.auth(), json={'message_id': sent['id']})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['text'], '你好，这是转出来的文字。')
        with patch.object(self.m.asr, 'transcribe', side_effect=AssertionError('should use cache')):
            again = self.c.post('/api/chat/asr', headers=self.auth(1), json={'message_id': sent['id']})
        self.assertEqual(again.json()['text'], '你好，这是转出来的文字。')
        self.assertTrue(again.json().get('cached'))
        listed = self.c.get('/api/chat/messages?with_user=' + str(self.ids[0]),
                            headers=self.auth(1)).json()['items']
        row = [item for item in listed if item['id'] == sent['id']][0]
        self.assertEqual(row['asr_text'], '你好，这是转出来的文字。')

    def test_missing_and_stolen_voice_rejected(self):
        self.assertEqual(self.send('audio', media_name='missing.audio.ogg').status_code, 400)
        up = self.upload(who=2).json()
        self.assertEqual(self.send('audio', media_name=up['name']).status_code, 400)

    def test_fake_audio_and_oversized_cleaned(self):
        before = set(Path(self.m.UPLOAD_DIR).iterdir())
        for blob, status in [(b'OggS' + b'fake' * 40, 400), (b'x' * (5 * 1024 * 1024 + 1), 413)]:
            r = self.c.post('/api/chat/media', headers=self.auth(), data={'to': self.ids[1]},
                files={'file': ('voice.ogg', blob, 'audio/ogg')})
            self.assertEqual(r.status_code, status, r.text)
        self.assertEqual(before, set(Path(self.m.UPLOAD_DIR).iterdir()))

    def test_video_track_disguised_as_audio_and_long_voice(self):
        for label, args in [('video', ['-f', 'lavfi', '-i', 'color=size=16x16:rate=1', '-t', '1', '-c:v', 'libvpx']),
                            ('long', ['-f', 'lavfi', '-i', 'anullsrc=r=24000:cl=mono', '-t', '601', '-c:a', 'libopus'])]:
            path = self.folder / (label + '.webm')
            subprocess.run([audio._tool('ffmpeg'), '-nostdin', '-v', 'error', '-y', *args, str(path)], check=True)
            r = self.c.post('/api/chat/media', headers=self.auth(), data={'to': self.ids[1]},
                files={'file': ('voice.webm', path.read_bytes(), 'audio/webm')})
            self.assertEqual(r.status_code, 400, r.text)
        self.assertFalse(list(Path(self.m.UPLOAD_DIR).glob('*.part')))

    def test_sticker_upload_send_replay_and_recall(self):
        for fmt in ('PNG', 'GIF'):
            up = self.c.post('/api/chat/stickers/upload', headers=self.auth(),
                files={'file': ('sticker.' + fmt.lower(), self.picture(fmt), 'image/' + fmt.lower())})
            self.assertEqual(up.status_code, 200, up.text)
            sent = self.send('sticker', media_name=up.json()['name'], request_id='sticker-' + fmt)
            self.assertEqual(sent.status_code, 200, sent.text)
            message = sent.json()['message']
            self.assertEqual(self.c.get(message['media_url']).status_code, 200)
            self.assertEqual(self.c.get(message['media_url'].split('?')[0]).status_code, 404)
            self.assertEqual(self.c.post('/api/chat/recall', headers=self.auth(), json={'message_id': message['id']}).status_code, 200)
            rows = self.c.get('/api/chat/messages', params={'with_user': self.ids[1]}, headers=self.auth()).json()['items']
            recalled = next(x for x in rows if x['id'] == message['id'])
            self.assertEqual(recalled['media_url'], '')

    def test_sticker_type_owner_and_invalid_content(self):
        up = self.upload().json()
        self.assertEqual(self.send('sticker', media_name=up['name']).status_code, 400)
        stolen = self.c.post('/api/chat/stickers/upload', headers=self.auth(2), files={'file': ('x.png', self.picture(), 'image/png')}).json()
        self.assertEqual(self.send('sticker', media_name=stolen['name']).status_code, 400)
        r = self.c.post('/api/chat/stickers/upload', headers=self.auth(), files={'file': ('x.svg', b'<svg/>', 'image/png')})
        self.assertEqual(r.status_code, 400)

    def test_sticker_search_route_reports_fallback_sources(self):
        with patch.object(stickers, 'search', return_value={
                'items': [], 'provider': '中文梗图', 'available': False, 'detail': '没搜到',
                'sources': ['360 图片'], 'unavailable': ['百度图片']}):
            r = self.c.get('/api/chat/stickers/search', params={'q': '你好', 'provider': 'cn'},
                           headers=self.auth())
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body['available'], False)
        self.assertEqual(body['sources'], ['360 图片'])
        self.assertEqual(body['unavailable'], ['百度图片'])
        self.assertEqual(body['detail'], '没搜到')

    def test_official_manifest_assets_and_validation(self):
        manifest = self.c.get('/stickers.json')
        self.assertEqual(manifest.status_code, 200)
        self.assertEqual(len(manifest.json()['items']), 18)
        for item in manifest.json()['items']:
            self.assertEqual(self.c.get('/' + item['file']).status_code, 200)
        self.assertEqual(self.send('sticker', text='qs:smile').status_code, 200)
        self.assertEqual(self.send('sticker', text='qs:unknown').status_code, 400)
        self.assertEqual(self.c.get('/stickers/%2e%2e%5cserver.py').status_code, 404)

    def test_network_import_metadata_and_outage(self):
        meta = dict(title='fixture', author='Test Artist', license='CC0', source_url='https://commons.wikimedia.org/wiki/File:Fixture.png')
        with patch.object(stickers, 'import_media', return_value=(self.picture(), meta)):
            up = self.c.post('/api/chat/stickers/import', headers=self.auth(), json={'id': 'fixture'})
        sent = self.send('sticker', media_name=up.json()['name'])
        self.assertEqual(sent.json()['message']['sticker_meta'], meta)
        with patch.object(stickers, 'search', side_effect=stickers.ProviderUnavailable):
            r = self.c.get('/api/chat/stickers/search?q=happy', headers=self.auth())
            self.assertFalse(r.json()['available'])
        self.assertEqual(self.c.get('/api/chat/stickers/search?q=happy').status_code, 401)

    def test_blocking_and_mutual_follow_boundaries(self):
        r = self.c.post('/api/chat/media', headers=self.auth(), data={'to': self.ids[1]}, files={'file': ('x.png', self.picture(), 'image/png')})
        self.assertEqual(r.status_code, 403)
        self.c.post('/api/chat/block', headers=self.auth(1), json={'with_user': self.ids[0], 'on': True})
        self.assertEqual(self.upload().status_code, 403)
        self.assertEqual(self.send('sticker', text='qs:smile').status_code, 403)
        self.c.post('/api/chat/block', headers=self.auth(1), json={'with_user': self.ids[0], 'on': False})


class ProviderSecurity(unittest.TestCase):
    def test_meme_catalog_search_import_and_source_boundaries(self):
        catalog = json.dumps([{'id':'cat','name':'Classic Cat','blank':'https://api.memegen.link/images/cat.jpg',
            'keywords':['cat'],'source':'http://knowyourmeme.com/memes/cat'}]).encode()
        image=io.BytesIO();Image.new('RGB',(10,10)).save(image,format='JPEG')
        def opener(request,timeout):
            url=request.full_url;r=io.BytesIO(catalog if url==stickers.MEME_API else image.getvalue())
            r.headers={'Content-Type':'application/json' if url==stickers.MEME_API else 'image/jpeg'}
            r.getcode=lambda:200;r.geturl=lambda:url;return r
        with patch.object(stickers,'_memes',(0,())):
            result=stickers.search('猫',1,b'key',provider='memegen',opener=opener)
            self.assertEqual(len(result['items']),1)
            self.assertTrue(result['items'][0]['preview_url'].endswith('?width=240'))
            token=result['items'][0]['id'];blob,meta=stickers.import_media(token,1,b'key',opener=opener)
            self.assertEqual(blob,image.getvalue());self.assertIn('未声明',meta['license'])
            self.assertTrue(meta['source_url'].startswith('https://knowyourmeme.com/'))
            with self.assertRaises(stickers.InvalidSticker):stickers.import_media(token,2,b'key',opener=opener)
        for url in ['https://api.memegen.link/images/../../secret.jpg','https://api.memegen.link.evil.test/images/cat.jpg','https://api.memegen.link/images/cat.jpg/extra']:
            with self.assertRaises(stickers.InvalidSticker):stickers._media_url(url)

    def test_openmoji_catalog_import_and_user_binding(self):
        catalog = json.dumps([{'hexcode': '1F600', 'annotation': 'grinning face', 'tags': 'happy smile', 'openmoji_author': 'Test artist'}]).encode()
        image = io.BytesIO(); Image.new('RGB', (10, 10)).save(image, format='PNG')
        def opener(request, timeout):
            url = request.full_url
            r = io.BytesIO(catalog if url == stickers.OPENMOJI_CATALOG else image.getvalue())
            r.headers = {'Content-Type': 'text/plain' if url == stickers.OPENMOJI_CATALOG else 'image/png'}
            r.getcode = lambda: 200
            r.geturl = lambda: url
            return r
        with patch.object(stickers, '_openmoji', (0, ())):
            result = stickers.search('开心', 1, b'key', opener=opener)
            self.assertEqual(len(result['items']), 1)
            self.assertEqual(result['provider'], 'OpenMoji')
            token = result['items'][0]['id']
            blob, meta = stickers.import_media(token, 1, b'key', opener=opener)
            self.assertEqual(blob, image.getvalue())
            self.assertEqual(meta['license'], 'CC BY-SA 4.0')
            with self.assertRaises(stickers.InvalidSticker): stickers.import_media(token, 2, b'key', opener=opener)
        for url in [stickers.OPENMOJI_BASE + '../secret', stickers.OPENMOJI_BASE + 'color/72x72/../../x.png']:
            with self.assertRaises(stickers.InvalidSticker): stickers._media_url(url)

    def test_signed_ids_are_user_bound_expiring_and_tamper_proof(self):
        token = stickers._sign(42, 1, b'secret')
        self.assertEqual(stickers._verify(token, 1, b'secret'), 42)
        for value, uid, key in [(token, 2, b'secret'), (token, 1, b'other'), (token + 'x', 1, b'secret')]:
            with self.assertRaises(stickers.InvalidSticker): stickers._verify(value, uid, key)
        with patch.object(stickers.time, 'time', return_value=0): old = stickers._sign(42, 1, b'secret')
        with self.assertRaises(stickers.InvalidSticker): stickers._verify(old, 1, b'secret')

    def test_media_ssrf_boundaries(self):
        for url in ['http://upload.wikimedia.org/wikipedia/commons/a.png', 'https://127.0.0.1/x',
                    'https://upload.wikimedia.org.evil.test/wikipedia/commons/a',
                    'https://x@upload.wikimedia.org/wikipedia/commons/a',
                    'https://upload.wikimedia.org:444/wikipedia/commons/a',
                    'https://upload.wikimedia.org/wikipedia/commons/%2e%2e/x']:
            with self.subTest(url=url), self.assertRaises(stickers.InvalidSticker): stickers._media_url(url)

    def test_chinese_sources_fallback_import_and_boundaries(self):
        image = io.BytesIO()
        Image.new('RGB', (10, 10), (20, 180, 90)).save(image, format='JPEG')
        image_bytes = image.getvalue()
        list360 = json.dumps({'list': [{
            'thumb': 'https://p1.ssl.qhimgs1.com/t' + 'a' * 16 + '.jpg',
            'title': '你好表情包', 'site': 'fabiaoqing.com',
            'link': 'https://fabiaoqing.com/detail/1', 'width': '300', 'height': '300'}]}).encode()
        list360_empty = json.dumps({'list': []}).encode()
        list_baidu = json.dumps({'data': [{
            'middleURL': 'https://img1.baidu.com/it/u=1,2&fm=253&f=JPEG?w=300&h=300',
            'fromPageTitleEnc': '你好梗图', 'fromURLHost': 'xiaohongshu.com'}]}).encode()

        def opener(request, timeout):
            url = request.full_url
            body = (list360 if url.startswith(stickers.SO360_API)
                    else list_baidu if url.startswith(stickers.BAIDU_API)
                    else image_bytes)
            response = io.BytesIO(body)
            response.headers = {'Content-Type': 'application/json' if body in (list360, list_baidu)
                                else 'image/jpeg'}
            response.getcode = lambda: 200
            response.geturl = lambda: url
            return response

        with patch.object(stickers, '_cn_search', stickers.OrderedDict()), \
                patch.object(stickers, '_cn_results', stickers.OrderedDict()):
            result = stickers.search('你好', 1, b'key', provider='cn', opener=opener)
            self.assertTrue(result['available'])
            self.assertIn('360 图片', result['sources'])
            self.assertEqual(len(result['items']), 2)
            token = result['items'][0]['id']
            blob, meta = stickers.import_media(token, 1, b'key', opener=opener)
            self.assertEqual(blob, image_bytes)
            self.assertEqual(meta['license'], stickers.CN_LICENSE)
            self.assertTrue(meta['source_url'].startswith('https://'))
            with self.assertRaises(stickers.InvalidSticker):
                stickers.import_media(token, 2, b'key', opener=opener)

        def baidu_only(request, timeout):
            url = request.full_url
            body = list360_empty if url.startswith(stickers.SO360_API) else (
                list_baidu if url.startswith(stickers.BAIDU_API) else image_bytes)
            response = io.BytesIO(body)
            response.headers = {'Content-Type': 'application/json' if body in (list360_empty, list_baidu)
                                else 'image/jpeg'}
            response.getcode = lambda: 200
            response.geturl = lambda: url
            return response

        with patch.object(stickers, '_cn_search', stickers.OrderedDict()), \
                patch.object(stickers, '_cn_results', stickers.OrderedDict()):
            result = stickers.search('你好', 1, b'key', provider='cn', opener=baidu_only)
            self.assertEqual(result['sources'], ['百度图片'])
            self.assertEqual(result['items'][0]['source_label'], '百度图片')

        for url in ['https://p1.ssl.qhimgs1.com/../secret.jpg',
                    'https://p1.ssl.qhimgs1.com.evil.test/t' + 'a' * 16 + '.jpg',
                    'https://evil.test/t' + 'a' * 16 + '.jpg',
                    'https://img1.baidu.com/it/u=1,2/../../secret',
                    'https://img1.baidu.com/not-it/u=1,2']:
            with self.subTest(url=url), self.assertRaises(stickers.InvalidSticker):
                stickers._media_url(url)


if __name__ == '__main__': unittest.main(verbosity=2)
