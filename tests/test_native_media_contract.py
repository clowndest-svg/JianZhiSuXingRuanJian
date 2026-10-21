# -*- coding: utf-8 -*-
"""原生麦克风授权契约：从 MainActivity 提取实际 Java 逻辑，现编现跑。

Android API 由最小 spy 替代，覆盖资源/origin 白名单、系统权限结果和请求生命周期。
不复制授权实现，也不需要 Gradle；不替代真机上的 WebView/系统权限弹窗验收。
"""
import re
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVITY = ROOT / "app/src/main/java/com/fitcoach/shapemaster/MainActivity.java"
MANIFEST = ROOT / "app/src/main/AndroidManifest.xml"
ANDROID_NS = "{http://schemas.android.com/apk/res/android}"


def java_block(source, declaration):
    """按真实代码的括号边界取方法/分支，忽略字符串与注释里的括号。"""
    start = source.index(declaration)
    masked = re.sub(
        r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|/\*.*?\*/|//[^\n]*',
        lambda match: " " * len(match.group()), source, flags=re.DOTALL,
    )
    opening = masked.index("{", start)
    depth = 0
    for index in range(opening, len(masked)):
        if masked[index] == "{":
            depth += 1
        elif masked[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError("找不到 Java 块结尾：" + declaration)


STUBS = r"""
import java.net.URI;
import java.util.Arrays;

class android {
    static class Manifest {
        static class permission {
            static final String RECORD_AUDIO = "android.permission.RECORD_AUDIO";
        }
    }
    static class content {
        static class pm {
            static class PackageManager { static final int PERMISSION_GRANTED = 0; }
        }
    }
}
class Uri {
    private final URI value;
    private Uri(String value) { this.value = URI.create(value); }
    static Uri parse(String value) { return new Uri(value); }
    String getScheme() { return value.getScheme(); }
    String getHost() { return value.getHost(); }
    String getUserInfo() { return value.getUserInfo(); }
    int getPort() { return value.getPort(); }
}
class PermissionRequest {
    static final String RESOURCE_AUDIO_CAPTURE = "android.webkit.resource.AUDIO_CAPTURE";
    static final String RESOURCE_VIDEO_CAPTURE = "android.webkit.resource.VIDEO_CAPTURE";
    static final String RESOURCE_PROTECTED_MEDIA_ID = "android.webkit.resource.PROTECTED_MEDIA_ID";
    Uri origin;
    String[] resources;
    int grants, denials;
    boolean canceled, throwOnDeny, throwOnGrant;
    String[] grantedResources;
    Runnable onDeny;
    PermissionRequest(String origin, String... resources) {
        this.origin = origin == null ? null : Uri.parse(origin);
        this.resources = resources;
    }
    Uri getOrigin() { return origin; }
    String[] getResources() { return resources; }
    void grant(String[] resources) {
        if (canceled) throw new AssertionError("grant called after WebView canceled request");
        grants++;
        grantedResources = resources;
        if (throwOnGrant) throw new IllegalStateException("WebView closed");
    }
    void deny() {
        if (canceled) throw new AssertionError("deny called after WebView canceled request");
        denials++;
        if (onDeny != null) onDeny.run();
        if (throwOnDeny) throw new IllegalStateException("WebView closed");
    }
}
class Toast {
    static final int LENGTH_LONG = 1;
    static Toast makeText(Object activity, String text, int length) { return new Toast(); }
    void show() {}
}
interface ValueCallback<T> { void onReceiveValue(T value); }
class WebView {
    boolean destroyed;
    void destroy() { destroyed = true; }
}
class TestActivity {
    boolean permissionGranted, finishing, frameworkDestroyed, throwOnPrompt;
    int prompts, lastRequestCode, starts, stops;
    String[] requestedPermissions;
    int checkSelfPermission(String permission) {
        if (!android.Manifest.permission.RECORD_AUDIO.equals(permission)) {
            throw new AssertionError("unexpected permission check: " + permission);
        }
        return permissionGranted ? 0 : -1;
    }
    void requestPermissions(String[] permissions, int requestCode) {
        prompts++;
        requestedPermissions = permissions;
        lastRequestCode = requestCode;
        if (throwOnPrompt) throw new IllegalStateException("no permission dialog");
    }
    boolean isFinishing() { return finishing; }
    boolean isDestroyed() { return frameworkDestroyed; }
    public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {}
    protected void onStart() { starts++; }
    protected void onStop() { stops++; }
    protected void onDestroy() { frameworkDestroyed = true; }
}
"""

HARNESS = r"""
public class NativeMediaHarness {
    static final String ORIGIN = "https://appassets.androidplatform.net";
    static final String AUDIO = PermissionRequest.RESOURCE_AUDIO_CAPTURE;
    static final String RECORD = android.Manifest.permission.RECORD_AUDIO;
    static final int MIC_CODE = 2028;
    static void check(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }
    static PermissionRequest audio() { return new PermissionRequest(ORIGIN, AUDIO); }
    static void denied(PermissionRequest request) {
        check(request.denials == 1 && request.grants == 0, "request not denied exactly once");
    }
    static void granted(PermissionRequest request) {
        check(request.grants == 1 && request.denials == 0, "request not granted exactly once");
        check(Arrays.equals(request.grantedResources, new String[]{AUDIO}), "non-audio grant");
    }
    static void result(MainActivity activity, boolean allow) {
        activity.permissionGranted = allow;
        activity.onRequestPermissionsResult(MIC_CODE, new String[]{RECORD}, new int[]{allow ? 0 : -1});
    }
    static void trustedOrigins() {
        for (String origin : new String[]{ORIGIN, ORIGIN + "/", ORIGIN + ":443/"}) {
            MainActivity activity = new MainActivity();
            activity.permissionGranted = true;
            PermissionRequest request = new PermissionRequest(origin, AUDIO);
            activity.onPermissionRequest(request);
            granted(request);
            check(activity.prompts == 0, "already-authorized microphone prompted again");
        }
    }
    static void rejectedOrigins() {
        for (boolean hasPermission : new boolean[]{false, true}) {
            for (String origin : new String[]{null, "http://appassets.androidplatform.net",
                    "https://example.com", "https://appassets.androidplatform.net.evil.test",
                    "https://appassets.androidplatform.net@evil.test",
                    "https://user@appassets.androidplatform.net", ORIGIN + ":444",
                    "file:///assets/index.html", "data:text/html,hello", "about:blank"}) {
                MainActivity activity = new MainActivity();
                activity.permissionGranted = hasPermission;
                PermissionRequest request = new PermissionRequest(origin, AUDIO);
                activity.onPermissionRequest(request);
                denied(request);
                check(activity.prompts == 0, "untrusted origin opened Android permission dialog");
            }
        }
    }
    static void rejectedResources() {
        for (boolean hasPermission : new boolean[]{false, true}) {
            for (String[] resources : new String[][]{null, new String[]{}, new String[]{null},
                    new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE},
                    new String[]{PermissionRequest.RESOURCE_PROTECTED_MEDIA_ID},
                    new String[]{"android.webkit.resource.MIDI_SYSEX"},
                    new String[]{AUDIO, PermissionRequest.RESOURCE_VIDEO_CAPTURE},
                    new String[]{AUDIO, PermissionRequest.RESOURCE_PROTECTED_MEDIA_ID},
                    new String[]{AUDIO, "unknown.future.resource"}, new String[]{AUDIO, AUDIO}}) {
                MainActivity activity = new MainActivity();
                activity.permissionGranted = hasPermission;
                PermissionRequest request = new PermissionRequest(ORIGIN, resources);
                activity.onPermissionRequest(request);
                denied(request);
                check(activity.prompts == 0, "unsupported resources opened Android permission dialog");
            }
        }
        new MainActivity().onPermissionRequest(null);
    }
    static void systemGrant() {
        MainActivity activity = new MainActivity();
        PermissionRequest request = audio();
        activity.onPermissionRequest(request);
        check(request.grants == 0 && request.denials == 0, "premature settlement");
        check(activity.prompts == 1 && activity.lastRequestCode == MIC_CODE,
                "microphone prompt not opened exactly once");
        check(Arrays.equals(activity.requestedPermissions, new String[]{RECORD}), "extra Android permissions");
        result(activity, true);
        granted(request);
        result(activity, true);
        granted(request);
    }
    static void systemDeny() {
        MainActivity activity = new MainActivity();
        PermissionRequest request = audio();
        activity.onPermissionRequest(request);
        result(activity, false);
        denied(request);
        PermissionRequest retry = audio();
        activity.onPermissionRequest(retry);
        check(activity.prompts == 2, "denial retained pending/in-flight state");
        result(activity, true);
        granted(retry);
    }
    static void malformedResults() {
        String[][] permissions = {null, new String[]{}, new String[]{RECORD}, new String[]{RECORD},
                new String[]{"android.permission.CAMERA"},
                new String[]{"android.permission.CAMERA", RECORD},
                new String[]{RECORD, "android.permission.CAMERA"}, new String[]{RECORD}, new String[]{null}};
        int[][] results = {new int[]{0}, new int[]{}, null, new int[]{}, new int[]{0},
                new int[]{0, -1}, new int[]{-1, 0}, new int[]{0, 0}, new int[]{0}};
        for (int i = 0; i < permissions.length; i++) {
            MainActivity activity = new MainActivity();
            PermissionRequest request = audio();
            activity.onPermissionRequest(request);
            activity.permissionGranted = true;
            activity.onRequestPermissionsResult(MIC_CODE, permissions[i], results[i]);
            denied(request);
        }
    }
    static void recheckAndroidPermission() {
        MainActivity activity = new MainActivity();
        PermissionRequest request = audio();
        activity.onPermissionRequest(request);
        activity.onRequestPermissionsResult(MIC_CODE, new String[]{RECORD}, new int[]{0});
        denied(request);
        activity = new MainActivity();
        request = audio();
        activity.onPermissionRequest(request);
        activity.permissionGranted = true;
        activity.onRequestPermissionsResult(MIC_CODE, new String[]{RECORD}, new int[]{-1});
        denied(request);
    }
    static void unrelatedResult() {
        MainActivity activity = new MainActivity();
        PermissionRequest request = audio();
        activity.onPermissionRequest(request);
        activity.onRequestPermissionsResult(2026, new String[]{RECORD}, new int[]{0});
        check(request.grants == 0 && request.denials == 0, "another request code settled microphone");
        result(activity, true);
        granted(request);
    }
    static void duplicatePending() {
        MainActivity activity = new MainActivity();
        PermissionRequest old = audio();
        activity.onPermissionRequest(old);
        PermissionRequest next = audio();
        next.onDeny = () -> denied(old);
        activity.onPermissionRequest(next);
        denied(old);
        denied(next);
        check(activity.prompts == 1, "overlapping Android prompts");
        result(activity, true);
        denied(old);
        denied(next);
        PermissionRequest retry = audio();
        activity.onPermissionRequest(retry);
        granted(retry);
    }
    static void canceledPending() {
        MainActivity activity = new MainActivity();
        PermissionRequest request = audio();
        activity.onPermissionRequest(request);
        request.canceled = true;
        activity.onPermissionRequestCanceled(request);
        PermissionRequest duringDialog = audio();
        activity.onPermissionRequest(duringDialog);
        denied(duringDialog);
        result(activity, true);
        check(request.grants == 0 && request.denials == 0, "canceled request called again");
        PermissionRequest retry = audio();
        activity.onPermissionRequest(retry);
        granted(retry);
        check(activity.prompts == 1, "cancellation opened a second Android prompt");
    }
    static void unrelatedCancel() {
        MainActivity activity = new MainActivity();
        PermissionRequest request = audio();
        activity.onPermissionRequest(request);
        PermissionRequest unrelated = audio();
        unrelated.canceled = true;
        activity.onPermissionRequestCanceled(unrelated);
        result(activity, true);
        granted(request);
        check(unrelated.grants == 0 && unrelated.denials == 0, "unrelated canceled request called");
    }
    static void stoppedPending() {
        MainActivity activity = new MainActivity();
        PermissionRequest request = audio();
        activity.onPermissionRequest(request);
        activity.onStop();
        denied(request);
        activity.permissionGranted = true;
        PermissionRequest inBackground = audio();
        activity.onPermissionRequest(inBackground);
        denied(inBackground);
        activity.onStart();
        PermissionRequest beforeOldResult = audio();
        activity.onPermissionRequest(beforeOldResult);
        denied(beforeOldResult);
        result(activity, true);
        denied(request);
        PermissionRequest retry = audio();
        activity.onPermissionRequest(retry);
        granted(retry);
        check(activity.starts == 1 && activity.stops == 1, "lifecycle super callbacks lost");
    }
    static void destroyedPending() {
        MainActivity activity = new MainActivity();
        PermissionRequest request = audio();
        activity.onPermissionRequest(request);
        final boolean[] fileCanceled = {false};
        activity.filePathCallback = values -> fileCanceled[0] = values == null;
        activity.webView = new WebView();
        request.onDeny = () -> check(!activity.webView.destroyed, "WebView destroyed before pending denial");
        activity.onDestroy();
        denied(request);
        check(activity.webView.destroyed && activity.frameworkDestroyed, "existing destroy cleanup lost");
        check(fileCanceled[0] && activity.filePathCallback == null, "file chooser cleanup lost");
        result(activity, true);
        denied(request);
        // 即使模拟系统状态还没更新，原生销毁标记也必须挡住迟到请求。
        activity.frameworkDestroyed = false;
        activity.onStart();
        PermissionRequest late = audio();
        activity.onPermissionRequest(late);
        denied(late);
    }
    static void finishingOrDestroyed() {
        for (boolean destroyed : new boolean[]{false, true}) {
            MainActivity activity = new MainActivity();
            activity.permissionGranted = true;
            activity.frameworkDestroyed = destroyed;
            activity.finishing = !destroyed;
            PermissionRequest request = audio();
            activity.onPermissionRequest(request);
            denied(request);
            check(activity.prompts == 0, "unavailable Activity opened dialog");
            activity = new MainActivity();
            request = audio();
            activity.onPermissionRequest(request);
            activity.frameworkDestroyed = destroyed;
            activity.finishing = !destroyed;
            result(activity, true);
            denied(request);
        }
    }
    static void promptFailure() {
        MainActivity activity = new MainActivity();
        activity.throwOnPrompt = true;
        PermissionRequest request = audio();
        activity.onPermissionRequest(request);
        denied(request);
        result(activity, true);
        denied(request);
        activity.throwOnPrompt = false;
        activity.permissionGranted = false;
        PermissionRequest retry = audio();
        activity.onPermissionRequest(retry);
        result(activity, true);
        granted(retry);
        check(activity.prompts == 2, "failed prompt retained in-flight state");
    }
    static void closedWebView() {
        MainActivity activity = new MainActivity();
        PermissionRequest request = audio();
        request.throwOnDeny = true;
        activity.onPermissionRequest(request);
        activity.onStop();
        denied(request);
        check(activity.stops == 1, "closed request broke lifecycle cleanup");
        result(activity, true);
        denied(request);
        activity.onStart();
        request = audio();
        request.throwOnGrant = true;
        activity.onPermissionRequest(request);
        granted(request);
    }
    static void recheckRequest() {
        MainActivity activity = new MainActivity();
        PermissionRequest request = audio();
        activity.onPermissionRequest(request);
        request.origin = Uri.parse("https://example.com");
        result(activity, true);
        denied(request);
        activity = new MainActivity();
        activity.permissionGranted = false;
        request = audio();
        activity.onPermissionRequest(request);
        request.resources = new String[]{AUDIO, PermissionRequest.RESOURCE_VIDEO_CAPTURE};
        result(activity, true);
        denied(request);
    }
    public static void main(String[] args) {
        switch (args[0]) {
            case "trusted_origins": trustedOrigins(); break;
            case "rejected_origins": rejectedOrigins(); break;
            case "rejected_resources": rejectedResources(); break;
            case "system_grant": systemGrant(); break;
            case "system_deny": systemDeny(); break;
            case "malformed_results": malformedResults(); break;
            case "android_permission_recheck": recheckAndroidPermission(); break;
            case "unrelated_result": unrelatedResult(); break;
            case "duplicate_pending": duplicatePending(); break;
            case "canceled_pending": canceledPending(); break;
            case "unrelated_cancel": unrelatedCancel(); break;
            case "stopped_pending": stoppedPending(); break;
            case "destroyed_pending": destroyedPending(); break;
            case "unavailable_activity": finishingOrDestroyed(); break;
            case "prompt_failure": promptFailure(); break;
            case "closed_webview": closedWebView(); break;
            case "request_recheck": recheckRequest(); break;
            default: throw new AssertionError("unknown scenario: " + args[0]);
        }
        System.out.println("PASS " + args[0]);
    }
}
"""


class NativeMediaContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ACTIVITY.read_text(encoding="utf-8")
        start = cls.source.index("    private static final int MIC_PERM_REQUEST")
        end = cls.source.index("    private boolean hasLocationPermission()", start)
        media_logic = cls.source[start:end]
        callbacks = "\n".join(java_block(cls.source, declaration) for declaration in (
            "public void onPermissionRequest(", "public void onPermissionRequestCanceled(",
            "protected void onStart()", "protected void onStop()", "protected void onDestroy()",
        ))
        mic_result = java_block(cls.source, "if (requestCode == MIC_PERM_REQUEST)")
        fixture = STUBS + "\nclass MainActivity extends TestActivity {\n" + media_logic + callbacks + """
    ValueCallback<Uri[]> filePathCallback;
    WebView webView;
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
""" + mic_result + "\n    }\n}\n" + HARNESS
        cls.tmp = tempfile.TemporaryDirectory(prefix="qingsu-native-media-")
        cls.addClassCleanup(cls.tmp.cleanup)
        folder = Path(cls.tmp.name)
        java_file = folder / "NativeMediaHarness.java"
        java_file.write_text(fixture, encoding="utf-8")
        output = folder / "out"
        output.mkdir()
        for executable in ("javac", "java"):
            if not shutil.which(executable):
                raise AssertionError("需要 Java/JDK 才能验证原生授权逻辑：" + executable)
        compiled = subprocess.run(
            ["javac", "-encoding", "UTF-8", "-d", str(output), str(java_file)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        if compiled.returncode:
            raise AssertionError("麦克风授权 Java fixture 编译失败：" + compiled.stderr + compiled.stdout)
        cls.classpath = str(output)

    def scenario(self, name):
        done = subprocess.run(
            ["java", "-Dfile.encoding=UTF-8", "-cp", self.classpath, "NativeMediaHarness", name],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
        )
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertIn("PASS " + name, done.stdout)

    def test_manifest_microphone_is_optional(self):
        manifest = ET.parse(MANIFEST).getroot()
        permissions = [item.get(ANDROID_NS + "name") for item in manifest.findall("uses-permission")]
        self.assertEqual(permissions.count("android.permission.RECORD_AUDIO"), 1)
        features = [item for item in manifest.findall("uses-feature")
                    if item.get(ANDROID_NS + "name") == "android.hardware.microphone"]
        self.assertEqual(len(features), 1)
        self.assertEqual(features[0].get(ANDROID_NS + "required"), "false")
        self.assertNotIn("android.permission.CAMERA", permissions)

    def test_only_literal_audio_allowlist_is_granted(self):
        grants = re.findall(r"\b\w+\.grant\((.*?)\);", self.source, flags=re.DOTALL)
        self.assertEqual(grants, ["new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE}"])

    def test_stop_only_clears_media_authorization(self):
        stop = java_block(self.source, "protected void onStop()")
        statements = stop[stop.index("{") + 1:-1].split()
        self.assertEqual(" ".join(statements),
                         "mediaPermissionStopped = true; denyPendingMediaRequest(); super.onStop();")
        self.assertNotIn("pauseTimers", self.source)
        self.assertNotIn("webView.onPause", self.source)


SCENARIOS = (
    "trusted_origins", "rejected_origins", "rejected_resources", "system_grant", "system_deny",
    "malformed_results", "android_permission_recheck", "unrelated_result", "duplicate_pending",
    "canceled_pending", "unrelated_cancel", "stopped_pending", "destroyed_pending",
    "unavailable_activity", "prompt_failure", "closed_webview", "request_recheck",
)
for scenario_name in SCENARIOS:
    def scenario_test(self, name=scenario_name):
        self.scenario(name)
    setattr(NativeMediaContractTest, "test_" + scenario_name, scenario_test)


if __name__ == "__main__":
    unittest.main(verbosity=2)
