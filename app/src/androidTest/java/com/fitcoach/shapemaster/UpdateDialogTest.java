package com.fitcoach.shapemaster;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.Instrumentation;
import android.content.Intent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.ScrollView;
import android.widget.TextView;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.Test;
import org.junit.runner.RunWith;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.fail;

/**
 * 更新弹窗在真机上必须真的能上下滑。
 * <p>
 * 为什么必须上设备：r174 那次把高度封顶加在了 TextView 上，文本自己裁掉、ScrollView
 * 永远撑不满，静态判据（"有 ScrollView"、"setView(scroll)"）当时全绿，机主实拍却是
 * 长说明被吃掉半行、按不动。只有真量一次"内容比视口高 + 滑得动 + 按钮还在屏内"才算修好。
 */
@RunWith(AndroidJUnit4.class)
public class UpdateDialogTest {

    private final Instrumentation instrumentation = InstrumentationRegistry.getInstrumentation();

    /** 一次弹窗测量的全部读数；断言只说"过了"，看图的人要能对上号。 */
    private static final class Probe {
        int viewport, content, textLayout, scrollYAtBottom, buttonBottom, skipBottom, windowHeight;
        boolean canDownAtTop, canDownAtBottom;
        ScrollView scroll;
        AlertDialog dialog;
    }

    private Activity launchHost() throws Exception {
        Intent intent = new Intent(instrumentation.getTargetContext(), MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        instrumentation.getTargetContext().startActivity(intent);
        AtomicReference<Activity> resumed = new AtomicReference<>();
        for (int i = 0; i < 100 && resumed.get() == null; i++) {
            instrumentation.runOnMainSync(() -> {
                for (android.app.Activity a : androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
                        .getInstance().getActivitiesInStage(androidx.test.runner.lifecycle.Stage.RESUMED)) {
                    if (a instanceof MainActivity) resumed.set(a);
                }
            });
            Thread.sleep(100);
        }
        assertNotNull("App activity did not resume", resumed.get());
        return resumed.get();
    }

    /** 走产品同一个建弹窗函数，量视口/内容/滚动/按钮位置。 */
    private Probe probe(Activity host, String title, String message) throws Exception {
        AtomicReference<Probe> holder = new AtomicReference<>(new Probe());
        instrumentation.runOnMainSync(() -> {
            Probe p = holder.get();
            p.dialog = UpdateManager.showUpdateDialog(host, title, message, () -> { }, () -> { });
            View custom = p.dialog.findViewById(android.R.id.custom);
            ViewGroup panel = (ViewGroup) custom;
            p.scroll = (ScrollView) panel.getChildAt(0);
        });
        Probe p = holder.get();
        ScrollView scroll = p.scroll;
        assertNotNull("弹窗正文不在滚动容器里", scroll);
        View content = scroll.getChildAt(0);
        for (int i = 0; i < 60 && (scroll.getHeight() <= 0 || content.getHeight() <= 0); i++) {
            instrumentation.runOnMainSync(() -> { });
            Thread.sleep(100);
        }
        final AtomicReference<Boolean> downAtTop = new AtomicReference<>(Boolean.FALSE);
        instrumentation.runOnMainSync(() -> downAtTop.set(scroll.canScrollVertically(1)));
        p.viewport = scroll.getHeight();
        p.content = content.getHeight();
        p.textLayout = ((TextView) content).getLayout().getHeight()
                + content.getPaddingTop() + content.getPaddingBottom();
        p.canDownAtTop = downAtTop.get();
        assertEquals("刚打开不该已经在底部", 0, scroll.getScrollY());
        instrumentation.runOnMainSync(() -> scroll.fullScroll(View.FOCUS_DOWN));
        Thread.sleep(300);
        final AtomicReference<Integer> endY = new AtomicReference<>(0);
        final AtomicReference<Boolean> stillDown = new AtomicReference<>(Boolean.TRUE);
        instrumentation.runOnMainSync(() -> {
            endY.set(scroll.getScrollY());
            stillDown.set(scroll.canScrollVertically(1));
        });
        p.scrollYAtBottom = endY.get();
        p.canDownAtBottom = stillDown.get();
        final int[] box = new int[3];
        instrumentation.runOnMainSync(() -> {
            View decor = p.dialog.getWindow().getDecorView();
            Button go = p.dialog.getButton(AlertDialog.BUTTON_POSITIVE);
            Button skip = p.dialog.getButton(AlertDialog.BUTTON_NEUTRAL);
            int[] loc = new int[2];
            go.getLocationInWindow(loc);
            box[0] = loc[1] + go.getHeight();
            int[] loc2 = new int[2];
            skip.getLocationInWindow(loc2);
            box[1] = loc2[1] + skip.getHeight();
            box[2] = decor.getHeight();
        });
        p.buttonBottom = box[0];
        p.skipBottom = box[1];
        p.windowHeight = box[2];
        return p;
    }

    private void assertReadable(Probe p, String label) {
        assertTrue(label + "：弹窗还没量出高度（视口 " + p.viewport + " / 内容 " + p.content + "）",
                p.viewport > 0 && p.content > 0);
        assertTrue(label + "：正文被 TextView 自己裁掉了（布局高 " + p.textLayout + " > 视图高 "
                + p.content + "）", p.content >= p.textLayout);
        if (p.content > p.viewport) {
            assertTrue(label + "：内容超出视口却滑不动", p.canDownAtTop);
            assertTrue(label + "：滑到底还能往下滑（scrollY " + p.scrollYAtBottom + "）", !p.canDownAtBottom);
            assertTrue(label + "：滑到底没真的移动（scrollY 还是 " + p.scrollYAtBottom + "）",
                    p.scrollYAtBottom > 0);
        }
        assertTrue(label + "：按钮被挤出屏幕（去下载底 " + p.buttonBottom + " / 窗口高 " + p.windowHeight + "）",
                p.buttonBottom > 0 && p.buttonBottom <= p.windowHeight);
        assertTrue(label + "：按钮被挤出屏幕（这次不更新底 " + p.skipBottom + " / 窗口高 " + p.windowHeight + "）",
                p.skipBottom > 0 && p.skipBottom <= p.windowHeight);
    }

    private void dump(String name, String text) throws Exception {
        File dir = new File(instrumentation.getTargetContext().getExternalFilesDir(null), "qa");
        dir.mkdirs();
        try (FileOutputStream out = new FileOutputStream(new File(dir, name))) {
            out.write(text.getBytes("UTF-8"));
        }
    }

    /** 比屏幕一半高得多的说明：必须能一路滑到底，两个按钮始终在屏内。 */
    @Test(timeout = 180000)
    public void longUpdateNotesScrollAndButtonsStayOnScreen() throws Exception {
        Activity host = launchHost();
        StringBuilder notes = new StringBuilder("修「更新说明一长就被吃掉」。");
        for (int i = 1; i <= 22; i++) {
            notes.append("\n• 第 ").append(i).append(" 条更新说明，故意写得长一点，用来验证弹窗真的能上下滑动而不是把后半截裁掉。");
        }
        Probe p = probe(host, "发现新版本 2.9.9", UpdateCopy.body(60, 999, "5.2 MB", notes.toString()));
        assertTrue("22 条说明居然没溢出（视口 " + p.viewport + " / 内容 " + p.content + "），量不到滚动",
                p.content > p.viewport);
        assertReadable(p, "长说明");
        dump("update-dialog.json", "{\"viewport\":" + p.viewport + ",\"content\":" + p.content
                + ",\"text_layout\":" + p.textLayout + ",\"scrollY_at_bottom\":" + p.scrollYAtBottom
                + ",\"button_bottom\":" + p.buttonBottom + ",\"window_height\":" + p.windowHeight + "}");
        instrumentation.runOnMainSync(() -> p.dialog.dismiss());
    }

    /** 线上清单里那份真实文案：同样不许裁正文、不许把按钮顶出屏幕。 */
    @Test(timeout = 180000)
    public void liveManifestNoteStaysReadable() throws Exception {
        Activity host = launchHost();
        HttpURLConnection c = (HttpURLConnection) new URL(BuildConfig.API_BASE_URL + "/version.json").openConnection();
        c.setConnectTimeout(15000);
        c.setReadTimeout(15000);
        c.setRequestProperty("Cache-Control", "no-cache");
        String json = null;
        try (InputStream in = c.getInputStream()) {
            java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = in.read(buf)) > 0) bo.write(buf, 0, n);
            json = new String(bo.toByteArray(), "UTF-8");
        } finally {
            c.disconnect();
        }
        assertNotNull("读不到线上版本清单", json);
        org.json.JSONObject o = new org.json.JSONObject(json);
        int remote = o.optInt("version_code", 0);
        String notes = o.optString("notes", "");
        assertTrue("线上清单没带更新说明", notes.length() > 0);
        Probe p = probe(host, "发现新版本 " + o.optString("version_name", String.valueOf(remote)),
                UpdateCopy.body(60, remote, "5.2 MB", notes));
        assertReadable(p, "线上文案");
        dump("update-dialog-live.json", "{\"remote\":" + remote + ",\"notes_chars\":" + notes.length()
                + ",\"viewport\":" + p.viewport + ",\"content\":" + p.content
                + ",\"text_layout\":" + p.textLayout + ",\"scrollY_at_bottom\":" + p.scrollYAtBottom
                + ",\"button_bottom\":" + p.buttonBottom + ",\"window_height\":" + p.windowHeight + "}");
        instrumentation.runOnMainSync(() -> p.dialog.dismiss());
    }
}
