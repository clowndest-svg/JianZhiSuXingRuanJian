package com.fitcoach.shapemaster;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.Instrumentation;
import android.content.Intent;
import android.graphics.Bitmap;
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
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;
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

    private void save(Bitmap image, String name) throws Exception {
        File dir = new File(instrumentation.getTargetContext().getExternalFilesDir(null), "qa");
        dir.mkdirs();
        File stale = new File(dir, name + ".png");
        if (stale.exists()) stale.delete();
        try (FileOutputStream out = new FileOutputStream(stale)) {
            image.compress(Bitmap.CompressFormat.PNG, 100, out);
        }
    }

    /** 长说明：比屏幕一半还高，必须靠滑动才看得完。 */
    private static String longNotes() {
        StringBuilder sb = new StringBuilder("修「更新说明一长就被吃掉」。");
        for (int i = 1; i <= 22; i++) {
            sb.append("\n• 第 ").append(i).append(" 条更新说明，故意写得长一点，用来验证弹窗真的能上下滑动而不是把后半截裁掉。");
        }
        return sb.toString();
    }

    @Test(timeout = 180000)
    public void longUpdateNotesScrollAndButtonsStayOnScreen() throws Exception {
        Activity host = launchHost();
        AtomicReference<AlertDialog> ref = new AtomicReference<>();
        AtomicReference<ScrollView> scrollRef = new AtomicReference<>();
        instrumentation.runOnMainSync(() -> {
            String message = UpdateCopy.body(60, 999, "5.2 MB", longNotes());
            AlertDialog dialog = UpdateManager.showUpdateDialog(host, "发现新版本 2.9.9", message, () -> { }, () -> { });
            ref.set(dialog);
            View custom = dialog.findViewById(android.R.id.custom);
            scrollRef.set((ScrollView) ((ViewGroup) custom).getChildAt(0));
        });
        AlertDialog dialog = ref.get();
        ScrollView scroll = scrollRef.get();
        assertNotNull("弹窗没建起来", dialog);
        assertNotNull("弹窗正文不在滚动容器里", scroll);

        View content = scroll.getChildAt(0);
        for (int i = 0; i < 60 && (scroll.getHeight() <= 0 || content.getHeight() <= 0); i++) {
            instrumentation.runOnMainSync(() -> { });
            Thread.sleep(100);
        }
        final int scrollHeight = scroll.getHeight();
        final int contentHeight = content.getHeight();
        assertTrue("弹窗还没量出高度", scrollHeight > 0 && contentHeight > 0);

        // 1) 说明确实比视口高（封顶生效），不是被 TextView 自己裁掉
        assertTrue("内容没有超出视口，量不到滚动（视口 " + scrollHeight + " / 内容 " + contentHeight + "）",
                contentHeight > scrollHeight);
        int textHeight = ((TextView) content).getLayout().getHeight()
                + content.getPaddingTop() + content.getPaddingBottom();
        assertTrue("TextView 被自己裁掉了（布局高 " + textHeight + " > 视图高 " + contentHeight + "）",
                contentHeight >= textHeight);

        // 2) 顶部时还能往下滑
        final AtomicReference<Boolean> canDown = new AtomicReference<>(Boolean.FALSE);
        instrumentation.runOnMainSync(() -> canDown.set(scroll.canScrollVertically(1)));
        assertTrue("封顶后不能往下滑，用户就看不到后半段说明", canDown.get());
        assertEquals("刚打开不该已经在底部", 0, scroll.getScrollY());

        save(instrumentation.getUiAutomation().takeScreenshot(), "update-dialog-top");

        // 3) 真的滑得动，滑到底后不再能往下滑
        instrumentation.runOnMainSync(() -> scroll.fullScroll(View.FOCUS_DOWN));
        Thread.sleep(300);
        final AtomicReference<Integer> endY = new AtomicReference<>(0);
        final AtomicReference<Boolean> stillDown = new AtomicReference<>(Boolean.TRUE);
        instrumentation.runOnMainSync(() -> {
            endY.set(scroll.getScrollY());
            stillDown.set(scroll.canScrollVertically(1));
        });
        assertTrue("滑动没生效（scrollY 还是 " + endY.get() + "）", endY.get() > 0);
        assertTrue("已经到底还能往下滑，说明量到的不是真内容", !stillDown.get());
        save(instrumentation.getUiAutomation().takeScreenshot(), "update-dialog-bottom");

        // 4) 两个按钮始终在屏内：说明再长也不能把它们挤出屏幕
        final int[] box = new int[4];
        instrumentation.runOnMainSync(() -> {
            View decor = dialog.getWindow().getDecorView();
            Button go = dialog.getButton(AlertDialog.BUTTON_POSITIVE);
            Button skip = dialog.getButton(AlertDialog.BUTTON_NEUTRAL);
            int[] loc = new int[2];
            go.getLocationInWindow(loc);
            box[0] = loc[1];
            box[1] = loc[1] + go.getHeight();
            box[2] = decor.getHeight();
            int[] loc2 = new int[2];
            skip.getLocationInWindow(loc2);
            box[3] = loc2[1] + skip.getHeight();
        });
        assertTrue("按钮底部跑出屏幕（按钮底 " + box[1] + " / 窗口高 " + box[2] + "）",
                box[0] > 0 && box[1] <= box[2] && box[3] <= box[2]);

        File dir = new File(instrumentation.getTargetContext().getExternalFilesDir(null), "qa");
        dir.mkdirs();
        try (FileOutputStream out = new FileOutputStream(new File(dir, "update-dialog.json"))) {
            String record = "{\"viewport\":" + scrollHeight + ",\"content\":" + contentHeight
                    + ",\"scrollY_at_bottom\":" + endY.get() + ",\"button_bottom\":" + box[1]
                    + ",\"window_height\":" + box[2] + ",\"text_layout_height\":" + textHeight + "}";
            out.write(record.getBytes("UTF-8"));
        }
        instrumentation.runOnMainSync(dialog::dismiss);
        if (!new File(dir, "update-dialog-top.png").exists()) fail("没留下顶部截图");
        if (!new File(dir, "update-dialog-bottom.png").exists()) fail("没留下底部截图");
    }
}
