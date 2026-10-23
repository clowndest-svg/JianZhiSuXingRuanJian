"""20-theme API, backwards compatibility and public original-art delivery; isolated DB only."""
import importlib.util,os,pathlib,re,sys,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient

class BubbleThemes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT/'_audit_sandbox').mkdir(exist_ok=True)
        cls.tmp=tempfile.TemporaryDirectory(dir=ROOT/'_audit_sandbox');cls.addClassCleanup(cls.tmp.cleanup)
        for k in ['DB','UPLOAD','KEY']:os.environ['QINGSU_'+k+'_DIR']=str(pathlib.Path(cls.tmp.name)/k)
        os.environ['QINGSU_WEB_DIR']=str(ROOT/'app/src/main/assets')
        spec=importlib.util.spec_from_file_location('theme_fixture_server',ROOT/'server.py');cls.s=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.s)
        cls.s._redis_cmd=lambda *a,**k:(False,None);cls.s.rate_hit=lambda *a,**k:(True,'test',1)
        cls.c=TestClient(cls.s.app);cls.addClassCleanup(cls.c.close)
        cls.users=[]
        for n in ['themeowner','themepeer']:
            r=cls.c.post('/api/register',headers={'X-App-Build':'99'},json={'username':n,'password':'Theme!12345','age':30,'height':170,'weight_jin':160,'target_weight_jin':140})
            assert r.status_code==200,r.text
            cls.users.append(r.json())
        cls.headers={'Authorization':'Bearer '+cls.users[0]['token'],'X-App-Build':'99'}
    def test_catalogue_ids_exactly_match_server_twenty(self):
        js=(ROOT/'app/src/main/assets/bubble-themes.js').read_text(encoding='utf-8')
        ids=re.findall(r"\{id:'(skin-[a-z]+)'",js)
        self.assertEqual(len(ids),20);self.assertEqual(len(set(ids)),20)
        self.assertEqual(set(ids),{t for t in self.s.community.BUBBLE_THEMES if t.startswith('skin-')})
        shapes=re.findall(r"shape:'([^']+)'",js);self.assertEqual(len(set(shapes)),20)
    def test_every_theme_persists_without_changing_peer(self):
        peer=self.users[1]['id'];c=self.s.get_db()
        original=c.execute('SELECT bubble_theme FROM community_profile WHERE user_id=?',(peer,)).fetchone()[0];c.close()
        for theme in self.s.community.BUBBLE_THEMES:
            with self.subTest(theme=theme):
                r=self.c.post('/api/community/profile',headers=self.headers,json={'bubble_theme':theme})
                self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['bubble_theme'],theme)
                history=self.c.get('/api/chat/messages',params={'with_user':peer},headers=self.headers)
                self.assertEqual(history.json()['bubble_theme'],theme)
                c=self.s.get_db();self.assertEqual(c.execute('SELECT bubble_theme FROM community_profile WHERE user_id=?',(self.users[0]['id'],)).fetchone()[0],theme);self.assertEqual(c.execute('SELECT bubble_theme FROM community_profile WHERE user_id=?',(peer,)).fetchone()[0],original);c.close()
    def test_unknown_and_markup_ids_rejected_without_writing(self):
        self.c.post('/api/community/profile',headers=self.headers,json={'bubble_theme':'skin-cat'})
        for value in ['skin-nope','<script>alert(1)</script>','skin-ai" onclick="bad()']:
            self.assertEqual(self.c.post('/api/community/profile',headers=self.headers,json={'bubble_theme':value}).status_code,400)
        self.assertEqual(self.c.post('/api/community/profile',headers=self.headers,json={'bubble_theme':'x'*1000}).status_code,422)
        c=self.s.get_db();self.assertEqual(c.execute('SELECT bubble_theme FROM community_profile WHERE user_id=?',(self.users[0]['id'],)).fetchone()[0],'skin-cat');c.close()
    def test_original_assets_are_served_with_correct_type(self):
        for name,mime in [('bubble-themes.js','application/javascript'),('bubble-themes.css','text/css'),('bubble-ai.png','image/png'),('bubble-moon.png','image/png'),('chat-backgrounds.js','application/javascript'),('chat-backgrounds.css','text/css')]:
            r=self.c.get('/'+name);self.assertEqual(r.status_code,200);self.assertTrue(r.headers['content-type'].startswith(mime));self.assertEqual(r.content,(ROOT/'app/src/main/assets'/name).read_bytes())
    def test_art_is_not_in_install_precache(self):
        sw=(ROOT/'app/src/main/assets/sw.js').read_text(encoding='utf-8').split('const MAX_ENTRIES')[0]
        self.assertNotIn('bubble-ai.png',sw);self.assertNotIn('bubble-moon.png',sw)
if __name__=='__main__':unittest.main()
