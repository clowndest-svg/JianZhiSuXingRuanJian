"""Compile the real bridge method against spies; does not certify a Douyin app version."""
import pathlib, subprocess, tempfile, unittest, xml.etree.ElementTree as ET
from test_native_media_contract import java_block
ROOT=pathlib.Path(__file__).resolve().parents[1]
STUB=r'''
class android { static class net { static class Uri {
 String value; Uri(String v){value=v;}
 static String encode(String v){return java.net.URLEncoder.encode(v,java.nio.charset.StandardCharsets.UTF_8).replace("+","%20");}
 public String toString(){return value;}
 static class Builder {
 String scheme,authority,key,value;
 Builder scheme(String s){scheme=s;return this;} Builder authority(String s){authority=s;return this;}
 Builder appendQueryParameter(String k,String v){key=k;value=v;return this;}
 Uri build(){return new Uri(scheme+"://"+authority+"?"+key+"="+encode(value));}
 }
}}}
class PM {
 boolean installed=true,resolves=true;int checks;
 void getPackageInfo(String name,int flags) throws Exception {checks++;if(!name.equals("com.ss.android.ugc.aweme"))throw new AssertionError();if(!installed)throw new Exception();}
}
class Intent {
 static final String ACTION_VIEW="view";static final int FLAG_ACTIVITY_NEW_TASK=1;
 android.net.Uri uri;String pkg;
 Intent(String action,android.net.Uri u){uri=u;}
 Intent setPackage(String p){pkg=p;return this;}void addFlags(int f){}
 Object resolveActivity(PM p){return p.resolves?new Object():null;}
}
class Context {
 PM pm=new PM();Intent started;boolean fail;
 PM getPackageManager(){return pm;}
 void startActivity(Intent i) throws Exception {if(fail)throw new Exception();started=i;}
}
public class DouyinHarness {
 Context context=new Context();String web;
 void openBrowser(String value){web=value;}
 METHOD
 static void check(boolean b){if(!b)throw new AssertionError();}
 public static void main(String[] args){
  String query="桌下划船（居家） & #教学";
  for(int mode=0;mode<4;mode++){
   DouyinHarness h=new DouyinHarness();
   h.context.pm.installed=mode!=1;h.context.pm.resolves=mode!=2;h.context.fail=mode==3;
   h.searchDouyin(query);
   check(h.context.pm.checks==1);
   if(mode==0){check(h.web==null);check(h.context.started.pkg.equals("com.ss.android.ugc.aweme"));
    check(h.context.started.uri.toString().equals("snssdk1128://search?keyword="+android.net.Uri.encode(query)));}
   else {check(h.context.started==null);check(h.web.equals("https://www.douyin.com/search/"+android.net.Uri.encode(query)+"?type=video"));}
  }
  DouyinHarness h=new DouyinHarness();h.searchDouyin(null);h.searchDouyin(" ");h.searchDouyin("x".repeat(201));check(h.context.pm.checks==0);check(h.web==null);
  System.out.println("PASS: installed, missing, unsupported, launch failure, invalid keyword");
 }
}
'''
class DouyinBridge(unittest.TestCase):
    def test_real_method_fallback_and_encoded_keyword(self):
        method=java_block((ROOT/'app/src/main/java/com/fitcoach/shapemaster/WebAppInterface.java').read_text(encoding='utf-8'),'public void searchDouyin(')
        with tempfile.TemporaryDirectory() as folder:
            p=pathlib.Path(folder);source=p/'DouyinHarness.java';source.write_text(STUB.replace('METHOD',method),encoding='utf-8')
            for command in (["javac","-encoding","UTF-8",str(source)],["java","-cp",str(p),"DouyinHarness"]):
                result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    def test_android_11_package_visibility(self):
        manifest=ET.parse(ROOT/'app/src/main/AndroidManifest.xml')
        packages={n.get('{http://schemas.android.com/apk/res/android}name') for n in manifest.findall('./queries/package')}
        self.assertIn('com.ss.android.ugc.aweme',packages)
if __name__=='__main__':unittest.main()
