"""Check that the release APK, version manifest and served H5 build agree."""
import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path


def build_code(blob, label):
    hit = re.search(rb"const APP_BUILD = (\d+);", blob)
    if not hit:
        raise SystemExit("%s does not declare APP_BUILD" % label)
    return int(hit.group(1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apk", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--web-app-js", required=True)
    parser.add_argument("--gradle", required=True, help="app/build.gradle")
    args = parser.parse_args()

    apk = Path(args.apk).read_bytes()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    code = int(manifest["version_code"])
    gradle_text = Path(args.gradle).read_text(encoding="utf-8")
    gradle_code = re.search(r"versionCode\s+(\d+)", gradle_text)
    gradle_name = re.search(r'versionName\s+"([^"]+)"', gradle_text)
    if not gradle_code or int(gradle_code.group(1)) != code:
        raise SystemExit("version manifest build does not match app/build.gradle")
    if not gradle_name or gradle_name.group(1) != manifest.get("version_name"):
        raise SystemExit("version manifest name does not match app/build.gradle")
    if int(manifest.get("min_version_code", 0)) != code:
        raise SystemExit("min_version_code must match version_code")
    if len(apk) != int(manifest["size"]):
        raise SystemExit("APK size does not match the version manifest")
    if hashlib.md5(apk).hexdigest() != manifest["md5"]:
        raise SystemExit("APK MD5 does not match the version manifest")
    if hashlib.sha256(apk).hexdigest() != manifest.get("sha256"):
        raise SystemExit("APK SHA-256 does not match the version manifest")
    web_build = build_code(Path(args.web_app_js).read_bytes(), "web app.js")
    if web_build != code:
        raise SystemExit("web app.js build %d does not match manifest %d" % (web_build, code))
    with zipfile.ZipFile(args.apk) as archive:
        js_name = next((name for name in archive.namelist() if name.endswith("assets/app.js")), None)
        if not js_name:
            raise SystemExit("APK does not include assets/app.js")
        apk_build = build_code(archive.read(js_name), "APK app.js")
        for name in ('app.js','features.js','companion.js','sw.js','index.html','style.css','features.css',
                     'bubble-themes.js','bubble-themes.css','bubble-ai.png','bubble-moon.png','chat-backgrounds.js','chat-backgrounds.css','chat-tools.js','chat-tools.css'):
            local = Path(args.web_app_js).parent / name
            if archive.read('assets/'+name) != local.read_bytes():
                raise SystemExit('APK and served H5 differ: '+name)
    if apk_build != code:
        raise SystemExit("APK app.js build %d does not match manifest %d" % (apk_build, code))
    print("release artifacts agree: version_code=%d size=%d sha256=%s" %
          (code, len(apk), manifest["sha256"][:12]))


if __name__ == "__main__":
    main()
