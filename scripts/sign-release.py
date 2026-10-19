"""Sign a release with a protected key and an Android 9+ rotation proof.

Private keys/passwords stay outside this repository; never print their contents.
"""
import argparse,os,secrets,subprocess
from pathlib import Path

def find_tool(candidates):
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise SystemExit('Required Android/Java signing tool was not found')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--key-dir',default=r'D:\RuanJian\ShuJuChunChu\qingsu-signing')
    args=parser.parse_args();store=Path(args.key_dir)
    if not store.is_dir():raise SystemExit('Create a private key directory with owner-only ACL first')
    password=store/'password.txt';key=store/'release.p12';lineage=store/'signing-lineage.bin'
    sdk=Path(os.environ.get('ANDROID_SDK_ROOT') or os.environ.get('ANDROID_HOME') or r'D:\RuanJian\AndroidTools\android-sdk')
    build_tools=Path(os.environ.get('ANDROID_BUILD_TOOLS_VERSION','34.0.0'))
    signer=find_tool([sdk/'build-tools'/build_tools/'apksigner',sdk/'build-tools'/build_tools/'apksigner.bat'])
    java=Path(os.environ.get('JAVA_HOME',r'E:\BianChengGongJu\GeoServer\OpenJDK17U'))/'bin'
    keytool=find_tool([java/'keytool',java/'keytool.exe'])
    old=Path(os.environ.get('ANDROID_LEGACY_KEYSTORE',Path.home()/'.android/debug.keystore'))
    if not old.is_file():raise SystemExit('Legacy Android signing key is missing')
    if not password.exists():password.write_text(secrets.token_urlsafe(40)+'\n',encoding='ascii')
    if not key.exists():
        subprocess.run([str(keytool),'-genkeypair','-noprompt','-keystore',str(key),'-storetype','PKCS12','-alias','qingsu-release','-keyalg','RSA','-keysize','4096','-validity','10950','-dname','CN=QingSu Release,O=QingSu,C=CN','-storepass:file',str(password)],check=True)
    old_args=['--ks',str(old),'--ks-key-alias','androiddebugkey','--ks-pass','pass:android','--key-pass','pass:android']
    new_args=['--ks',str(key),'--ks-key-alias','qingsu-release','--ks-pass','file:'+str(password)]
    if not lineage.exists():raise SystemExit('Signing lineage proof is missing; it must be provisioned with the protected release key')
    subprocess.run([signer,'sign',*old_args,'--next-signer',*new_args,'--lineage',str(lineage),'--rotation-min-sdk-version','28','--debuggable-apk-permitted','false','--out',args.output,args.input],check=True)
    subprocess.run([signer,'verify','--verbose','--print-certs',args.output],check=True)
    print('Release signed with rotation proof; Android <9 retains the legacy signer for compatibility.')

if __name__=='__main__':main()
